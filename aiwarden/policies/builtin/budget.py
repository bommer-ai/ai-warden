"""
Budget policy — blocks requests when accumulated spend exceeds the limit.

Cost recording happens at the system level (engine.record_llm_cost) after every
LLM call. This policy only needs a pre-hook to check the limit.

NOTE: Spend is tracked in-memory within this process only. In multi-process
deployments (gunicorn workers, Kubernetes pods), each process has independent
spend tracking. For distributed enforcement, set AIWARDEN_REDIS_URL.
"""
import logging
import threading
from datetime import datetime, timezone
from typing import Optional

from aiwarden.policies.base import Block, Policy

log = logging.getLogger(__name__)


class BudgetPolicy(Policy):
    """
    Tracks LLM spend and blocks requests when budget is exceeded.

    pre()  — checks accumulated spend before calling LLM. Blocks if over limit.
    post() — records actual cost after LLM responds.

    Config:
        group_by: metadata.team
        limits:
          engineering: 500.00
          default: 100.00
        reset: monthly
        priority: 10
    """

    name          = "budget-control"
    priority      = 10
    default_hooks = ["pre"]

    def __init__(self, config: dict = None):
        super().__init__(config)
        self._spend: dict[str, dict[str, float]] = {}
        self._lock = threading.Lock()

    def pre(self, request: dict) -> tuple[dict, Optional[Block]]:
        group = self._get_group(request)
        limit = self._get_limit(request, group)
        spend = self._get_spend(group)

        log.debug("[aiwarden] budget check — group=%s spend=%.4f limit=%.2f", group, spend, limit)

        if spend >= limit:
            return request, Block(
                f"Budget exceeded for '{group}': ${spend:.4f} / ${limit:.2f} "
                f"({self.config.get('reset', 'monthly')})"
            )
        return request, None

    def record_cost(self, request: dict, cost: float):
        """Called by the engine after every LLM call with the actual cost."""
        group = self._get_group(request)
        self._add_spend(group, cost)
        log.debug("[aiwarden] budget recorded — group=%s cost=%.6f", group, cost)

    # ── spend helpers ─────────────────────────────────────────────────────

    def _get_group(self, request: dict) -> str:
        path = self.config.get("group_by", "")
        if not path:
            return "__global__"
        node = request
        for key in path.split("."):
            if not isinstance(node, dict):
                return "__global__"
            node = node.get(key, "")
        return str(node) if node else "__global__"

    def _get_limit(self, request: dict, group: str) -> float:
        if flat := self.config.get("limit"):
            return float(flat)

        limits = self.config.get("limits", {})

        if isinstance(limits, list):
            default_limit = float("inf")
            for entry in limits:
                if "default" in entry:
                    default_limit = float(entry["default"])
                    continue
                when = entry.get("when", {})
                if self._matches_when(request, when):
                    return float(entry.get("limit", float("inf")))
            return default_limit

        if isinstance(limits, dict):
            return float(limits.get(group, limits.get("default", float("inf"))))

        return float("inf")

    def _matches_when(self, request: dict, when: dict) -> bool:
        for path, expected in when.items():
            node = request
            for key in path.split("."):
                if not isinstance(node, dict):
                    return False
                node = node.get(key, "")
            if str(node) != str(expected):
                return False
        return True

    def _current_period(self) -> str:
        now = datetime.now(timezone.utc)
        reset = self.config.get("reset", "monthly")
        if reset == "daily":
            return now.strftime("%Y-%m-%d")
        if reset == "weekly":
            return now.strftime("%Y-W%W")
        return now.strftime("%Y-%m")

    def _get_spend(self, group: str) -> float:
        with self._lock:
            return self._spend.get(group, {}).get(self._current_period(), 0.0)

    def _add_spend(self, group: str, amount: float):
        period = self._current_period()
        with self._lock:
            if group not in self._spend:
                self._spend[group] = {}
            self._spend[group][period] = self._spend[group].get(period, 0.0) + amount

    # ── public helpers ────────────────────────────────────────────────────

    def get_spend(self, group: str = "__global__") -> float:
        return self._get_spend(group)

    def get_all_spend(self) -> dict:
        period = self._current_period()
        with self._lock:
            return {group: periods.get(period, 0.0) for group, periods in self._spend.items()}

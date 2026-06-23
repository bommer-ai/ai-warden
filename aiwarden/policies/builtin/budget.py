"""
Budget policy — tracks LLM spend and blocks requests when budget is exceeded.

Supports distributed enforcement across pods/processes via Redis.
Set AIWARDEN_REDIS_URL to enable shared budget tracking.
Without Redis, falls back to per-process in-memory tracking.
"""
import logging
import threading
from datetime import datetime, timezone
from typing import Optional

from aiwarden.policies.base import Block, Policy
from aiwarden.policies.builtin._distributed_tracker import DistributedSpendTracker

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
    default_hooks = ["pre", "post"]

    def __init__(self, config: dict = None):
        super().__init__(config)
        reset_period = (config or {}).get("reset", "monthly")
        self._tracker = DistributedSpendTracker(reset_period=reset_period)
        self._lock = threading.Lock()

    def pre(self, request: dict) -> tuple[dict, Optional[Block]]:
        group = self._get_group(request)
        limit = self._get_limit(request, group)
        key = self._budget_key(group)
        allowed, spend = self._tracker.check_budget(key, limit)

        log.debug("[aiwarden] budget check — group=%s spend=%.4f limit=%.2f", group, spend, limit)

        if not allowed:
            return request, Block(
                f"Budget exceeded for '{group}': ${spend:.4f} / ${limit:.2f} "
                f"({self.config.get('reset', 'monthly')})"
            )
        return request, None

    def post(self, request: dict, response: object) -> object:
        try:
            from aiwarden.cost import compute_cost
            model = request.get("model", "")
            usage = getattr(response, "usage", None)
            if usage:
                prompt_tokens = (
                    getattr(usage, "input_tokens", 0)
                    or getattr(usage, "prompt_tokens", 0)
                    or 0
                )
                completion_tokens = (
                    getattr(usage, "output_tokens", 0)
                    or getattr(usage, "completion_tokens", 0)
                    or 0
                )
                cost = compute_cost(model, prompt_tokens, completion_tokens)
                group = self._get_group(request)
                key = self._budget_key(group)
                self._tracker.record_spend(key, cost)
                log.debug("[aiwarden] budget recorded — group=%s cost=%.6f", group, cost)
        except Exception as e:
            log.error("[aiwarden] budget post() error: %s", e)
        return response

    # ── key generation ────────────────────────────────────────────────────

    def _budget_key(self, group: str) -> str:
        period = self._current_period()
        return f"aiwarden:budget:{group}:{period}"

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

    # ── public helpers ────────────────────────────────────────────────────

    def get_spend(self, group: str = "__global__") -> float:
        """Return current spend for a group in the current period."""
        key = self._budget_key(group)
        return self._tracker.get_spend(key)

    def get_all_spend(self) -> dict:
        """Return spend for all groups in the current period."""
        period = self._current_period()
        prefix = f"aiwarden:budget:"
        all_spend = self._tracker.get_all_spend(prefix)
        result = {}
        for k, v in all_spend.items():
            if k.endswith(f":{period}"):
                group = k.removeprefix(prefix).removesuffix(f":{period}")
                result[group] = v
        return result

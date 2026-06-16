import logging
from datetime import datetime, timezone
from typing import Optional

from aiwarden.policies.base import Block, Policy

log = logging.getLogger(__name__)


class BudgetPolicy(Policy):
    """
    Tracks LLM spend and blocks requests when budget is exceeded.

    pre()  — checks accumulated spend before calling LLM. Blocks if over limit.
    post() — records actual cost after LLM responds.

    Spend is tracked in-memory per group (team, user, deployment, etc.).
    Resets automatically when the configured period rolls over.

    Config:
        group_by: metadata.team        # dotted path into request — e.g. metadata.user_id
        limits:
          engineering: 500.00          # per-group limit
          intern: 20.00
          default: 100.00              # fallback for unknown groups
        # OR a flat limit for all:
        # limit: 100.00
        reset: monthly                 # daily | weekly | monthly

    Example with per-dimension limits:
        limits:
          - when:
              metadata.team: intern
              metadata.deployment: prod
            limit: 10.00
          - when:
              metadata.team: engineering
            limit: 1000.00
          - default: 50.00
    """

    name          = "budget-control"
    default_hooks = ["pre", "post"]

    def __init__(self, config: dict = None):
        super().__init__(config)
        self._spend: dict[str, dict[str, float]] = {}   # {group: {period: spend}}

    # ── pre: check before LLM call ────────────────────────────────────────────

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

    # ── post: record actual cost after LLM responds ───────────────────────────

    def post(self, request: dict, response: object) -> object:
        try:
            from aiwarden.cost import compute_cost
            model  = request.get("model", "")
            usage  = getattr(response, "usage", None)
            if usage:
                cost  = compute_cost(
                    model,
                    getattr(usage, "input_tokens",  0) or 0,
                    getattr(usage, "output_tokens", 0) or 0,
                )
                group = self._get_group(request)
                self._add_spend(group, cost)
                log.debug("[aiwarden] budget recorded — group=%s cost=%.6f", group, cost)
        except Exception as e:
            log.error("[aiwarden] budget post() error: %s", e)
        return response

    # ── spend helpers ─────────────────────────────────────────────────────────

    def _get_group(self, request: dict) -> str:
        """Resolve dotted path like 'metadata.team' from request dict."""
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
        # flat limit
        if flat := self.config.get("limit"):
            return float(flat)

        limits = self.config.get("limits", {})

        # list-style with when: conditions
        if isinstance(limits, list):
            for entry in limits:
                when = entry.get("when", {})
                if self._matches_when(request, when):
                    return float(entry.get("limit", float("inf")))
                if "default" in entry:
                    return float(entry["default"])
            return float("inf")

        # dict-style: {group_value: limit, default: limit}
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
        return now.strftime("%Y-%m")   # monthly (default)

    def _get_spend(self, group: str) -> float:
        return self._spend.get(group, {}).get(self._current_period(), 0.0)

    def _add_spend(self, group: str, amount: float):
        period = self._current_period()
        if group not in self._spend:
            self._spend[group] = {}
        self._spend[group][period] = self._spend[group].get(period, 0.0) + amount

    # ── public helpers ────────────────────────────────────────────────────────

    def get_spend(self, group: str = "__global__") -> float:
        """Query current spend for a group — useful for dashboards/debugging."""
        return self._get_spend(group)

    def get_all_spend(self) -> dict:
        """Return all tracked spend for the current period."""
        period = self._current_period()
        return {group: periods.get(period, 0.0) for group, periods in self._spend.items()}

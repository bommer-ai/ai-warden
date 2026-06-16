import logging
from typing import Optional

from aiwarden.policies.base import Block, Policy

log = logging.getLogger(__name__)


class PolicyEngine:
    """
    Runs all enabled policies in order.

    pre()  — called before every LLM request.
    post() — called after every LLM response, before agent sees it.

    Policies are loaded lazily on first use so AIWARDEN_POLICY_FILE is
    resolved after the process environment is fully initialised.
    """

    def __init__(self):
        self._policies: list[Policy] | None = None

    def run_pre(self, request: dict) -> tuple[dict, Optional[Block]]:
        for policy in self._get_policies():
            if "pre" not in policy.hooks:
                continue
            try:
                request, block = policy.pre(request)
                if block:
                    log.info("[aiwarden] policy '%s' blocked request: %s", policy.name, block.reason)
                    return request, block
            except Exception as e:
                log.error("[aiwarden] policy '%s' pre() error: %s", policy.name, e)
        return request, None

    def run_post(self, request: dict, response: object) -> object:
        for policy in self._get_policies():
            if "post" not in policy.hooks:
                continue
            try:
                response = policy.post(request, response)
            except Exception as e:
                log.error("[aiwarden] policy '%s' post() error: %s", policy.name, e)
        return response

    def register(self, policy: Policy) -> "PolicyEngine":
        """Programmatically add a policy — useful for custom policies in agent code."""
        if self._policies is None:
            self._policies = []
        self._policies.append(policy)
        return self

    def _get_policies(self) -> list[Policy]:
        if self._policies is None:
            from aiwarden.policies.loader import load_policies
            self._policies = load_policies()
        return self._policies

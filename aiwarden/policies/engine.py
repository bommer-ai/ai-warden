import logging
import threading
from typing import Optional

from aiwarden import config
from aiwarden.event import PolicyResult
from aiwarden.policies.base import Block, Policy, Warn

log = logging.getLogger(__name__)


def _resolve_agent(request: dict) -> str:
    """
    Resolve the agent name for this request.
    Priority:
      1. _agent in kwargs (per-call override)
      2. aiwarden.agent() context manager (scoped block)
      3. AIWARDEN_AGENT_NAME env var / configure() (process-wide)
    """
    if agent_kwarg := request.get("_agent", ""):
        return agent_kwarg
    from aiwarden import get_agent
    if agent_ctx := get_agent():
        return agent_ctx
    return config.AGENT_NAME


class PolicyEngine:
    """
    Runs all enabled policies in priority order (lower priority = runs first).

    pre()  — called before every LLM request. Short-circuits on Block.
    post() — called after every LLM response. All post-hooks always run.

    Tracks which policies fired (warn or block) for the event log.
    """

    def __init__(self):
        self._policies: list[Policy] | None = None
        self._load_lock = threading.Lock()

    def run_pre(self, request: dict) -> tuple[dict, Optional[Block], list[PolicyResult]]:
        """
        Run pre-hooks in priority order.
        Returns (modified_request, block_or_none, list_of_fired_policies).
        Short-circuits on Block — remaining policies don't run.
        """
        fired: list[PolicyResult] = []
        current_agent = _resolve_agent(request)

        for policy in self._get_policies():
            if "pre" not in policy.hooks:
                continue
            if policy.agents and current_agent not in policy.agents:
                continue
            try:
                request, result = policy.pre(request)
                if isinstance(result, Block):
                    fired.append(PolicyResult(
                        name=policy.name, action="block",
                        message=result.reason, hook="pre",
                    ))
                    log.info("[aiwarden] policy '%s' blocked: %s", policy.name, result.reason)
                    return request, result, fired
                elif isinstance(result, Warn):
                    fired.append(PolicyResult(
                        name=policy.name, action="warn",
                        message=result.reason, hook="pre",
                    ))
                    log.info("[aiwarden] policy '%s' warned: %s", policy.name, result.reason)
            except Exception as e:
                log.error("[aiwarden] policy '%s' pre() error: %s", policy.name, e)

        return request, None, fired

    def run_post(self, request: dict, response: object) -> tuple[object, list[PolicyResult]]:
        """
        Run post-hooks in priority order.
        Returns (modified_response, list_of_fired_policies).
        """
        fired: list[PolicyResult] = []
        current_agent = _resolve_agent(request)

        for policy in self._get_policies():
            if "post" not in policy.hooks:
                continue
            if policy.agents and current_agent not in policy.agents:
                continue
            try:
                result = policy.post(request, response)
                if isinstance(result, tuple) and len(result) == 2:
                    response, warn = result
                    if isinstance(warn, Warn):
                        fired.append(PolicyResult(
                            name=policy.name, action="warn",
                            message=warn.reason, hook="post",
                        ))
                        log.info("[aiwarden] policy '%s' post warned: %s", policy.name, warn.reason)
                else:
                    response = result
            except Exception as e:
                log.error("[aiwarden] policy '%s' post() error: %s", policy.name, e)

        return response, fired

    def register(self, policy: Policy, first: bool = False) -> "PolicyEngine":
        """Programmatically add a policy."""
        if self._policies is None:
            self._policies = []
        if first:
            self._policies.insert(0, policy)
        else:
            self._policies.append(policy)
        self._policies.sort(key=lambda p: p.priority)
        return self

    def _get_policies(self) -> list[Policy]:
        if self._policies is None:
            with self._load_lock:
                if self._policies is None:
                    try:
                        from aiwarden.policies.loader import load_policies
                        policies = load_policies()
                        policies.sort(key=lambda p: p.priority)
                        self._policies = policies
                    except Exception as e:
                        log.warning(
                            "[aiwarden] failed to load policies — running unprotected: %s", e
                        )
                        self._policies = []
        return self._policies

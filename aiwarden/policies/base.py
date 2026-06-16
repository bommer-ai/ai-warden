from abc import ABC
from dataclasses import dataclass
from typing import Optional


@dataclass
class Block:
    """Returned by Policy.pre() to stop the request from reaching the LLM."""
    reason: str


class PolicyViolationError(Exception):
    """Raised when a policy uses action=interrupt on a tool_use block."""
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class Policy(ABC):
    """
    Base class for all policies — built-in and custom.

    Each policy declares which hooks it runs on (pre, post, or both).
    Implement only the hooks you need — defaults are passthrough.

    pre()  — runs BEFORE the LLM call.
               Can modify the request or block it entirely (return Block).
               Use for: budget checks, rate limiting, input filtering.

    post() — runs AFTER the LLM responds, BEFORE agent sees the response.
               Can modify or replace the response.
               Use for: tool blocking, output filtering, cost tracking.

    Example:
        class MyPolicy(Policy):
            name         = "my-policy"
            default_hooks = ["pre"]

            def pre(self, request):
                if should_block(request):
                    return request, Block("not allowed")
                return request, None
    """

    name: str          = ""
    default_hooks: list = []   # override in subclass: ["pre"], ["post"], ["pre", "post"]

    def __init__(self, config: dict = None):
        self.config = config or {}
        # YAML can override default hooks per instance
        self.hooks: list[str] = self.config.get("hooks", self.default_hooks)

    def pre(self, request: dict) -> tuple[dict, Optional[Block]]:
        return request, None

    def post(self, request: dict, response: object) -> object:
        return response

from abc import ABC
from dataclasses import dataclass
from typing import Optional


@dataclass
class Block:
    """Returned by Policy.pre() to stop the request from reaching the LLM."""
    reason: str


@dataclass
class Warn:
    """Returned by policies to log a warning without blocking."""
    reason: str


class PolicyViolationError(Exception):
    """Raised when a policy blocks a request or tool call."""
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class Policy(ABC):
    """
    Base class for all policies — built-in and custom.

    Priority: lower value = runs first (cheap blockers before expensive modifiers).
        10: rate limit, budget checks
        50: agent control
        90: PII redaction (expensive, modifies request)
        100: default

    pre()  — runs BEFORE the LLM call.
             Return (request, Block(...)) to block.
             Return (request, Warn(...)) to warn without blocking.
             Return (request, None) to pass.

    post() — runs AFTER the LLM responds.
             Return (response, Warn(...)) to warn.
             Return (response, None) to pass.
             Or return just response (backwards-compatible but deprecated).
    """

    name: str = ""
    priority: int = 100
    default_hooks: list = []

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.hooks: list[str] = self.config.get("hooks", self.default_hooks)
        if "priority" in self.config:
            self.priority = int(self.config["priority"])
        self.agents: list[str] = self.config.get("agents", [])

    def pre(self, request: dict) -> tuple[dict, Optional["Block | Warn"]]:
        return request, None

    def post(self, request: dict, response: object) -> object:
        return response

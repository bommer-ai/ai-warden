from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class Block:
    """Returned by a PreProcessor to stop the request from reaching the LLM."""
    reason: str


class PolicyViolationError(Exception):
    """Raised in the patcher when a PreProcessor blocks a request."""
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class PreProcessor(ABC):
    """
    Runs BEFORE the LLM API call, inside the patched create().
    Can modify the request or block it entirely.

    Example uses:
      - Inject memory into system prompt
      - Redact PII from input messages
      - Block if org is over budget
      - Add policy constraints
    """
    @abstractmethod
    def process(self, request: dict) -> tuple[dict, Optional[Block]]:
        """
        request  — full kwargs passed to Messages.create / completions.create
                   (messages, model, system, tools, metadata, ...)

        Return (modified_request, None)    to continue
        Return (request,          Block)   to stop — raises PolicyViolationError
        """
        ...


class PostProcessor(ABC):
    """
    Runs AFTER the LLM API call, before the response is returned to the agent.
    Can modify or replace the response the agent sees.

    Example uses:
      - Strip PII from the response
      - Apply guardrails / content filtering
      - Annotate or transform the response
    """
    @abstractmethod
    def process(self, request: dict, response: object) -> object:
        """
        request  — kwargs that were sent (after pre-processing)
        response — SDK response object

        Return (possibly modified) response — agent receives whatever you return.
        """
        ...

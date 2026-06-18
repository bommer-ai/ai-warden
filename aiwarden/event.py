"""
Common event and protocol types for ai-warden.

NormalizedRequest / NormalizedResponse: provider-agnostic types that policies operate on.
LLMEvent: canonical event schema emitted by all patchers.
PolicyResult: a policy that fired during a request.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


# ── Normalized protocol types (policies operate on these) ────────────────────

@dataclass
class NormalizedRequest:
    """Provider-agnostic view of what's being sent to the LLM."""
    provider: str                               # "anthropic" | "openai" | "gemini"
    model: str
    messages: list                              # common dict format [{role, content}]
    system: str = ""
    tools: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    custom_fields: dict = field(default_factory=dict)  # user's _ prefixed fields
    raw: dict = field(default_factory=dict)     # original kwargs — preserved for patcher
    pii_found: list = field(default_factory=list)  # populated by PIIPolicy


@dataclass
class NormalizedResponse:
    """Provider-agnostic view of what came back from the LLM."""
    provider: str
    model: str = ""
    text_content: str = ""
    tool_calls: list = field(default_factory=list)   # [{name, arguments, id}]
    finish_reason: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw: object = None                          # original SDK response object


# ── Policy result ────────────────────────────────────────────────────────────

@dataclass
class PolicyResult:
    """A single policy that fired during this request."""
    name: str
    action: str              # "block" | "warn" | "refusal" | "interrupt"
    message: str
    hook: str = "pre"        # "pre" or "post"


# ── Event schema ─────────────────────────────────────────────────────────────

@dataclass
class LLMEvent:
    """Canonical event emitted by all patchers."""

    # Identity
    id: str = field(default_factory=lambda: uuid4().hex)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    provider: str = ""
    type: str = "chat"

    # Run tracking
    run_id: str = ""
    turn: int = 0
    model: str = ""

    # Request
    request_messages: list = field(default_factory=list)
    system: str = ""

    # Response
    response_content: str = ""
    tool_calls: list = field(default_factory=list)
    finish_reason: str = ""
    streamed: bool = False

    # Usage
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0
    latency_ms: int = 0

    # Policies
    policy_fired: bool = False
    policy_blocked: bool = False
    policies: list = field(default_factory=list)

    # PII
    pii_redacted: bool = False
    pii_types_found: list = field(default_factory=list)

    # Context
    tags: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    custom_fields: dict = field(default_factory=dict)

    # Caller
    caller_file: str = ""
    caller_line: int = 0
    caller_function: str = ""

    def to_dict(self) -> dict:
        """Serialize to dict for JSON output."""
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "provider": self.provider,
            "type": self.type,
            "run_id": self.run_id,
            "turn": self.turn,
            "model": self.model,
            "request_messages": self.request_messages,
            "system": self.system,
            "response_content": self.response_content,
            "tool_calls": self.tool_calls,
            "finish_reason": self.finish_reason,
            "streamed": self.streamed,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cost": self.cost,
            "latency_ms": self.latency_ms,
            "policy_fired": self.policy_fired,
            "policy_blocked": self.policy_blocked,
            "policies": [
                {"name": p.name, "action": p.action, "message": p.message, "hook": p.hook}
                if isinstance(p, PolicyResult) else p
                for p in self.policies
            ],
            "pii_redacted": self.pii_redacted,
            "pii_types_found": self.pii_types_found,
            "tags": self.tags,
            "metadata": self.metadata,
            "custom_fields": self.custom_fields,
            "caller_file": self.caller_file,
            "caller_line": self.caller_line,
            "caller_function": self.caller_function,
        }

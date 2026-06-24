"""
Shared test fixtures for ai-warden test suite.

Provides:
- Response factories (Anthropic/OpenAI, text/tool/streaming)
- Policy engine fixture with automatic state restoration
- Config fixture that restores ENABLED/CALLER_TRACKING after test
- Common request builders
"""
import pytest
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch

from aiwarden import config
from aiwarden.policies import engine as engine_mod
from aiwarden.policies.engine import PolicyEngine


# ═══════════════════════════════════════════════════════════════════════════════
#  FIXTURES — Policy Engine State Isolation
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _restore_engine_state():
    """Automatically restore engine singleton policies after every test."""
    original = engine_mod._policies
    yield
    engine_mod._policies = original


@pytest.fixture(autouse=True)
def _restore_config():
    """Automatically restore config after every test."""
    original_enabled = config.ENABLED
    original_tracking = config.CALLER_TRACKING
    original_debug = config.DEBUG
    yield
    config.ENABLED = original_enabled
    config.CALLER_TRACKING = original_tracking
    config.DEBUG = original_debug


@pytest.fixture
def fresh_engine():
    """Provide a fresh PolicyEngine instance (not the singleton)."""
    return PolicyEngine()


@pytest.fixture
def engine_with_policies():
    """Factory fixture: returns a function to set policies on the singleton."""
    def _set(policies):
        engine_mod._policies = sorted(policies, key=lambda p: p.priority)
    return _set


# ═══════════════════════════════════════════════════════════════════════════════
#  FACTORIES — Anthropic Responses
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def anthropic_response():
    """Factory for Anthropic-style response objects."""
    def _make(text="OK", input_tokens=100, output_tokens=50,
              stop_reason="end_turn", tool_calls=None):
        content = []
        if tool_calls:
            for tc in tool_calls:
                content.append(SimpleNamespace(
                    type="tool_use",
                    id=f"toolu_{uuid4().hex[:24]}",
                    name=tc["name"],
                    input=tc.get("input", {}),
                ))
        else:
            content.append(SimpleNamespace(type="text", text=text))
        return SimpleNamespace(
            id=f"msg_{uuid4().hex[:24]}",
            model="claude-sonnet-4-6",
            role="assistant",
            type="message",
            stop_reason=stop_reason,
            content=content,
            usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
        )
    return _make


@pytest.fixture
def openai_response():
    """Factory for OpenAI-style response objects."""
    def _make(content="Hello", model="gpt-4o",
              prompt_tokens=10, completion_tokens=5,
              finish_reason="stop", tool_calls=None):
        msg = SimpleNamespace(content=content, tool_calls=tool_calls)
        choice = SimpleNamespace(message=msg, finish_reason=finish_reason)
        usage = SimpleNamespace(prompt_tokens=prompt_tokens,
                                completion_tokens=completion_tokens)
        return SimpleNamespace(choices=[choice], usage=usage, model=model)
    return _make


# ═══════════════════════════════════════════════════════════════════════════════
#  FACTORIES — Requests
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def make_request():
    """Factory for LLM request dicts."""
    def _make(content="Hello, help me.", model="claude-sonnet-4-6",
              num_messages=1, metadata=None):
        messages = []
        for i in range(num_messages):
            role = "user" if i % 2 == 0 else "assistant"
            messages.append({"role": role, "content": f"{content} (msg {i})"})
        req = {"model": model, "max_tokens": 1024, "messages": messages}
        if metadata:
            req["metadata"] = metadata
        return req
    return _make


@pytest.fixture
def pii_request():
    """Factory for requests containing PII."""
    def _make(content=None):
        if content is None:
            content = (
                "Contact john.doe@example.com or call 555-123-4567. "
                "SSN: 123-45-6789. API key: sk-abcdefghijklmnopqrstuvwxyz."
            )
        return {"model": "claude-sonnet-4-6", "max_tokens": 1024,
                "messages": [{"role": "user", "content": content}]}
    return _make


# ═══════════════════════════════════════════════════════════════════════════════
#  FACTORIES — Policies
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def block_policy():
    """A custom policy that blocks requests matching a model pattern."""
    from aiwarden.policies.custom.policy import CustomPolicy

    def _make(model_pattern="gpt-4", message="blocked"):
        return CustomPolicy({"name": "test-blocker", "rules": [
            {"name": "block-rule", "hook": "pre", "action": "block",
             "match": {"model": {"startswith": model_pattern}}, "message": message}
        ]})
    return _make


@pytest.fixture
def warn_policy():
    """A custom policy that warns on requests matching a model pattern."""
    from aiwarden.policies.custom.policy import CustomPolicy

    def _make(model_pattern="gpt-4", message="warned"):
        return CustomPolicy({"name": "test-warner", "rules": [
            {"name": "warn-rule", "hook": "pre", "action": "warn",
             "match": {"model": {"contains": model_pattern}}, "message": message}
        ]})
    return _make

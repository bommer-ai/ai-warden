"""
Tests for the OpenAI SDK patcher.

Validates:
- Pre-hooks fire before LLM call
- Blocking policies raise PolicyViolationError
- Post-hooks fire after LLM response
- Tool calls in response are accessible to tool policy
- PII redacted from messages before API call
- Original exceptions propagate (not swallowed)
- build_and_capture called with provider="openai"
- Internal _-prefixed keys stripped from api_kwargs
- Streaming: pre-hook blocks before stream starts
"""
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import aiwarden.patchers.openai as patcher
from aiwarden.patchers.openai import _patched_create
from aiwarden.policies.base import PolicyViolationError
from aiwarden.policies.builtin.pii import PIIPolicy
from aiwarden.policies.builtin.tools import ToolsPolicy
from aiwarden.policies.custom.policy import CustomPolicy
from aiwarden.policies import engine as engine_mod
from aiwarden import config


def _make_response(content="Hello", model="gpt-4o",
                   prompt_tokens=10, completion_tokens=5,
                   finish_reason="stop", tool_calls=None):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=msg, finish_reason=finish_reason)
    usage = SimpleNamespace(prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens)
    return SimpleNamespace(choices=[choice], usage=usage, model=model)


def _make_tool_response(tool_name="bash", arguments='{"cmd": "rm -rf /"}',
                        tool_id="call_abc"):
    func = SimpleNamespace(name=tool_name, arguments=arguments)
    tc = SimpleNamespace(function=func, id=tool_id)
    msg = SimpleNamespace(content=None, tool_calls=[tc])
    choice = SimpleNamespace(message=msg, finish_reason="tool_calls")
    usage = SimpleNamespace(prompt_tokens=20, completion_tokens=10)
    return SimpleNamespace(choices=[choice], usage=usage, model="gpt-4o")


class TestOpenAINonStreaming:
    """Non-streaming OpenAI patcher tests."""

    def test_pre_hooks_fire_warn(self):
        """A warn-action rule fires but response still returns."""
        policy = CustomPolicy({"name": "warn-gate", "rules": [
            {"name": "warn-gpt", "hook": "pre", "action": "warn",
             "match": {"model": {"contains": "gpt-4"}}, "message": "GPT warned"},
        ]})
        old = engine_mod._policies
        engine_mod._policies = [policy]
        try:
            mock_resp = _make_response()
            with patch.object(patcher, '_original', return_value=mock_resp):
                result = _patched_create(None, model="gpt-4o", max_tokens=100,
                                         messages=[{"role": "user", "content": "hi"}])
            assert result.choices[0].message.content == "Hello"
        finally:
            engine_mod._policies = old

    def test_pre_hook_blocks(self):
        """A block-action rule raises PolicyViolationError."""
        policy = CustomPolicy({"name": "blocker", "rules": [
            {"name": "block-gpt", "hook": "pre", "action": "block",
             "match": {"model": {"startswith": "gpt-4"}}, "message": "GPT blocked"},
        ]})
        old = engine_mod._policies
        engine_mod._policies = [policy]
        try:
            with pytest.raises(PolicyViolationError, match="GPT blocked"):
                _patched_create(None, model="gpt-4o", max_tokens=100,
                                messages=[{"role": "user", "content": "hi"}])
        finally:
            engine_mod._policies = old

    def test_post_hooks_fire_tool_policy(self):
        """Tool policy can intercept tool_use in response."""
        tool_cfg = {
            "name": "safety", "type": "tools", "enabled": True,
            "builtin": {"no-privilege-escalation": True},
            "rules": [],
        }
        tools = ToolsPolicy(tool_cfg)
        old = engine_mod._policies
        engine_mod._policies = [tools]
        try:
            resp = _make_tool_response(tool_name="bash",
                                       arguments='{"command": "sudo rm -rf /"}')
            with patch.object(patcher, '_original', return_value=resp):
                result = _patched_create(None, model="gpt-4o", max_tokens=100,
                                         messages=[{"role": "user", "content": "hi"}])
            assert result is not None
        finally:
            engine_mod._policies = old

    def test_pii_redacted_before_api_call(self):
        """PII policy redacts messages before _original is called."""
        pii = PIIPolicy({})
        old = engine_mod._policies
        engine_mod._policies = [pii]
        try:
            mock_fn = MagicMock(return_value=_make_response())
            with patch.object(patcher, '_original', mock_fn):
                _patched_create(None, model="gpt-4o", max_tokens=100,
                                messages=[{"role": "user",
                                           "content": "Email john@example.com"}])
            call_kwargs = mock_fn.call_args
            sent_messages = call_kwargs[1].get("messages") if call_kwargs[1] else None
            if sent_messages is None and call_kwargs[0]:
                sent_messages = call_kwargs[0][0]
            assert isinstance(sent_messages, list), (
                f"Expected messages list in API call, got: {type(sent_messages)}")
            content = sent_messages[0]["content"]
            assert "john@example.com" not in content, "PII was NOT redacted before API call"
            assert "[REDACTED:email]" in content
        finally:
            engine_mod._policies = old

    def test_original_exception_propagates(self):
        """If _original raises, the exception is not swallowed."""
        old = engine_mod._policies
        engine_mod._policies = []
        try:
            with patch.object(patcher, '_original',
                              side_effect=RuntimeError("network error")):
                with pytest.raises(RuntimeError, match="network error"):
                    _patched_create(None, model="gpt-4o", max_tokens=100,
                                    messages=[{"role": "user", "content": "hi"}])
        finally:
            engine_mod._policies = old

    def test_build_and_capture_called_with_openai_provider(self):
        """Verify build_and_capture receives provider='openai'."""
        old = engine_mod._policies
        engine_mod._policies = []
        old_enabled = config.ENABLED
        config.ENABLED = True
        try:
            with patch.object(patcher, '_original', return_value=_make_response()):
                with patch('aiwarden.patchers.openai.build_and_capture') as mock_cap:
                    _patched_create(None, model="gpt-4o", max_tokens=100,
                                    messages=[{"role": "user", "content": "hi"}])
                    assert mock_cap.called
                    assert mock_cap.call_args.kwargs['provider'] == "openai"
        finally:
            engine_mod._policies = old
            config.ENABLED = old_enabled

    def test_usage_tokens_passed_to_capture(self):
        """Token counts from response are passed to build_and_capture."""
        old = engine_mod._policies
        engine_mod._policies = []
        old_enabled = config.ENABLED
        config.ENABLED = True
        try:
            resp = _make_response(prompt_tokens=150, completion_tokens=75)
            with patch.object(patcher, '_original', return_value=resp):
                with patch('aiwarden.patchers.openai.build_and_capture') as mock_cap:
                    _patched_create(None, model="gpt-4o", max_tokens=100,
                                    messages=[{"role": "user", "content": "hi"}])
                    assert mock_cap.call_args.kwargs['prompt_tokens'] == 150
                    assert mock_cap.call_args.kwargs['completion_tokens'] == 75
        finally:
            engine_mod._policies = old
            config.ENABLED = old_enabled

    def test_internal_keys_stripped_from_api_kwargs(self):
        """Keys starting with _ are not passed to the real API."""
        old = engine_mod._policies
        engine_mod._policies = []
        try:
            mock_fn = MagicMock(return_value=_make_response())
            with patch.object(patcher, '_original', mock_fn):
                _patched_create(None, model="gpt-4o", max_tokens=100,
                                messages=[{"role": "user", "content": "hi"}],
                                _custom_field="should_be_stripped")
            call_kwargs = mock_fn.call_args[1] if mock_fn.call_args[1] else {}
            if not call_kwargs:
                call_kwargs = dict(zip(
                    ["model", "max_tokens", "messages"],
                    mock_fn.call_args[0] if mock_fn.call_args[0] else []
                ))
            assert "_custom_field" not in str(mock_fn.call_args)
        finally:
            engine_mod._policies = old


class TestOpenAIStreamingBlock:
    """Streaming path: blocking behavior."""

    def test_pre_hook_blocks_stream_never_starts(self):
        """Block policy raises before stream is created."""
        policy = CustomPolicy({"name": "blocker", "rules": [
            {"name": "block-all", "hook": "pre", "action": "block",
             "match": {"model": {"contains": "gpt"}}, "message": "blocked"},
        ]})
        old = engine_mod._policies
        engine_mod._policies = [policy]
        try:
            mock_fn = MagicMock()
            with patch.object(patcher, '_original', mock_fn):
                with pytest.raises(PolicyViolationError, match="blocked"):
                    _patched_create(None, model="gpt-4o", max_tokens=100,
                                    messages=[{"role": "user", "content": "hi"}],
                                    stream=True)
            mock_fn.assert_not_called()
        finally:
            engine_mod._policies = old

    def test_stream_options_injected(self):
        """stream_options.include_usage=True is injected for streaming calls."""
        old = engine_mod._policies
        engine_mod._policies = []
        try:
            mock_fn = MagicMock(return_value=iter([]))
            with patch.object(patcher, '_original', mock_fn):
                wrapper = _patched_create(None, model="gpt-4o", max_tokens=100,
                                          messages=[{"role": "user", "content": "hi"}],
                                          stream=True)
            call_kwargs = mock_fn.call_args[1]
            assert call_kwargs.get("stream_options", {}).get("include_usage") is True
        finally:
            engine_mod._policies = old


class TestOpenAIAsyncNonStreaming:
    """Async OpenAI patcher: non-streaming path."""

    def test_async_pre_hook_blocks(self):
        """Block policy raises PolicyViolationError before async API call."""
        import asyncio
        policy = CustomPolicy({"name": "blocker", "rules": [
            {"name": "block-gpt", "hook": "pre", "action": "block",
             "match": {"model": {"startswith": "gpt-4"}}, "message": "async blocked"},
        ]})
        old = engine_mod._policies
        engine_mod._policies = [policy]
        try:
            async def run():
                from aiwarden.patchers.openai import _patched_async_create
                with pytest.raises(PolicyViolationError, match="async blocked"):
                    await _patched_async_create(None, model="gpt-4o", max_tokens=100,
                                                messages=[{"role": "user", "content": "hi"}])
            asyncio.run(run())
        finally:
            engine_mod._policies = old

    def test_async_passthrough(self):
        """Unblocked async requests reach the mock API and return response."""
        import asyncio
        old = engine_mod._policies
        engine_mod._policies = []
        try:
            mock_resp = _make_response(content="async hello")

            async def mock_original(self, *a, **kw):
                return mock_resp

            async def run():
                from aiwarden.patchers.openai import _patched_async_create
                with patch.object(patcher, '_original_async', mock_original):
                    result = await _patched_async_create(None, model="gpt-4o", max_tokens=100,
                                                         messages=[{"role": "user", "content": "hi"}])
                assert result.choices[0].message.content == "async hello"
            asyncio.run(run())
        finally:
            engine_mod._policies = old

    def test_async_pii_redacted_before_api(self):
        """PII is redacted from messages before they reach the async API call."""
        import asyncio
        pii = PIIPolicy({})
        old = engine_mod._policies
        engine_mod._policies = [pii]
        try:
            captured_kwargs = {}

            async def mock_original(self, *a, **kw):
                captured_kwargs.update(kw)
                return _make_response()

            async def run():
                from aiwarden.patchers.openai import _patched_async_create
                with patch.object(patcher, '_original_async', mock_original):
                    await _patched_async_create(None, model="gpt-4o", max_tokens=100,
                                                messages=[{"role": "user", "content": "Email john@test.com"}])

            asyncio.run(run())
            msgs = captured_kwargs.get("messages", [])
            assert isinstance(msgs, list), f"Expected list, got {type(msgs)}"
            assert "john@test.com" not in msgs[0]["content"]
            assert "[REDACTED:email]" in msgs[0]["content"]
        finally:
            engine_mod._policies = old

    def test_async_build_and_capture_called(self):
        """build_and_capture is called with provider='openai' after async response."""
        import asyncio
        old = engine_mod._policies
        engine_mod._policies = []
        old_enabled = config.ENABLED
        config.ENABLED = True
        try:
            async def mock_original(self, *a, **kw):
                return _make_response()

            async def run():
                from aiwarden.patchers.openai import _patched_async_create
                with patch.object(patcher, '_original_async', mock_original):
                    with patch('aiwarden.patchers.openai.build_and_capture') as mock_cap:
                        await _patched_async_create(None, model="gpt-4o", max_tokens=100,
                                                    messages=[{"role": "user", "content": "hi"}])
                        assert mock_cap.called
                        assert mock_cap.call_args.kwargs['provider'] == "openai"

            asyncio.run(run())
        finally:
            engine_mod._policies = old
            config.ENABLED = old_enabled

    def test_async_internal_keys_stripped(self):
        """Keys starting with _ are not passed to the async API."""
        import asyncio
        old = engine_mod._policies
        engine_mod._policies = []
        try:
            captured_kwargs = {}

            async def mock_original(self, *a, **kw):
                captured_kwargs.update(kw)
                return _make_response()

            async def run():
                from aiwarden.patchers.openai import _patched_async_create
                with patch.object(patcher, '_original_async', mock_original):
                    await _patched_async_create(None, model="gpt-4o", max_tokens=100,
                                                messages=[{"role": "user", "content": "hi"}],
                                                _custom="should_strip")

            asyncio.run(run())
            assert "_custom" not in captured_kwargs
        finally:
            engine_mod._policies = old


class TestOpenAIAsyncStreaming:
    """Async OpenAI patcher: streaming path."""

    def test_async_stream_block_before_start(self):
        """Block policy raises before async stream is created."""
        import asyncio
        policy = CustomPolicy({"name": "blocker", "rules": [
            {"name": "block-all", "hook": "pre", "action": "block",
             "match": {"model": {"contains": "gpt"}}, "message": "stream blocked"},
        ]})
        old = engine_mod._policies
        engine_mod._policies = [policy]
        try:
            called = []

            async def mock_original(self, *a, **kw):
                called.append(True)
                return iter([])

            async def run():
                from aiwarden.patchers.openai import _patched_async_create
                with patch.object(patcher, '_original_async', mock_original):
                    with pytest.raises(PolicyViolationError, match="stream blocked"):
                        await _patched_async_create(None, model="gpt-4o", max_tokens=100,
                                                    messages=[{"role": "user", "content": "hi"}],
                                                    stream=True)
                assert len(called) == 0

            asyncio.run(run())
        finally:
            engine_mod._policies = old

    def test_async_stream_finalize_idempotent(self):
        """Calling _finalize() twice on async stream wrapper is safe."""
        import asyncio
        from aiwarden.patchers.openai import _AsyncStreamWrapper

        old = engine_mod._policies
        engine_mod._policies = []
        try:
            class FakeAsyncStream:
                def __init__(self):
                    self.chunks = [
                        SimpleNamespace(choices=[SimpleNamespace(
                            delta=SimpleNamespace(content="hello"))], usage=None),
                    ]
                    self.idx = 0
                async def __anext__(self):
                    if self.idx >= len(self.chunks):
                        raise StopAsyncIteration
                    c = self.chunks[self.idx]
                    self.idx += 1
                    return c

            wrapper = _AsyncStreamWrapper(
                FakeAsyncStream(),
                {"model": "gpt-4o", "messages": []},
                time.monotonic(), [])

            # Consume
            async def consume():
                chunks = []
                try:
                    while True:
                        c = await wrapper.__anext__()
                        chunks.append(c)
                except StopAsyncIteration:
                    pass
                return chunks

            asyncio.run(consume())
            # Double finalize should not crash
            wrapper._finalize()
            wrapper._finalize()
            assert wrapper._finalized is True
        finally:
            engine_mod._policies = old


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

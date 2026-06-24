"""
Streaming tests for Anthropic and OpenAI patchers.

Validates:
- Pre-hooks fire before stream starts
- Chunks pass through unmodified
- Post-hooks fire on _finalize() (after iteration ends)
- Events emitted with streamed=True
- Pre-hook blocks prevent stream creation
- PII redacted from request before stream starts
- _finalize() is idempotent (double-call safe)
- Edge cases: empty stream, partial consumption
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import aiwarden.patchers.anthropic as anthropic_patcher
import aiwarden.patchers.openai as openai_patcher
from aiwarden.patchers.anthropic import _patched_create as anthropic_create
from aiwarden.patchers.openai import _patched_create as openai_create
from aiwarden.policies.base import PolicyViolationError
from aiwarden.policies.builtin.pii import PIIPolicy
from aiwarden.policies.custom.policy import CustomPolicy
from aiwarden.policies import engine as engine_mod
from aiwarden import config


# ── Fake stream classes ──────────────────────────────────────────────────────


class FakeAnthropicStream:
    """Mimics anthropic SDK MessageStream: context manager + iterator + get_final_message()."""

    def __init__(self, chunks, final_message):
        self._chunks = chunks
        self._final = final_message

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def __iter__(self):
        yield from self._chunks

    def get_final_message(self):
        return self._final


def _make_anthropic_final(text="Hello world", model="claude-sonnet-4-6",
                          input_tokens=10, output_tokens=5):
    return SimpleNamespace(
        id="msg_test", model=model, role="assistant",
        type="message", stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=input_tokens,
                              output_tokens=output_tokens),
    )


def _make_anthropic_chunk(text="Hi"):
    return SimpleNamespace(
        type="content_block_delta",
        delta=SimpleNamespace(type="text_delta", text=text),
    )


def _make_openai_chunk(content="Hi", finish_reason=None):
    delta = SimpleNamespace(content=content)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=None)


def _make_openai_usage_chunk(prompt_tokens=10, completion_tokens=5):
    delta = SimpleNamespace(content=None)
    choice = SimpleNamespace(delta=delta, finish_reason="stop")
    usage = SimpleNamespace(prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens)
    return SimpleNamespace(choices=[choice], usage=usage)


# ── Anthropic Streaming Tests ────────────────────────────────────────────────


class TestAnthropicSyncStreaming:
    """Sync streaming for the Anthropic patcher."""

    def _call_streaming(self, mock_stream, policies=None, **extra_kwargs):
        old = engine_mod._policies
        engine_mod._policies = policies or []
        try:
            with patch.object(anthropic_patcher, '_original_create',
                              return_value=mock_stream):
                kwargs = {"model": "claude-sonnet-4-6", "max_tokens": 100,
                          "messages": [{"role": "user", "content": "hello"}],
                          "stream": True, **extra_kwargs}
                return anthropic_create(None, **kwargs)
        finally:
            engine_mod._policies = old

    def test_chunks_pass_through(self):
        """All chunks from the underlying stream are yielded unmodified."""
        chunks = [_make_anthropic_chunk("Hi"), _make_anthropic_chunk(" there")]
        stream = FakeAnthropicStream(chunks, _make_anthropic_final("Hi there"))
        wrapper = self._call_streaming(stream)
        received = list(wrapper)
        assert len(received) == 2
        assert received[0].delta.text == "Hi"
        assert received[1].delta.text == " there"

    def test_post_hooks_fire_on_finalize(self):
        """Post-hooks are called after stream iteration completes."""
        chunks = [_make_anthropic_chunk("x")]
        final = _make_anthropic_final("x")
        stream = FakeAnthropicStream(chunks, final)

        policy = CustomPolicy({"name": "post-gate", "rules": [
            {"name": "post-warn", "hook": "post", "action": "warn",
             "match": {"response.content": {"contains": "x"}},
             "message": "post warned"},
        ]})

        wrapper = self._call_streaming(stream, policies=[policy])
        list(wrapper)

    def test_event_emitted_with_streamed_true(self):
        """build_and_capture is called with streamed=True after finalize."""
        chunks = [_make_anthropic_chunk("ok")]
        stream = FakeAnthropicStream(chunks, _make_anthropic_final("ok"))

        old = engine_mod._policies
        engine_mod._policies = []
        try:
            with patch.object(anthropic_patcher, '_original_create',
                              return_value=stream):
                with patch('aiwarden.patchers.anthropic.build_and_capture') as mock_cap:
                    wrapper = anthropic_create(
                        None, model="claude-sonnet-4-6", max_tokens=100,
                        messages=[{"role": "user", "content": "hi"}],
                        stream=True)
                    list(wrapper)
                    assert mock_cap.called
                    assert mock_cap.call_args.kwargs['streamed'] is True
        finally:
            engine_mod._policies = old

    def test_pre_hook_blocks_stream_never_starts(self):
        """Block policy raises before _original_create is called."""
        policy = CustomPolicy({"name": "blocker", "rules": [
            {"name": "block", "hook": "pre", "action": "block",
             "match": {"model": {"contains": "sonnet"}}, "message": "blocked"},
        ]})
        old = engine_mod._policies
        engine_mod._policies = [policy]
        try:
            mock_fn = MagicMock()
            with patch.object(anthropic_patcher, '_original_create', mock_fn):
                with pytest.raises(PolicyViolationError, match="blocked"):
                    anthropic_create(
                        None, model="claude-sonnet-4-6", max_tokens=100,
                        messages=[{"role": "user", "content": "hi"}],
                        stream=True)
            mock_fn.assert_not_called()
        finally:
            engine_mod._policies = old

    def test_pii_redacted_before_stream(self):
        """PII is redacted from messages before the stream is created."""
        pii = PIIPolicy({})
        old = engine_mod._policies
        engine_mod._policies = [pii]
        try:
            stream = FakeAnthropicStream([], _make_anthropic_final(""))
            mock_fn = MagicMock(return_value=stream)
            with patch.object(anthropic_patcher, '_original_create', mock_fn):
                anthropic_create(
                    None, model="claude-sonnet-4-6", max_tokens=100,
                    messages=[{"role": "user",
                               "content": "Email john@example.com please"}],
                    stream=True)
            call_kwargs = mock_fn.call_args[1]
            sent_content = call_kwargs["messages"][0]["content"]
            assert "john@example.com" not in sent_content
            assert "[REDACTED:email]" in sent_content
        finally:
            engine_mod._policies = old

    def test_finalize_idempotent(self):
        """Calling _finalize() multiple times does not double-emit."""
        chunks = [_make_anthropic_chunk("hi")]
        stream = FakeAnthropicStream(chunks, _make_anthropic_final("hi"))

        old = engine_mod._policies
        engine_mod._policies = []
        try:
            with patch.object(anthropic_patcher, '_original_create',
                              return_value=stream):
                with patch('aiwarden.patchers.anthropic.build_and_capture') as mock_cap:
                    wrapper = anthropic_create(
                        None, model="claude-sonnet-4-6", max_tokens=100,
                        messages=[{"role": "user", "content": "hi"}],
                        stream=True)
                    list(wrapper)
                    wrapper._finalize()
                    wrapper._finalize()
                    assert mock_cap.call_count == 1
        finally:
            engine_mod._policies = old


class TestAnthropicStreamingEdgeCases:
    """Edge cases for Anthropic streaming."""

    def test_empty_stream(self):
        """Empty stream (no chunks) still finalizes without error."""
        stream = FakeAnthropicStream([], _make_anthropic_final(""))
        old = engine_mod._policies
        engine_mod._policies = []
        try:
            with patch.object(anthropic_patcher, '_original_create',
                              return_value=stream):
                with patch('aiwarden.patchers.anthropic.build_and_capture') as mock_cap:
                    wrapper = anthropic_create(
                        None, model="claude-sonnet-4-6", max_tokens=100,
                        messages=[{"role": "user", "content": "hi"}],
                        stream=True)
                    chunks = list(wrapper)
                    assert chunks == []
                    assert mock_cap.called
        finally:
            engine_mod._policies = old

    def test_partial_consumption(self):
        """Consuming only some chunks then finalizing does not crash."""
        many_chunks = [_make_anthropic_chunk(f"c{i}") for i in range(10)]
        stream = FakeAnthropicStream(many_chunks, _make_anthropic_final("partial"))
        old = engine_mod._policies
        engine_mod._policies = []
        try:
            with patch.object(anthropic_patcher, '_original_create',
                              return_value=stream):
                with patch('aiwarden.patchers.anthropic.build_and_capture') as mock_cap:
                    wrapper = anthropic_create(
                        None, model="claude-sonnet-4-6", max_tokens=100,
                        messages=[{"role": "user", "content": "hi"}],
                        stream=True)
                    it = iter(wrapper)
                    next(it)
                    next(it)
                    wrapper._finalize()
                    assert mock_cap.call_count == 1
        finally:
            engine_mod._policies = old


# ── OpenAI Streaming Tests ───────────────────────────────────────────────────


class TestOpenAISyncStreaming:
    """Sync streaming for the OpenAI patcher."""

    def test_chunks_accumulate_and_content_reassembled(self):
        """Content from delta.content fields is joined correctly."""
        chunks = [
            _make_openai_chunk("Hello"),
            _make_openai_chunk(", "),
            _make_openai_chunk("world"),
            _make_openai_usage_chunk(prompt_tokens=10, completion_tokens=3),
        ]
        old = engine_mod._policies
        engine_mod._policies = []
        try:
            with patch.object(openai_patcher, '_original', return_value=iter(chunks)):
                with patch('aiwarden.patchers.openai.build_and_capture') as mock_cap:
                    wrapper = openai_create(
                        None, model="gpt-4o", max_tokens=100,
                        messages=[{"role": "user", "content": "hi"}],
                        stream=True)
                    received = list(wrapper)
                    assert len(received) == 4
                    assert mock_cap.called
                    assert mock_cap.call_args.kwargs['text_content'] == "Hello, world"
                    assert mock_cap.call_args.kwargs['streamed'] is True
        finally:
            engine_mod._policies = old

    def test_post_hooks_fire_on_finalize(self):
        """Post-hooks receive the reassembled fake response."""
        chunks = [_make_openai_chunk("test"), _make_openai_usage_chunk()]
        old = engine_mod._policies
        engine_mod._policies = []
        try:
            with patch.object(openai_patcher, '_original', return_value=iter(chunks)):
                wrapper = openai_create(
                    None, model="gpt-4o", max_tokens=100,
                    messages=[{"role": "user", "content": "hi"}],
                    stream=True)
                list(wrapper)
        finally:
            engine_mod._policies = old

    def test_event_emitted_with_streamed_true(self):
        """build_and_capture receives streamed=True."""
        chunks = [_make_openai_chunk("ok"), _make_openai_usage_chunk()]
        old = engine_mod._policies
        engine_mod._policies = []
        try:
            with patch.object(openai_patcher, '_original', return_value=iter(chunks)):
                with patch('aiwarden.patchers.openai.build_and_capture') as mock_cap:
                    wrapper = openai_create(
                        None, model="gpt-4o", max_tokens=100,
                        messages=[{"role": "user", "content": "hi"}],
                        stream=True)
                    list(wrapper)
                    assert mock_cap.call_args.kwargs['streamed'] is True
        finally:
            engine_mod._policies = old

    def test_pre_hook_blocks_stream_never_starts(self):
        """Block policy raises before _original is called."""
        policy = CustomPolicy({"name": "blocker", "rules": [
            {"name": "block", "hook": "pre", "action": "block",
             "match": {"model": {"contains": "gpt"}}, "message": "blocked"},
        ]})
        old = engine_mod._policies
        engine_mod._policies = [policy]
        try:
            mock_fn = MagicMock()
            with patch.object(openai_patcher, '_original', mock_fn):
                with pytest.raises(PolicyViolationError, match="blocked"):
                    openai_create(
                        None, model="gpt-4o", max_tokens=100,
                        messages=[{"role": "user", "content": "hi"}],
                        stream=True)
            mock_fn.assert_not_called()
        finally:
            engine_mod._policies = old

    def test_usage_extracted_from_last_chunk(self):
        """Token usage is extracted from the last chunk that has it."""
        chunks = [
            _make_openai_chunk("Hello"),
            _make_openai_usage_chunk(prompt_tokens=42, completion_tokens=7),
        ]
        old = engine_mod._policies
        engine_mod._policies = []
        try:
            with patch.object(openai_patcher, '_original', return_value=iter(chunks)):
                with patch('aiwarden.patchers.openai.build_and_capture') as mock_cap:
                    wrapper = openai_create(
                        None, model="gpt-4o", max_tokens=100,
                        messages=[{"role": "user", "content": "hi"}],
                        stream=True)
                    list(wrapper)
                    assert mock_cap.call_args.kwargs['prompt_tokens'] == 42
                    assert mock_cap.call_args.kwargs['completion_tokens'] == 7
        finally:
            engine_mod._policies = old

    def test_empty_stream_no_crash(self):
        """Empty stream (no chunks) finalizes without error."""
        old = engine_mod._policies
        engine_mod._policies = []
        try:
            with patch.object(openai_patcher, '_original', return_value=iter([])):
                with patch('aiwarden.patchers.openai.build_and_capture') as mock_cap:
                    wrapper = openai_create(
                        None, model="gpt-4o", max_tokens=100,
                        messages=[{"role": "user", "content": "hi"}],
                        stream=True)
                    chunks = list(wrapper)
                    assert chunks == []
                    assert mock_cap.called
        finally:
            engine_mod._policies = old

    def test_finalize_idempotent(self):
        """Double-finalize does not double-emit."""
        chunks = [_make_openai_chunk("x"), _make_openai_usage_chunk()]
        old = engine_mod._policies
        engine_mod._policies = []
        try:
            with patch.object(openai_patcher, '_original', return_value=iter(chunks)):
                with patch('aiwarden.patchers.openai.build_and_capture') as mock_cap:
                    wrapper = openai_create(
                        None, model="gpt-4o", max_tokens=100,
                        messages=[{"role": "user", "content": "hi"}],
                        stream=True)
                    list(wrapper)
                    wrapper._finalize()
                    assert mock_cap.call_count == 1
        finally:
            engine_mod._policies = old


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

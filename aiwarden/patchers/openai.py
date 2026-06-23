import time

from aiwarden.patchers._common import build_and_capture
from aiwarden.policies import engine
from aiwarden.policies.base import PolicyViolationError

_patched  = False
_original = None


def patch(openai_module):
    """
    Patches at the class level for OpenAI SDK.
    openai.OpenAI().chat.completions.create → our wrapper
    """
    global _patched, _original
    if _patched:
        return
    _patched = True

    try:
        from openai.resources.chat.completions import Completions
        _original = Completions.create
        Completions.create = _patched_create
    except Exception:
        # Fallback: patch module-level attribute (older SDK versions)
        try:
            _original = openai_module.chat.completions.create
            openai_module.chat.completions.create = lambda *a, **kw: _patched_create(None, *a, **kw)
        except Exception:
            pass


# ── sync ──────────────────────────────────────────────────────────────────────

def _patched_create(self, *args, **kwargs):
    if kwargs.get("stream"):
        kwargs = {
            **kwargs,
            "stream_options": {
                **kwargs.get("stream_options", {}),
                "include_usage": True,
            },
        }
        kwargs, block, pre_fired = engine.run_pre(kwargs)
        if block:
            _emit_blocked(kwargs, pre_fired)
            raise PolicyViolationError(block.reason)
        api_kwargs = {k: v for k, v in kwargs.items() if not k.startswith("_")}
        raw_stream = _original(self, *args, **api_kwargs) if self else _original(*args, **api_kwargs)
        return _StreamWrapper(raw_stream, kwargs, time.monotonic(), pre_fired)

    # 1. PRE-HOOKS
    kwargs, block, pre_fired = engine.run_pre(kwargs)
    if block:
        _emit_blocked(kwargs, pre_fired)
        raise PolicyViolationError(block.reason)

    # 2. LLM CALL
    api_kwargs = {k: v for k, v in kwargs.items() if not k.startswith("_")}
    start      = time.monotonic()
    response   = _original(self, *args, **api_kwargs) if self else _original(*args, **api_kwargs)
    latency    = int((time.monotonic() - start) * 1000)

    # 3. POST-HOOKS
    response, post_fired = engine.run_post(kwargs, response)

    # 4. CAPTURE
    _emit(kwargs, response, latency, streamed=False, pre_fired=pre_fired, post_fired=post_fired)
    return response


# ── streaming wrapper ─────────────────────────────────────────────────────────

class _StreamWrapper:
    def __init__(self, stream, request_kwargs, start_time, pre_fired):
        self._stream    = stream
        self._kwargs    = request_kwargs
        self._start     = start_time
        self._pre_fired = pre_fired
        self._chunks    = []
        self._finalized = False

    def __iter__(self):
        return self

    def __next__(self):
        try:
            chunk = next(self._stream)
            self._chunks.append(chunk)
            return chunk
        except StopIteration:
            self._finalize()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._finalize()
        try:
            return self._stream.__exit__(*args)
        except Exception:
            return False

    def _finalize(self):
        if self._finalized:
            return
        self._finalized = True
        try:
            content = "".join(
                c.choices[0].delta.content or ""
                for c in self._chunks
                if c.choices and c.choices[0].delta and c.choices[0].delta.content
            )
            usage = next(
                (c.usage for c in reversed(self._chunks) if getattr(c, "usage", None)),
                None,
            )

            # Build a minimal response-like object for post-hooks
            from types import SimpleNamespace
            fake_msg = SimpleNamespace(content=content, tool_calls=None)
            fake_choice = SimpleNamespace(message=fake_msg, finish_reason="stop")
            fake_usage = SimpleNamespace(
                prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            )
            fake_response = SimpleNamespace(
                choices=[fake_choice],
                usage=fake_usage,
                model=self._kwargs.get("model", ""),
            )

            fake_response, post_fired = engine.run_post(self._kwargs, fake_response)
            latency = int((time.monotonic() - self._start) * 1000)
            _emit(self._kwargs, fake_response, latency, streamed=True,
                  pre_fired=self._pre_fired, post_fired=post_fired)
        except Exception:
            pass


# ── emit helpers ─────────────────────────────────────────────────────────────

def _emit(kwargs, response, latency_ms, streamed, pre_fired=None, post_fired=None):
    """Extract OpenAI-specific fields and delegate to common build_and_capture."""
    try:
        messages = kwargs.get("messages", [])
        model    = kwargs.get("model", getattr(response, "model", "unknown"))

        msg         = response.choices[0].message
        raw_content = getattr(msg, "content", "") or ""

        tool_calls = []
        if getattr(msg, "tool_calls", None):
            tool_calls = [
                {"name": tc.function.name, "arguments": tc.function.arguments, "id": getattr(tc, "id", "")}
                for tc in msg.tool_calls
            ]

        usage             = getattr(response, "usage", None)
        prompt_tokens     = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0

        build_and_capture(
            provider="openai",
            kwargs=kwargs,
            messages=messages,
            model=model,
            text_content=raw_content,
            tool_calls=tool_calls,
            finish_reason=getattr(response.choices[0], "finish_reason", "") or "",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            streamed=streamed,
            pre_fired=pre_fired,
            post_fired=post_fired,
            pii_found=kwargs.get("_pii_found", []),
        )
    except Exception:
        pass


def _emit_blocked(kwargs, pre_fired):
    """Emit event for a blocked request."""
    try:
        build_and_capture(
            provider="openai",
            kwargs=kwargs,
            messages=kwargs.get("messages", []),
            model=kwargs.get("model", "unknown"),
            finish_reason="blocked",
            pre_fired=pre_fired,
            blocked=True,
            pii_found=kwargs.get("_pii_found", []),
        )
    except Exception:
        pass

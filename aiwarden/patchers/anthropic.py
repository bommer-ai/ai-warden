import time

from aiwarden.patchers._common import build_and_capture
from aiwarden.policies import engine
from aiwarden.policies.base import PolicyViolationError

_patched         = False
_original_create = None


def patch(anthropic_module):
    """
    Patches at the Messages class level — works for all client instances.
    """
    global _patched, _original_create

    if _patched:
        return
    _patched = True

    try:
        from anthropic.resources.messages import Messages
        _original_create = Messages.create
        Messages.create  = _patched_create
    except Exception:
        pass

    try:
        from anthropic.resources.messages import AsyncMessages
        _patch_async(AsyncMessages)
    except Exception:
        pass

    try:
        from anthropic.resources.beta.messages import Messages as BetaMessages
        BetaMessages.create = _patched_create
    except Exception:
        pass

    try:
        from anthropic.resources.beta.messages import AsyncMessages as AsyncBetaMessages
        _patch_async(AsyncBetaMessages)
    except Exception:
        pass


# ── sync ──────────────────────────────────────────────────────────────────────

def _patched_create(self, *args, **kwargs):
    if kwargs.get("stream"):
        # Pre-hooks run before stream starts
        kwargs, block, pre_fired = engine.run_pre(kwargs)
        if block:
            _emit_blocked(kwargs, pre_fired)
            raise PolicyViolationError(block.reason)
        api_kwargs = {k: v for k, v in kwargs.items() if not k.startswith("_")}
        return _StreamWrapper(
            _original_create(self, *args, **api_kwargs), kwargs, time.monotonic(), pre_fired
        )

    # 1. PRE-HOOKS
    kwargs, block, pre_fired = engine.run_pre(kwargs)
    if block:
        _emit_blocked(kwargs, pre_fired)
        raise PolicyViolationError(block.reason)

    # 2. LLM CALL
    api_kwargs = {k: v for k, v in kwargs.items() if not k.startswith("_")}
    start      = time.monotonic()
    response   = _original_create(self, *args, **api_kwargs)
    latency    = int((time.monotonic() - start) * 1000)

    # 3. POST-HOOKS
    response, post_fired = engine.run_post(kwargs, response)

    # 4. CAPTURE
    _emit(kwargs, response, latency, streamed=False, pre_fired=pre_fired, post_fired=post_fired)
    return response


# ── async ─────────────────────────────────────────────────────────────────────

_original_async_create = None


def _patch_async(AsyncMessages):
    global _original_async_create
    _original_async_create = AsyncMessages.create

    async def patched(self, *args, **kwargs):
        kwargs, block, pre_fired = engine.run_pre(kwargs)
        if block:
            _emit_blocked(kwargs, pre_fired)
            raise PolicyViolationError(block.reason)

        api_kwargs = {k: v for k, v in kwargs.items() if not k.startswith("_")}
        start      = time.monotonic()
        response   = await _original_async_create(self, *args, **api_kwargs)
        latency    = int((time.monotonic() - start) * 1000)

        response, post_fired = engine.run_post(kwargs, response)
        _emit(kwargs, response, latency, streamed=False, pre_fired=pre_fired, post_fired=post_fired)
        return response

    AsyncMessages.create = patched


# ── streaming wrapper ─────────────────────────────────────────────────────────

class _StreamWrapper:
    def __init__(self, stream, request_kwargs, start_time, pre_fired):
        self._stream    = stream
        self._kwargs    = request_kwargs
        self._start     = start_time
        self._pre_fired = pre_fired
        self._finalized = False

    def __enter__(self):
        self._stream.__enter__()
        return self

    def __exit__(self, *args):
        result = self._stream.__exit__(*args)
        self._finalize()
        return result

    def __iter__(self):
        for chunk in self._stream:
            yield chunk
        self._finalize()

    def __getattr__(self, name):
        return getattr(self._stream, name)

    def _finalize(self):
        if self._finalized:
            return
        self._finalized = True
        try:
            final = self._stream.get_final_message()
            final, post_fired = engine.run_post(self._kwargs, final)
            latency = int((time.monotonic() - self._start) * 1000)
            _emit(self._kwargs, final, latency, streamed=True,
                  pre_fired=self._pre_fired, post_fired=post_fired)
        except Exception:
            pass


# ── emit helpers ─────────────────────────────────────────────────────────────

def _emit(kwargs, response, latency_ms, streamed, pre_fired=None, post_fired=None):
    """Extract Anthropic-specific fields and delegate to common build_and_capture."""
    try:
        messages = kwargs.get("messages", [])
        model    = kwargs.get("model", getattr(response, "model", "unknown"))
        system   = kwargs.get("system", "")
        if not isinstance(system, str):
            system = str(system)

        text_content = ""
        tool_calls   = []
        for block in getattr(response, "content", []):
            block_type = getattr(block, "type", "")
            if block_type == "text":
                text_content += getattr(block, "text", "")
            elif block_type == "tool_use":
                tool_calls.append({
                    "name":      getattr(block, "name", ""),
                    "arguments": str(getattr(block, "input", {})),
                    "id":        getattr(block, "id", ""),
                })

        usage             = getattr(response, "usage", None)
        prompt_tokens     = getattr(usage, "input_tokens", 0) or 0
        completion_tokens = getattr(usage, "output_tokens", 0) or 0

        build_and_capture(
            provider="anthropic",
            kwargs=kwargs,
            messages=messages,
            model=model,
            text_content=text_content,
            tool_calls=tool_calls,
            finish_reason=getattr(response, "stop_reason", None) or "",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            streamed=streamed,
            pre_fired=pre_fired,
            post_fired=post_fired,
            pii_found=kwargs.get("_pii_found", []),
            system=system,
        )
    except Exception:
        pass


def _emit_blocked(kwargs, pre_fired):
    """Emit event for a blocked request (no response)."""
    try:
        messages = kwargs.get("messages", [])
        model    = kwargs.get("model", "unknown")
        system   = kwargs.get("system", "")
        if not isinstance(system, str):
            system = str(system)

        build_and_capture(
            provider="anthropic",
            kwargs=kwargs,
            messages=messages,
            model=model,
            finish_reason="blocked",
            pre_fired=pre_fired,
            blocked=True,
            pii_found=kwargs.get("_pii_found", []),
            system=system,
        )
    except Exception:
        pass

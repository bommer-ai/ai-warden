import time
import traceback
from datetime import datetime, timezone
from uuid import uuid4

from aiwarden.capture import capture
from aiwarden.cost import compute_cost
from aiwarden.pipeline import pipeline
from aiwarden.pipeline.base import PolicyViolationError
from aiwarden.session import get_or_create_session_id, compute_turn
from aiwarden.tags import get_tags

_patched         = False
_original_create = None


def patch(anthropic_module):
    """
    Patches at the Messages class level — works for all client instances.
    anthropic.Anthropic().messages.create → our wrapper
    """
    global _patched, _original_create

    if _patched:
        return
    _patched = True

    try:
        from anthropic.resources.messages import Messages
        _original_create    = Messages.create
        Messages.create     = _patched_create
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
        return _StreamWrapper(
            _original_create(self, *args, **kwargs), kwargs, time.monotonic()
        )

    # 1. PRE-PROCESSORS — run on request before API call
    #    Can modify kwargs (inject memory, redact PII, add context)
    #    or block the request entirely (budget exceeded, policy violation)
    kwargs, block = pipeline.run_pre(kwargs)
    if block:
        raise PolicyViolationError(block.reason)

    # 2. real API call — kwargs may have been modified by pre-processors
    #    Strip internal keys we stashed (prefixed with _) before sending
    api_kwargs = {k: v for k, v in kwargs.items() if not k.startswith("_")}
    start      = time.monotonic()
    response   = _original_create(self, *args, **api_kwargs)
    latency    = int((time.monotonic() - start) * 1000)

    # 3. POST-PROCESSORS — run on response before returning to agent
    #    Can modify what the agent sees (guardrails, PII from output, etc.)
    response = pipeline.run_post(kwargs, response)

    # 4. capture event for analytics (non-blocking)
    _emit(kwargs, response, latency, streamed=False)
    return response


# ── async ─────────────────────────────────────────────────────────────────────

_original_async_create = None


def _patch_async(AsyncMessages):
    global _original_async_create
    _original_async_create = AsyncMessages.create

    async def patched(self, *args, **kwargs):
        kwargs, block = pipeline.run_pre(kwargs)
        if block:
            raise PolicyViolationError(block.reason)

        api_kwargs = {k: v for k, v in kwargs.items() if not k.startswith("_")}
        start      = time.monotonic()
        response   = await _original_async_create(self, *args, **api_kwargs)
        latency    = int((time.monotonic() - start) * 1000)

        response = pipeline.run_post(kwargs, response)
        _emit(kwargs, response, latency, streamed=False)
        return response

    AsyncMessages.create = patched


# ── streaming wrapper ─────────────────────────────────────────────────────────

class _StreamWrapper:
    """
    Wraps Anthropic streaming context manager transparently.
    Pre-processors run before stream starts, post-processors run on final message.
    """
    def __init__(self, stream, request_kwargs, start_time):
        self._stream  = stream
        self._kwargs  = request_kwargs
        self._start   = start_time

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
        try:
            final   = self._stream.get_final_message()
            final   = pipeline.run_post(self._kwargs, final)
            latency = int((time.monotonic() - self._start) * 1000)
            _emit(self._kwargs, final, latency, streamed=True)
        except Exception:
            pass


# ── shared emit ───────────────────────────────────────────────────────────────

def _extract_caller() -> dict:
    stack = traceback.extract_stack()
    for frame in reversed(stack):
        if (
            "aiwarden" not in frame.filename
            and "site-packages" not in frame.filename
            and "anthropic" not in frame.filename
        ):
            return {
                "caller_file":     frame.filename,
                "caller_line":     frame.lineno,
                "caller_function": frame.name,
            }
    return {}


def _emit(kwargs: dict, response, latency_ms: int, streamed: bool):
    """
    Captures the event for analytics.
    By this point:
      - kwargs["messages"] are already PII-cleaned (by PIIRedactPreProcessor)
      - response may already be modified (by post-processors)
    So we just record what's here — no inline redaction needed.
    """
    try:
        messages = kwargs.get("messages", [])
        system   = kwargs.get("system", "")
        model    = kwargs.get("model", getattr(response, "model", "unknown"))

        # PII metadata stashed by PIIRedactPreProcessor
        pii_found = kwargs.get("_pii_found", [])

        # extract text content and tool calls from response
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

        # usage
        usage             = getattr(response, "usage", None)
        prompt_tokens     = getattr(usage, "input_tokens",  0) or 0
        completion_tokens = getattr(usage, "output_tokens", 0) or 0
        cost              = compute_cost(model, prompt_tokens, completion_tokens)

        # session
        session_id = get_or_create_session_id(messages)
        turn       = compute_turn(messages)

        # auto tags from metadata
        auto_tags = {}
        if meta := kwargs.get("metadata", {}):
            auto_tags.update(meta)

        event = {
            "id":                str(uuid4()),
            "timestamp":         datetime.now(timezone.utc).isoformat(),
            "provider":          "anthropic",
            "type":              "chat",
            "model":             model,
            "session_id":        session_id,
            "turn":              turn,
            "streamed":          streamed,
            "prompt_tokens":     prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost":              cost,
            "latency_ms":        latency_ms,
            "finish_reason":     getattr(response, "stop_reason", None),
            "tool_calls":        tool_calls,
            "pii_redacted":      bool(pii_found),
            "pii_types_found":   list(set(pii_found)),
            "request_messages":  messages,     # already clean — pre-processor ran
            "response_content":  text_content, # already clean — post-processor ran
            "system":            system,
            "tags":              {**auto_tags, **get_tags()},
            **_extract_caller(),
        }

        capture(event)

    except Exception:
        pass  # never crash user app

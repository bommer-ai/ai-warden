import time
import traceback
from datetime import datetime, timezone
from uuid import uuid4

from aiwarden.capture import capture
from aiwarden.cost import compute_cost
from aiwarden.policies import engine
from aiwarden.policies.base import PolicyViolationError
from aiwarden.session import get_or_create_session_id, compute_turn
from aiwarden.tags import get_tags

_patched  = False
_original = None


def patch(openai_module):
    global _patched, _original
    if _patched:
        return
    _patched  = True
    _original = openai_module.chat.completions.create

    openai_module.chat.completions.create = _patched_create


# ── sync ──────────────────────────────────────────────────────────────────────

def _patched_create(*args, **kwargs):
    if kwargs.get("stream"):
        kwargs = {
            **kwargs,
            "stream_options": {
                **kwargs.get("stream_options", {}),
                "include_usage": True,
            },
        }
        # pre-processors run before stream starts
        kwargs, block = engine.run_pre(kwargs)
        if block:
            raise PolicyViolationError(block.reason)
        api_kwargs = {k: v for k, v in kwargs.items() if not k.startswith("_")}
        return _StreamWrapper(_original(*args, **api_kwargs), kwargs, time.monotonic())

    # 1. PRE-PROCESSORS
    kwargs, block = engine.run_pre(kwargs)
    if block:
        raise PolicyViolationError(block.reason)

    # 2. real API call
    api_kwargs = {k: v for k, v in kwargs.items() if not k.startswith("_")}
    start      = time.monotonic()
    response   = _original(*args, **api_kwargs)
    latency    = int((time.monotonic() - start) * 1000)

    # 3. POST-PROCESSORS
    response = engine.run_post(kwargs, response)

    # 4. capture event
    _emit(kwargs, response, latency, streamed=False)
    return response


# ── streaming wrapper ─────────────────────────────────────────────────────────

class _StreamWrapper:
    def __init__(self, stream, request_kwargs, start_time):
        self._stream  = stream
        self._kwargs  = request_kwargs
        self._start   = start_time
        self._chunks  = []

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
        return self._stream.__exit__(*args)

    def _finalize(self):
        content = "".join(
            c.choices[0].delta.content or ""
            for c in self._chunks
            if c.choices and c.choices[0].delta.content
        )
        usage = next(
            (c.usage for c in reversed(self._chunks) if getattr(c, "usage", None)),
            None,
        )

        class _FakeResponse:
            class _Choice:
                class _Message:
                    pass
                message      = _Message()
                finish_reason = "stop"
            choices = [_Choice()]

            class _Usage:
                prompt_tokens     = getattr(usage, "prompt_tokens",     0)
                completion_tokens = getattr(usage, "completion_tokens", 0)

        resp = _FakeResponse()
        resp.choices[0].message.content    = content
        resp.choices[0].message.tool_calls = None
        resp.usage = _FakeResponse._Usage()

        resp = engine.run_post(self._kwargs, resp)
        latency = int((time.monotonic() - self._start) * 1000)
        _emit(self._kwargs, resp, latency, streamed=True)


# ── shared emit ───────────────────────────────────────────────────────────────

def _extract_caller() -> dict:
    stack = traceback.extract_stack()
    for frame in reversed(stack):
        if "aiwarden" not in frame.filename and "site-packages" not in frame.filename:
            return {
                "caller_file":     frame.filename,
                "caller_line":     frame.lineno,
                "caller_function": frame.name,
            }
    return {}


def _emit(kwargs: dict, response, latency_ms: int, streamed: bool):
    try:
        messages = kwargs.get("messages", [])
        model    = kwargs.get("model", "unknown")

        # PII metadata stashed by PIIRedactPreProcessor
        pii_found = kwargs.get("_pii_found", [])

        msg         = response.choices[0].message
        raw_content = getattr(msg, "content", "") or ""

        tool_calls = []
        if getattr(msg, "tool_calls", None):
            tool_calls = [
                {"name": tc.function.name, "arguments": tc.function.arguments}
                for tc in msg.tool_calls
            ]

        usage             = response.usage
        prompt_tokens     = getattr(usage, "prompt_tokens",     0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        cost              = compute_cost(model, prompt_tokens, completion_tokens)

        session_id = get_or_create_session_id(messages)
        turn       = compute_turn(messages)

        auto_tags = {}
        if user := kwargs.get("user"):
            auto_tags["user"] = user

        event = {
            "id":                str(uuid4()),
            "timestamp":         datetime.now(timezone.utc).isoformat(),
            "provider":          "openai",
            "type":              "chat",
            "model":             model,
            "session_id":        session_id,
            "turn":              turn,
            "streamed":          streamed,
            "prompt_tokens":     prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost":              cost,
            "latency_ms":        latency_ms,
            "finish_reason":     getattr(response.choices[0], "finish_reason", None),
            "tool_calls":        tool_calls,
            "pii_redacted":      bool(pii_found),
            "pii_types_found":   pii_found,
            "request_messages":  messages,    # already clean
            "response_content":  raw_content, # already clean
            "tags":              {**auto_tags, **get_tags()},
            **_extract_caller(),
        }

        capture(event)

    except Exception:
        pass

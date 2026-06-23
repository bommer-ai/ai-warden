"""
Shared event-building logic for all patchers.
Eliminates duplication between Anthropic and OpenAI patchers.
"""
import traceback

from aiwarden import config
from aiwarden.capture import capture
from aiwarden.cost import compute_cost
from aiwarden.event import LLMEvent, PolicyResult
from aiwarden.session import get_run_state, increment_turn, mark_run_completed, record_cost, record_tool
from aiwarden.tags import get_tags


def extract_caller(exclude_modules: tuple = ("aiwarden", "site-packages")) -> dict:
    """Walk the stack to find the user's call site. Disabled when CALLER_TRACKING=false."""
    if not config.CALLER_TRACKING:
        return {}
    stack = traceback.extract_stack()
    for frame in reversed(stack):
        if not any(mod in frame.filename for mod in exclude_modules):
            return {
                "caller_file": frame.filename,
                "caller_line": frame.lineno,
                "caller_function": frame.name,
            }
    return {}


def build_and_capture(
    provider: str,
    kwargs: dict,
    messages: list,
    model: str,
    text_content: str = "",
    tool_calls: list = None,
    finish_reason: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    latency_ms: int = 0,
    streamed: bool = False,
    pre_fired: list = None,
    post_fired: list = None,
    blocked: bool = False,
    pii_found: list = None,
    system: str = "",
):
    """Build LLMEvent, update RunState, and send to capture. Never raises."""
    try:
        tool_calls = tool_calls or []
        pii_found = pii_found or []

        # Run state tracking
        run_state = get_run_state(kwargs, messages)
        increment_turn(run_state)
        cost = compute_cost(model, prompt_tokens, completion_tokens)
        record_cost(run_state, cost)
        for tc in tool_calls:
            record_tool(run_state, tc.get("name", ""))

        # Mark run completed when agent loop ends
        _TERMINAL_REASONS = {"end_turn", "stop", "stop_sequence"}
        if finish_reason in _TERMINAL_REASONS and not tool_calls:
            mark_run_completed(run_state)

        # Policies
        all_fired = (pre_fired or []) + (post_fired or [])
        policy_fired = len(all_fired) > 0

        # Custom fields (user's _ prefixed keys)
        internal_keys = {"_pii_found", "_run_id", "_policy_blocked",
                        "_blocked_rule", "_blocked_tool", "_blocked_input"}
        custom_fields = {k: v for k, v in kwargs.items()
                        if k.startswith("_") and k not in internal_keys}

        # Metadata
        metadata = kwargs.get("metadata", {}) or {}

        # Caller
        caller = extract_caller()

        event = LLMEvent(
            provider=provider,
            model=model,
            run_id=run_state.run_id,
            turn=run_state.turn,
            request_messages=messages,
            system=system,
            response_content=text_content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            streamed=streamed,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost=cost,
            latency_ms=latency_ms,
            policy_fired=policy_fired,
            policy_blocked=blocked,
            policies=all_fired,
            pii_redacted=bool(pii_found),
            pii_types_found=list(set(pii_found)),
            tags={**metadata, **get_tags()},
            metadata=metadata,
            custom_fields=custom_fields,
            caller_file=caller.get("caller_file", ""),
            caller_line=caller.get("caller_line", 0),
            caller_function=caller.get("caller_function", ""),
        )

        capture(event.to_dict())

    except Exception:
        pass

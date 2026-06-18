"""
Session / run tracking for ai-warden.

Design:
  - ContextVar holds the RunState (source of truth for run_id, turns, cost)
  - OTel trace_id is used as the SIGNAL for when to reset ContextVar
  - If OTel trace changes → new run (reset ContextVar)
  - If OTel trace same → same run (keep ContextVar)
  - No OTel → fallback: turn==0 (no assistant messages) means new run

This correctly identifies:
  - Single agent runs (multiple LLM calls in a loop)
  - Multi-agent flows (Agent A triggers Agent B within same request/trace)
  - Sequential runs on the same thread (different traces or fresh messages)

Known limitations:
  - Without OTel: if messages are compressed/truncated mid-run and all assistant
    messages are removed, a new RunState is created (splits the run). Fix: use OTel
    in production, or pass _run_id explicitly.
  - Without OTel: pre-filled messages with assistant turns on a thread that already
    had a previous run will continue the old run's state. Fix: clear ContextVar
    between tasks, or use OTel.
  - Turn counter is per-process. Multiple processes each track independently.
"""
import time as _time
from contextvars import ContextVar
from dataclasses import dataclass, field
from uuid import uuid4


# ── Run state ────────────────────────────────────────────────────────────────

@dataclass
class RunState:
    """Mutable state for a single agent run."""
    run_id: str
    turn: int = 0
    start_time: float = field(default_factory=_time.monotonic)
    total_cost: float = 0.0
    tools_called: list = field(default_factory=list)


_current_run: ContextVar[RunState | None] = ContextVar("aiwarden_run", default=None)
_last_otel_trace: ContextVar[str | None] = ContextVar("aiwarden_last_trace", default=None)


# ── Public API ───────────────────────────────────────────────────────────────

def get_run_state(kwargs: dict, messages: list) -> RunState:
    """
    Get (or create) the RunState for this create() call.

    Priority:
      1. _run_id in kwargs → user override, always wins
      2. OTel trace_id → if changed from last seen, start new run
      3. ContextVar + turn==0 → fallback for no-OTel environments
    """
    # 1. User override
    if explicit_id := kwargs.get("_run_id"):
        return _ensure_run(str(explicit_id))

    # 2. OTel trace — use as change-detection signal
    otel_id = _get_otel_trace_id()
    if otel_id:
        last_trace = _last_otel_trace.get()
        if otel_id != last_trace:
            # Trace changed → new run
            _last_otel_trace.set(otel_id)
            return _new_run()
        else:
            # Same trace → same run
            state = _current_run.get()
            if state:
                return state
            return _new_run()

    # 3. No OTel — use turn==0 heuristic
    state = _current_run.get()
    has_assistant = any(m.get("role") == "assistant" for m in messages)

    if state is None or not has_assistant:
        # First call or fresh messages → new run
        return _new_run()

    # Continuing existing run
    return state


def get_run_id(kwargs: dict, messages: list) -> str:
    """Convenience: just the run_id string."""
    return get_run_state(kwargs, messages).run_id


def increment_turn(state: RunState):
    """Increment turn counter. Called on every create() call."""
    state.turn += 1


def record_cost(state: RunState, cost: float):
    """Accumulate cost for this run."""
    state.total_cost += cost


def record_tool(state: RunState, tool_name: str):
    """Record a tool invocation."""
    state.tools_called.append(tool_name)


def compute_turn(messages: list) -> int:
    """Legacy: derive turn from messages. Prefer RunState.turn."""
    return len([m for m in messages if m.get("role") == "assistant"])


# ── Internal ─────────────────────────────────────────────────────────────────

def _new_run() -> RunState:
    """Create a fresh RunState and store in ContextVar."""
    state = RunState(run_id=uuid4().hex[:16])
    _current_run.set(state)
    return state


def _ensure_run(run_id: str) -> RunState:
    """Get existing state if run_id matches, or create new with given id."""
    state = _current_run.get()
    if state and state.run_id == run_id:
        return state
    state = RunState(run_id=run_id)
    _current_run.set(state)
    return state


def _get_otel_trace_id() -> str | None:
    """Read trace_id from current OTel span. Returns None if OTel isn't active."""
    try:
        from opentelemetry import trace as _otel_trace
        span = _otel_trace.get_current_span()
        ctx = span.get_span_context()
        if ctx and ctx.trace_id:
            return format(ctx.trace_id, '032x')
    except (ImportError, Exception):
        pass
    return None


# ── Legacy API ───────────────────────────────────────────────────────────────

def get_or_create_session_id(messages: list) -> str:
    """Backwards-compatible."""
    return get_run_state({}, messages).run_id

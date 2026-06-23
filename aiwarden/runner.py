"""
Hot mode: aiwarden.run() — deterministic run tracking.

HOW THE CODE DECIDES WHICH MODE TO USE:
  - Hot mode:    user wraps with `aiwarden.run()` → sets RunState in ContextVar
                 → patcher detects it (session.get_run_state line 60) → skips all heuristics
  - Patcher mode: no wrapper → session.get_run_state uses OTel/heuristics to figure out runs

The patcher ALWAYS runs (it's the one calling the LLM). The wrapper just gives it
better signal. There's no "mode switch" — the patcher checks ContextVar first,
falls back to heuristics if empty.

WHAT GETS LOGGED (events.jsonl):
  - Per-call events (type: "chat") — ALWAYS emitted by the patcher on every create() call.
    Contains: latency, tokens, cost, model, policy_fired, tool_calls.
    This is the raw telemetry. Logged in both modes.

  - Run summary (type: "run_summary") — ONLY emitted in hot mode, once per wrapper exit.
    Contains: total cost, total turns, duration, status, children.
    This is the aggregate. NOT logged in patcher-only mode.

In patcher-only mode, the consumer aggregates per-call events by run_id themselves.
In hot mode, they get both: raw per-call + finished run summaries.
"""
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from uuid import uuid4

_current_run_ctx: ContextVar["Run | None"] = ContextVar("aiwarden_hotmode_run", default=None)


@dataclass
class Run:
    """Represents a tracked agent run. Available inside and after `with aiwarden.run():`."""
    id: str = field(default_factory=lambda: uuid4().hex[:16])
    agent: str = "default"
    status: str = "running"

    # Metrics (updated live by the patcher via session.py integration)
    turns: int = 0
    cost: float = 0.0
    tools: list = field(default_factory=list)
    start_time: float = field(default_factory=time.monotonic)
    end_time: float = 0.0

    # Topology
    parent_id: str = ""
    children: list = field(default_factory=list)

    # Internal
    _error: Exception = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _summary_emitted: bool = field(default=False, repr=False)

    @property
    def duration(self) -> float:
        """Duration in seconds."""
        end = self.end_time or time.monotonic()
        return round(end - self.start_time, 3)

    @property
    def duration_ms(self) -> int:
        return int(self.duration * 1000)

    def summary(self) -> dict:
        return {
            "run_id": self.id,
            "agent": self.agent,
            "status": self.status,
            "turns": self.turns,
            "cost": self.cost,
            "duration_ms": self.duration_ms,
            "tools": list(set(self.tools)),
            "children": [c.id for c in self.children],
            "parent_id": self.parent_id,
            "error": str(self._error) if self._error else None,
        }


@contextmanager
def run(agent: str = None, id: str = None):
    """
    Hot mode context manager. Tracks everything deterministically.

    Args:
        agent: Agent name for policy scoping. If None, inherits from
               aiwarden.agent() context or falls back to "default".
        id: Custom run ID (auto-generated if not provided)

    Yields:
        Run object with live metrics (turns, cost, duration, tools)
    """
    from aiwarden import _current_agent, get_agent
    from aiwarden.session import _current_run as session_run_ctx, RunState

    # Resolve agent name: explicit param > existing context > "default"
    resolved_agent = agent or get_agent() or "default"

    current = Run(
        id=id or uuid4().hex[:16],
        agent=resolved_agent,
    )

    # Check for parent run (nested wrappers) — thread-safe append
    parent = _current_run_ctx.get()
    if parent:
        current.parent_id = parent.id
        with parent._lock:
            parent.children.append(current)

    # Set ContextVars
    run_token = _current_run_ctx.set(current)
    agent_token = _current_agent.set(resolved_agent)

    # Set session RunState — patcher will write into this
    run_state = RunState(run_id=current.id)
    session_token = session_run_ctx.set(run_state)

    try:
        yield current
        current.status = "completed"
    except Exception as e:
        current.status = "errored"
        current._error = e
        raise
    finally:
        # Finalize: drain RunState metrics into the Run object
        current.turns += run_state.turn
        current.cost += run_state.total_cost
        current.tools.extend(run_state.tools_called)
        current.end_time = time.monotonic()

        # Accumulate to parent (thread-safe)
        if parent:
            with parent._lock:
                parent.cost += current.cost

        # Emit run summary (idempotent)
        _emit_run_summary(current)

        # Restore ContextVars
        session_run_ctx.reset(session_token)
        _current_agent.reset(agent_token)
        _current_run_ctx.reset(run_token)


def get_current_run() -> "Run | None":
    """Get the current active Run (if inside a `with aiwarden.run():` block)."""
    return _current_run_ctx.get()


def _emit_run_summary(r: Run):
    """Emit a run-completed summary event. Idempotent — only fires once per Run."""
    if r._summary_emitted:
        return
    r._summary_emitted = True

    try:
        from aiwarden.capture import capture
        from aiwarden import config
        from datetime import datetime, timezone

        if not config.ENABLED:
            return

        event = {
            "id": uuid4().hex,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "run_summary",
            "run_id": r.id,
            "agent": r.agent,
            "status": r.status,
            "turns": r.turns,
            "cost": r.cost,
            "duration_ms": r.duration_ms,
            "tools_used": list(set(r.tools)),
            "parent_id": r.parent_id,
            "children": [c.id for c in r.children],
            "error": str(r._error) if r._error else None,
        }
        capture(event)
    except Exception:
        pass

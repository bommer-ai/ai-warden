"""ai-warden: Agent safety, observability, and control."""
from contextlib import contextmanager
from contextvars import ContextVar

from aiwarden.config import configure
from aiwarden.tags import tag

__version__ = "0.1.0"
__all__ = ["configure", "tag", "agent", "get_agent", "run", "get_current_run"]

_current_agent: ContextVar[str] = ContextVar("aiwarden_agent", default="")


@contextmanager
def agent(name: str):
    """Scope all LLM calls inside this block to the given agent name."""
    token = _current_agent.set(name)
    try:
        yield
    finally:
        _current_agent.reset(token)


def get_agent() -> str:
    """Get the current agent name from ContextVar."""
    return _current_agent.get()


# ── Hot mode: aiwarden.run() ─────────────────────────────────────────────────

from aiwarden.runner import Run, run, get_current_run  # noqa: E402

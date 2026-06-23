from contextlib import contextmanager
from contextvars import ContextVar

_current_tags: ContextVar[dict] = ContextVar("aiwarden_tags", default={})


@contextmanager
def tag(**kwargs):
    current = _current_tags.get()
    token   = _current_tags.set({**current, **kwargs})
    try:
        yield
    finally:
        _current_tags.reset(token)


def get_tags() -> dict:
    return _current_tags.get()

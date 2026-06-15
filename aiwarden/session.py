from contextvars import ContextVar
from uuid import uuid4

_auto_session: ContextVar[str] = ContextVar("aiwarden_session", default=None)


def compute_turn(messages: list) -> int:
    return len([m for m in messages if m.get("role") == "assistant"])


def get_or_create_session_id(messages: list) -> str:
    turn = compute_turn(messages)

    if turn == 0:
        new_id = uuid4().hex[:16]
        _auto_session.set(new_id)
        return new_id

    if sid := _auto_session.get():
        return sid

    return uuid4().hex[:16]

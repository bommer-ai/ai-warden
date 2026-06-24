"""
Field resolution and rule evaluation for custom policies.

Handles dotted-path resolution into nested dicts/lists,
when-condition checking, and full rule evaluation.
"""
from aiwarden.policies.custom.operators import match_value
from aiwarden.policies.custom.schema import CustomRule


def resolve_field(data: dict, field_path: str):
    """
    Resolve a dotted path from a dict.
    Supports: 'model', 'metadata.team', 'messages.0.content'
    Returns None if path doesn't exist.
    """
    node = data
    for key in field_path.split("."):
        if isinstance(node, dict):
            node = node.get(key)
        elif isinstance(node, list):
            try:
                node = node[int(key)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if node is None:
            return None
    return node


def check_when(data: dict, when: dict) -> bool:
    """Check when conditions. All must match (AND logic)."""
    for path, expected in when.items():
        actual = resolve_field(data, path)
        if str(actual) != str(expected):
            return False
    return True


def evaluate_rule(rule: CustomRule, data: dict) -> bool:
    """Evaluate a single rule against the data dict. Returns True if rule fires."""
    if rule.when and not check_when(data, rule.when):
        return False

    for field_path, matchers in rule.match.items():
        if field_path in ("messages.content", "request.messages.content"):
            messages = data.get("messages", [])
            if not any(
                isinstance(m.get("content", ""), str) and match_value(m["content"], matchers)
                for m in messages
            ):
                return False
        elif field_path.startswith("response."):
            response_key = "_" + field_path.replace("response.", "")
            value = data.get(response_key)
            if not match_value(value, matchers):
                return False
        elif field_path.startswith("run."):
            value = _resolve_run_field(field_path)
            if not match_value(value, matchers):
                return False
        else:
            value = resolve_field(data, field_path)
            if not match_value(value, matchers):
                return False

    return True


def _resolve_run_field(field_path: str):
    """Resolve run.* fields from the current RunState or active Run."""
    from aiwarden.session import _current_run
    state = _current_run.get()
    if state is None:
        return None

    field_name = field_path.replace("run.", "", 1)
    if field_name == "turns":
        return state.turn
    elif field_name == "cost":
        return state.total_cost
    elif field_name == "tools_count":
        return len(state.tools_called)
    elif field_name == "duration":
        import time
        return time.monotonic() - state.start_time
    return None

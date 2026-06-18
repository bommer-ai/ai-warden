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
        else:
            value = resolve_field(data, field_path)
            if not match_value(value, matchers):
                return False

    return True

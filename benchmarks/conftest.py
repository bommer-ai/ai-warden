"""
Shared fixtures for benchmark and stress tests.
Provides fake responses, policy configs, request builders, and rule generators.
"""
import re
from types import SimpleNamespace
from uuid import uuid4


def make_request(content="Hello, please help me.", num_messages=1, metadata=None):
    messages = []
    for i in range(num_messages):
        role = "user" if i % 2 == 0 else "assistant"
        messages.append({"role": role, "content": f"{content} (msg {i})"})
    req = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 1024,
        "messages": messages,
    }
    if metadata:
        req["metadata"] = metadata
    return req


def make_pii_request(size_kb=1, num_messages=1):
    pii_content = (
        "Contact john.doe@example.com or call 555-123-4567. "
        "SSN: 123-45-6789. API key: sk-abcdefghijklmnopqrstuvwxyz. "
        "Credit card: 4111 1111 1111 1111. "
    )
    padding = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 10
    block = pii_content + padding
    target_chars = size_kb * 1024
    content = (block * (target_chars // len(block) + 1))[:target_chars]
    messages = [{"role": "user", "content": content} for _ in range(num_messages)]
    return {"model": "claude-sonnet-4-6", "max_tokens": 1024, "messages": messages}


def make_anthropic_response(text="OK", input_tokens=100, output_tokens=50,
                            stop_reason="end_turn", tool_calls=None):
    content = []
    if tool_calls:
        for tc in tool_calls:
            content.append(SimpleNamespace(
                type="tool_use",
                id=f"toolu_{uuid4().hex[:24]}",
                name=tc["name"],
                input=tc.get("input", {}),
            ))
    else:
        content.append(SimpleNamespace(type="text", text=text))

    return SimpleNamespace(
        id=f"msg_{uuid4().hex[:24]}",
        model="claude-sonnet-4-6",
        role="assistant",
        type="message",
        stop_reason=stop_reason,
        content=content,
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def generate_custom_rules(n, hook="pre", action="warn"):
    rules = []
    for i in range(n):
        rules.append({
            "name": f"rule-{i:04d}",
            "hook": hook,
            "action": action,
            "message": f"Rule {i} triggered",
            "match": {
                "model": {"contains": f"nonexistent-model-{i}"},
            },
        })
    return rules


def generate_complex_rules(n, hook="pre", action="warn"):
    rules = []
    for i in range(n):
        rules.append({
            "name": f"complex-rule-{i:04d}",
            "hook": hook,
            "action": action,
            "message": f"Complex rule {i} triggered",
            "match": {
                "model": {"startswith": f"nonexistent-{i}", "not_contains": "blocked"},
                f"metadata.field_{i}": {"equals": f"value_{i}"},
                f"metadata.nested.level_{i}": {"contains": f"deep_{i}"},
                "messages.content": {"not_contains": f"forbidden_{i}"},
            },
            "when": {
                f"metadata.env_{i}": f"production_{i}",
            },
        })
    return rules


def generate_pii_patterns(n):
    patterns = {}
    for i in range(n):
        patterns[f"custom_pattern_{i}"] = rf"\bCUSTOM{i}-\d{{4,8}}\b"
    return patterns


def make_tool_policy_config(num_rules=10):
    rules = []
    for i in range(num_rules):
        rules.append({
            "name": f"tool-rule-{i}",
            "action": "warn",
            "message": f"Tool rule {i} triggered",
            "match_tool": f"dangerous_tool_{i}",
            "match_args": {"path": {"startswith": f"/forbidden_{i}/"}},
        })
    return {
        "name": "bench-tool-safety",
        "type": "tools",
        "enabled": True,
        "builtin": {"filesystem-safety": True, "no-privilege-escalation": True},
        "rules": rules,
    }


def make_budget_config(num_groups=100):
    limits = {f"team-{i}": float(i + 1) * 10.0 for i in range(num_groups)}
    limits["default"] = 100.0
    return {
        "name": "bench-budget",
        "type": "budget",
        "enabled": True,
        "group_by": "metadata.team",
        "limits": limits,
        "reset": "monthly",
    }

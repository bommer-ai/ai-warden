"""
Policy engine tests.

Covers:
  - Rule matching: tool name (exact, glob, list), arg matchers, any_arg, when_metadata
  - Actions: refusal (response replaced), interrupt (exception raised), warn (passthrough)
  - Built-in templates: filesystem-safety, no-privilege-escalation
  - Rule parser: _parse_rule handles all match/when fields
  - ToolsPolicy: end-to-end with a fake Anthropic response object
"""

import textwrap
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from aiwarden.policies.base import PolicyViolationError
from aiwarden.policies.builtin.tools import ToolsPolicy, _build_refusal
from aiwarden.policies.builtin.tools_rules import (
    BUILTIN_TEMPLATES,
    PolicyRule,
    _match_field,
    _match_tool,
    _parse_rule,
    matches,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _tool_use(name: str, **input_kwargs):
    """Minimal tool_use block (mirrors Anthropic SDK shape)."""
    return SimpleNamespace(type="tool_use", name=name, input=input_kwargs)


def _text_block(text: str):
    return SimpleNamespace(type="text", text=text)


def _response(*blocks):
    """Fake Anthropic Message with content blocks and model_copy support."""
    class FakeMessage:
        def __init__(self, content):
            self.content     = list(content)
            self.stop_reason = "tool_use"

        def model_copy(self, *, update=None):
            copy = FakeMessage(self.content)
            for k, v in (update or {}).items():
                setattr(copy, k, v)
            return copy

    return FakeMessage(blocks)


# ── _match_field ──────────────────────────────────────────────────────────────

class TestMatchField:
    def test_contains_match(self):
        assert _match_field("rm -rf /data", {"contains": "rm -rf"})

    def test_contains_no_match(self):
        assert not _match_field("ls -la", {"contains": "rm -rf"})

    def test_startswith_string(self):
        assert _match_field("sudo apt install", {"startswith": "sudo"})

    def test_startswith_list_any(self):
        assert _match_field("/etc/passwd", {"startswith": ["/etc/", "/sys/"]})

    def test_startswith_list_none(self):
        assert not _match_field("/home/user", {"startswith": ["/etc/", "/sys/"]})

    def test_not_startswith(self):
        assert _match_field("/home/user/file.txt", {"not_startswith": ["/etc/", "/sys/"]})
        assert not _match_field("/etc/hosts", {"not_startswith": ["/etc/", "/sys/"]})

    def test_equals(self):
        assert _match_field("prod", {"equals": "prod"})
        assert not _match_field("staging", {"equals": "prod"})

    def test_in(self):
        assert _match_field("prod", {"in": ["prod", "staging"]})
        assert not _match_field("dev", {"in": ["prod", "staging"]})

    def test_regex_match(self):
        assert _match_field("rm -rf /data", {"regex": r"rm\s+-[rRfF]*[rR]"})

    def test_regex_no_match(self):
        assert not _match_field("rm file.txt", {"regex": r"rm\s+-[rRfF]*[rR]"})

    def test_multiple_ops_all_must_match(self):
        assert _match_field("sudo rm -rf /", {"contains": "rm -rf", "startswith": "sudo"})
        assert not _match_field("rm -rf /", {"contains": "rm -rf", "startswith": "sudo"})


# ── _match_tool ───────────────────────────────────────────────────────────────

class TestMatchTool:
    def test_exact(self):
        assert _match_tool("bash", "bash")
        assert not _match_tool("bash", "shell")

    def test_wildcard(self):
        assert _match_tool("*", "anything")

    def test_glob(self):
        assert _match_tool("bash*", "bash_exec")
        assert not _match_tool("bash*", "shell")

    def test_list(self):
        assert _match_tool(["bash", "shell"], "shell")
        assert not _match_tool(["bash", "shell"], "python")


# ── matches() — full rule evaluation ─────────────────────────────────────────

class TestMatches:
    def _rule(self, **kwargs):
        defaults = dict(name="test", action="block")
        return PolicyRule(**{**defaults, **kwargs})

    def test_basic_match(self):
        rule = self._rule(match_tool="bash", match_args={"command": {"contains": "rm -rf"}})
        assert matches(rule, "bash", {"command": "rm -rf /data"}, {})

    def test_wrong_tool(self):
        rule = self._rule(match_tool="bash", match_args={"command": {"contains": "rm -rf"}})
        assert not matches(rule, "shell", {"command": "rm -rf /data"}, {})

    def test_arg_not_matching(self):
        rule = self._rule(match_tool="bash", match_args={"command": {"contains": "rm -rf"}})
        assert not matches(rule, "bash", {"command": "ls -la"}, {})

    def test_any_arg_match(self):
        rule = self._rule(match_tool="*", any_arg={"contains": "password"})
        assert matches(rule, "call_api", {"url": "http://x.com", "body": "password=secret"}, {})

    def test_any_arg_no_match(self):
        rule = self._rule(match_tool="*", any_arg={"contains": "password"})
        assert not matches(rule, "call_api", {"url": "http://x.com", "body": "hello"}, {})

    def test_when_metadata_match(self):
        rule = self._rule(match_tool="bash", when_metadata={"deployment": "prod"})
        assert matches(rule, "bash", {}, {"deployment": "prod"})

    def test_when_metadata_no_match(self):
        rule = self._rule(match_tool="bash", when_metadata={"deployment": "prod"})
        assert not matches(rule, "bash", {}, {"deployment": "staging"})

    def test_when_metadata_missing_key(self):
        rule = self._rule(match_tool="bash", when_metadata={"deployment": "prod"})
        assert not matches(rule, "bash", {}, {})

    def test_no_metadata_filter_applies_globally(self):
        rule = self._rule(match_tool="bash", match_args={"command": {"contains": "rm -rf"}})
        assert matches(rule, "bash", {"command": "rm -rf /"}, {"team": "admin"})
        assert matches(rule, "bash", {"command": "rm -rf /"}, {})


# ── ToolsPolicy ───────────────────────────────────────────────────────────────

class TestToolsPolicy:
    def _policy(self, *rules):
        p = ToolsPolicy()
        p._rules = list(rules)
        return p

    def _rule(self, action="refusal", tool="bash", **match_args):
        return PolicyRule(
            name="test-rule",
            action=action,
            message="blocked by test",
            match_tool=tool,
            match_args=match_args,
        )

    # ── refusal ───────────────────────────────────────────────────────────────

    def test_refusal_replaces_content(self):
        rule   = self._rule(action="refusal", command={"contains": "rm -rf"})
        policy = self._policy(rule)
        response = _response(_tool_use("bash", command="rm -rf /data"))

        result = policy.post({}, response)

        assert result.stop_reason == "end_turn"
        assert len(result.content) == 1
        assert result.content[0].text == "blocked by test"

    def test_refusal_returns_original_on_no_match(self):
        rule   = self._rule(action="refusal", command={"contains": "rm -rf"})
        policy = self._policy(rule)
        response = _response(_tool_use("bash", command="ls -la"))

        assert policy.post({}, response) is response

    def test_refusal_ignores_text_blocks(self):
        rule   = self._rule(action="refusal", command={"contains": "rm -rf"})
        policy = self._policy(rule)
        response = _response(_text_block("some text"))

        assert policy.post({}, response) is response

    # ── interrupt ─────────────────────────────────────────────────────────────

    def test_interrupt_raises_policy_violation(self):
        rule   = self._rule(action="interrupt", command={"contains": "push --force"})
        policy = self._policy(rule)
        response = _response(_tool_use("bash", command="git push --force origin main"))

        with pytest.raises(PolicyViolationError, match="blocked by test"):
            policy.post({}, response)

    # ── warn ──────────────────────────────────────────────────────────────────

    def test_warn_returns_original_response(self):
        rule   = self._rule(action="warn", command={"contains": "curl"})
        policy = self._policy(rule)
        response = _response(_tool_use("bash", command="curl https://example.com"))

        assert policy.post({}, response) is response

    # ── context-aware ─────────────────────────────────────────────────────────

    def test_metadata_scoped_rule_matches(self):
        rule = PolicyRule(
            name="prod-only",
            action="refusal",
            message="not in prod",
            match_tool="bash",
            when_metadata={"deployment": "prod"},
        )
        policy   = self._policy(rule)
        response = _response(_tool_use("bash", command="DROP TABLE users"))

        result = policy.post({"metadata": {"deployment": "prod"}}, response)
        assert result.stop_reason == "end_turn"

    def test_metadata_scoped_rule_skips_other_envs(self):
        rule = PolicyRule(
            name="prod-only",
            action="refusal",
            message="not in prod",
            match_tool="bash",
            when_metadata={"deployment": "prod"},
        )
        policy   = self._policy(rule)
        response = _response(_tool_use("bash", command="DROP TABLE users"))

        result = policy.post({"metadata": {"deployment": "staging"}}, response)
        assert result is response

    # ── lazy load ─────────────────────────────────────────────────────────────

    def test_rules_loaded_lazily(self):
        p = ToolsPolicy()
        assert p._rules is None
        with patch.object(p, "_load_rules", return_value=[]):
            p.post({}, _response())
        assert p._rules == []

    def test_empty_rules_passthrough(self):
        policy   = self._policy()  # no rules
        response = _response(_tool_use("bash", command="rm -rf /"))
        assert policy.post({}, response) is response


# ── Built-in templates ────────────────────────────────────────────────────────

class TestBuiltinTemplates:
    def _policy_for(self, template: str):
        p = ToolsPolicy()
        p._rules = BUILTIN_TEMPLATES[template]
        return p

    def test_filesystem_safety_blocks_rm_rf(self):
        policy   = self._policy_for("filesystem-safety")
        response = _response(_tool_use("bash", command="rm -rf /data"))
        result   = policy.post({}, response)
        assert result.stop_reason == "end_turn"

    def test_filesystem_safety_allows_safe_rm(self):
        policy   = self._policy_for("filesystem-safety")
        response = _response(_tool_use("bash", command="rm file.txt"))
        assert policy.post({}, response) is response

    def test_filesystem_safety_blocks_system_write(self):
        policy   = self._policy_for("filesystem-safety")
        response = _response(_tool_use("write_file", path="/etc/passwd"))
        result   = policy.post({}, response)
        assert result.stop_reason == "end_turn"

    def test_no_privilege_escalation_blocks_sudo(self):
        policy   = self._policy_for("no-privilege-escalation")
        response = _response(_tool_use("bash", command="sudo apt install curl"))
        result   = policy.post({}, response)
        assert result.stop_reason == "end_turn"

    def test_no_privilege_escalation_allows_normal(self):
        policy   = self._policy_for("no-privilege-escalation")
        response = _response(_tool_use("bash", command="python main.py"))
        assert policy.post({}, response) is response

    def test_safe_git_interrupts_force_push(self):
        policy   = self._policy_for("safe-git")
        response = _response(_tool_use("bash", command="git push --force origin main"))
        with pytest.raises(PolicyViolationError):
            policy.post({}, response)


# ── Rule parser ───────────────────────────────────────────────────────────────

class TestParseRule:
    def test_basic(self):
        r = _parse_rule({
            "name": "test",
            "action": "refusal",
            "message": "blocked",
            "match": {"tool": "bash", "command": {"contains": "rm"}},
        })
        assert r.name == "test"
        assert r.action == "refusal"
        assert r.match_tool == "bash"
        assert r.match_args == {"command": {"contains": "rm"}}

    def test_any_arg(self):
        r = _parse_rule({
            "name": "test",
            "action": "warn",
            "match": {"tool": "*", "any_arg": {"startswith": "/Users/"}},
        })
        assert r.any_arg == {"startswith": "/Users/"}
        assert r.match_args == {}

    def test_when_metadata(self):
        r = _parse_rule({
            "name": "no-prod-drop",
            "action": "interrupt",
            "match": {"tool": "execute_sql", "query": {"regex": "(?i)DROP"}},
            "when": {"metadata": {"deployment": "prod"}},
        })
        assert r.match_tool == "execute_sql"
        assert r.when_metadata == {"deployment": "prod"}

    def test_defaults(self):
        r = _parse_rule({})
        assert r.name == "unnamed"
        assert r.action == "warn"
        assert r.match_tool == "*"


# ── ToolsPolicy._load_rules ───────────────────────────────────────────────────

class TestToolsPolicyLoadRules:
    def test_builtin_template_loaded(self):
        policy = ToolsPolicy({"builtin": {"filesystem-safety": True}})
        rules  = policy._load_rules()
        names  = {r.name for r in rules}
        assert "no-recursive-delete" in names
        assert "no-system-path-write" in names

    def test_unknown_builtin_skipped(self):
        policy = ToolsPolicy({"builtin": {"nonexistent-template": True}})
        rules  = policy._load_rules()
        assert rules == []

    def test_custom_rules_parsed(self):
        policy = ToolsPolicy({"rules": [
            {
                "name": "no-prod-drop",
                "action": "interrupt",
                "message": "DROP blocked",
                "match": {"tool": "execute_sql", "query": {"regex": "(?i)DROP"}},
                "when": {"metadata": {"deployment": "prod"}},
            },
        ]})
        rules = policy._load_rules()
        assert len(rules) == 1
        r = rules[0]
        assert r.name == "no-prod-drop"
        assert r.action == "interrupt"
        assert r.match_tool == "execute_sql"
        assert r.when_metadata == {"deployment": "prod"}

    def test_builtin_and_custom_combined(self):
        policy = ToolsPolicy({
            "builtin": {"no-privilege-escalation": True},
            "rules": [{"name": "custom", "action": "warn", "match": {"tool": "bash"}}],
        })
        rules = policy._load_rules()
        names = {r.name for r in rules}
        assert "no-sudo" in names
        assert "custom" in names

    def test_invalid_rule_skipped(self):
        policy = ToolsPolicy({"rules": [
            None,  # bad rule — should be skipped, not crash
        ]})
        # must not raise
        rules = policy._load_rules()
        assert rules == []

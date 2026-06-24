"""
Functional stress tests — correctness under load.

Tests that the rule engine produces correct results with:
- Large rule sets (100+)
- All 14 operators
- Deep dotted paths
- Edge cases (None, empty, missing, type mismatch)
- Large message arrays with PII
"""
import pytest

from aiwarden.policies.custom.operators import match_value
from aiwarden.policies.custom.policy import CustomPolicy
from aiwarden.policies.custom.resolver import evaluate_rule, resolve_field
from aiwarden.policies.custom.schema import parse_rule
from aiwarden.policies.builtin.pii import PIIPolicy
from aiwarden.policies.engine import PolicyEngine

from benchmarks.conftest import (
    generate_complex_rules,
    generate_custom_rules,
    generate_pii_patterns,
    make_pii_request,
    make_request,
)


class TestOperatorCorrectness:
    """All 14 operators with edge cases."""

    def test_contains_basic(self):
        assert match_value("hello world", {"contains": "world"})
        assert not match_value("hello world", {"contains": "xyz"})

    def test_contains_none_value(self):
        assert not match_value(None, {"contains": "anything"})

    def test_contains_numeric(self):
        assert match_value(12345, {"contains": "234"})

    def test_not_contains(self):
        assert match_value("safe content", {"not_contains": "danger"})
        assert not match_value("dangerous content", {"not_contains": "danger"})

    def test_startswith_single(self):
        assert match_value("gpt-4o-mini", {"startswith": "gpt-4"})
        assert not match_value("claude-3", {"startswith": "gpt-4"})

    def test_startswith_list(self):
        assert match_value("gpt-4o", {"startswith": ["gpt-4", "claude-3"]})
        assert match_value("claude-3-5", {"startswith": ["gpt-4", "claude-3"]})
        assert not match_value("llama-2", {"startswith": ["gpt-4", "claude-3"]})

    def test_not_startswith(self):
        assert match_value("claude-3", {"not_startswith": "gpt-4"})
        assert not match_value("gpt-4o", {"not_startswith": "gpt-4"})

    def test_endswith(self):
        assert match_value("file.py", {"endswith": ".py"})
        assert not match_value("file.js", {"endswith": ".py"})

    def test_endswith_list(self):
        assert match_value("file.py", {"endswith": [".py", ".js"]})

    def test_equals(self):
        assert match_value("exact", {"equals": "exact"})
        assert not match_value("EXACT", {"equals": "exact"})

    def test_equals_numeric_as_string(self):
        assert match_value(42, {"equals": "42"})

    def test_not_equals(self):
        assert match_value("a", {"not_equals": "b"})
        assert not match_value("a", {"not_equals": "a"})

    def test_in_operator(self):
        assert match_value("warn", {"in": ["warn", "block", "refusal"]})
        assert not match_value("allow", {"in": ["warn", "block", "refusal"]})

    def test_not_in_operator(self):
        assert match_value("allow", {"not_in": ["warn", "block"]})
        assert not match_value("warn", {"not_in": ["warn", "block"]})

    def test_regex(self):
        assert match_value("EMP-123456", {"regex": r"EMP-\d{6}"})
        assert not match_value("EMP-12", {"regex": r"EMP-\d{6}"})

    def test_regex_none_value(self):
        assert not match_value(None, {"regex": r"\d+"})

    def test_gt(self):
        assert match_value(10, {"gt": 5})
        assert not match_value(5, {"gt": 5})
        assert not match_value(3, {"gt": 5})

    def test_lt(self):
        assert match_value(3, {"lt": 5})
        assert not match_value(5, {"lt": 5})

    def test_gte(self):
        assert match_value(5, {"gte": 5})
        assert match_value(6, {"gte": 5})
        assert not match_value(4, {"gte": 5})

    def test_lte(self):
        assert match_value(5, {"lte": 5})
        assert match_value(4, {"lte": 5})
        assert not match_value(6, {"lte": 5})

    def test_numeric_ops_with_non_numeric(self):
        assert not match_value("abc", {"gt": 5})
        assert not match_value(None, {"lt": 5})

    def test_unknown_operator_fails_safe(self):
        assert not match_value("anything", {"unknown_op": "value"})

    def test_combined_operators_and_logic(self):
        assert match_value("gpt-4o-mini", {"startswith": "gpt", "contains": "4o", "not_contains": "turbo"})
        assert not match_value("gpt-4-turbo", {"startswith": "gpt", "contains": "4", "not_contains": "turbo"})

    def test_empty_string(self):
        assert match_value("", {"equals": ""})
        assert not match_value("", {"contains": "x"})

    def test_empty_matchers(self):
        assert match_value("anything", {})


class TestResolveField:
    """Dotted path resolution edge cases."""

    def test_simple_key(self):
        assert resolve_field({"model": "gpt-4"}, "model") == "gpt-4"

    def test_nested_two_levels(self):
        assert resolve_field({"metadata": {"team": "eng"}}, "metadata.team") == "eng"

    def test_nested_five_levels(self):
        data = {"a": {"b": {"c": {"d": {"e": "deep"}}}}}
        assert resolve_field(data, "a.b.c.d.e") == "deep"

    def test_list_index(self):
        data = {"messages": [{"content": "first"}, {"content": "second"}]}
        assert resolve_field(data, "messages.0.content") == "first"
        assert resolve_field(data, "messages.1.content") == "second"

    def test_missing_key_returns_none(self):
        assert resolve_field({"a": 1}, "b") is None
        assert resolve_field({"a": {"b": 1}}, "a.c") is None

    def test_missing_deep_key(self):
        assert resolve_field({"a": 1}, "a.b.c") is None

    def test_list_out_of_bounds(self):
        data = {"items": [1, 2, 3]}
        assert resolve_field(data, "items.10") is None

    def test_none_intermediate(self):
        data = {"a": None}
        assert resolve_field(data, "a.b") is None

    def test_non_dict_intermediate(self):
        data = {"a": 42}
        assert resolve_field(data, "a.b") is None


class TestLargeRuleSets:
    """Correctness with 100+ rules."""

    def test_100_rules_none_match(self):
        rules = generate_custom_rules(100)
        policy = CustomPolicy({"name": "large-set", "rules": rules})
        request = make_request(content="normal request")
        result, block = policy.pre(request)
        assert block is None

    def test_100_rules_last_matches(self):
        rules = generate_custom_rules(99, action="warn")
        rules.append({
            "name": "matching-rule",
            "hook": "pre",
            "action": "block",
            "message": "This one matches",
            "match": {"model": {"contains": "sonnet"}},
        })
        policy = CustomPolicy({"name": "large-set", "rules": rules})
        request = make_request()
        result, block = policy.pre(request)
        assert block is not None
        assert "This one matches" in block.reason

    def test_100_rules_first_matches_short_circuits(self):
        rules = [{
            "name": "first-rule",
            "hook": "pre",
            "action": "block",
            "message": "First rule blocks",
            "match": {"model": {"contains": "sonnet"}},
        }]
        rules.extend(generate_custom_rules(99, action="block"))
        policy = CustomPolicy({"name": "short-circuit", "rules": rules})
        request = make_request()
        result, block = policy.pre(request)
        assert block is not None
        assert "First rule blocks" in block.reason

    def test_complex_rules_none_match(self):
        rules = generate_complex_rules(50)
        policy = CustomPolicy({"name": "complex-set", "rules": rules})
        request = make_request(metadata={"team": "eng"})
        result, block = policy.pre(request)
        assert block is None

    def test_1000_rules_all_miss(self):
        rules = generate_custom_rules(1000)
        policy = CustomPolicy({"name": "massive-set", "rules": rules})
        request = make_request()
        result, block = policy.pre(request)
        assert block is None


class TestPIIStress:
    """PII policy with large payloads."""

    def test_1kb_message(self):
        policy = PIIPolicy({})
        request = make_pii_request(size_kb=1)
        result, _ = policy.pre(request)
        content = result["messages"][0]["content"]
        assert "[REDACTED:email]" in content
        assert "[REDACTED:phone]" in content
        assert "[REDACTED:ssn]" in content
        assert "[REDACTED:api_key]" in content
        assert "[REDACTED:cc]" in content

    def test_10kb_message(self):
        policy = PIIPolicy({})
        request = make_pii_request(size_kb=10)
        result, _ = policy.pre(request)
        pii_found = result["_pii_found"]
        assert len(pii_found) >= 4

    def test_100kb_message(self):
        policy = PIIPolicy({})
        request = make_pii_request(size_kb=100)
        result, _ = policy.pre(request)
        pii_found = result["_pii_found"]
        assert len(pii_found) >= 4

    def test_100_messages(self):
        policy = PIIPolicy({})
        request = make_pii_request(size_kb=1, num_messages=100)
        result, _ = policy.pre(request)
        pii_found = result["_pii_found"]
        assert len(pii_found) >= 4
        assert len(result["messages"]) == 100

    def test_15_custom_patterns(self):
        patterns = generate_pii_patterns(10)
        policy = PIIPolicy({"patterns": patterns})
        assert len(policy._patterns) == 15  # 5 builtin + 10 custom

    def test_no_pii_in_clean_content(self):
        policy = PIIPolicy({})
        request = {"messages": [{"role": "user", "content": "This is clean text without any PII."}]}
        result, _ = policy.pre(request)
        assert result["_pii_found"] == []
        assert result["messages"][0]["content"] == "This is clean text without any PII."


class TestEngineWithManyPolicies:
    """PolicyEngine correctness with multiple policies."""

    def test_priority_ordering(self):
        engine = PolicyEngine()
        from aiwarden.policies.builtin.pii import PIIPolicy
        from aiwarden.policies.builtin.budget import BudgetPolicy

        p1 = PIIPolicy({})  # priority 90
        p2 = BudgetPolicy({"limit": 1000.0})  # priority 10
        engine._policies = sorted([p1, p2], key=lambda p: p.priority)
        assert engine._policies[0].priority < engine._policies[1].priority

    def test_agent_scoping_skips_non_matching(self):
        from aiwarden.policies.custom.policy import CustomPolicy
        policy = CustomPolicy({
            "name": "scoped",
            "agents": ["chatbot"],
            "rules": [{"name": "r1", "hook": "pre", "action": "block",
                       "match": {"model": {"contains": "sonnet"}}}],
        })
        engine = PolicyEngine()
        engine._policies = [policy]

        request = make_request()
        request["_agent"] = "other-agent"
        _, block, _ = engine.run_pre(request)
        assert block is None

    def test_agent_scoping_matches(self):
        from aiwarden.policies.custom.policy import CustomPolicy
        policy = CustomPolicy({
            "name": "scoped",
            "agents": ["chatbot"],
            "rules": [{"name": "r1", "hook": "pre", "action": "block",
                       "message": "blocked",
                       "match": {"model": {"contains": "sonnet"}}}],
        })
        engine = PolicyEngine()
        engine._policies = [policy]

        request = make_request()
        request["_agent"] = "chatbot"
        _, block, _ = engine.run_pre(request)
        assert block is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

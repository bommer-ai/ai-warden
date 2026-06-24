"""
Tests for the generic CustomPolicy — declarative policy engine.

Covers:
  - Pre-hook rules: model matching, max_tokens numeric, metadata conditions
  - Post-hook rules: response content, token counts, finish reason
  - Schema validation: missing fields, invalid operators, bad types
  - All operators: contains, startswith, regex, equals, in, gt, lt, gte, lte, not_*
  - Priority ordering
  - Latency benchmark
"""
import time
from types import SimpleNamespace

from aiwarden.policies.custom import (
    CustomPolicy,
    CustomRule,
    validate_rule,
    parse_rule,
    resolve_field,
    match_value,
    evaluate_rule,
)
from aiwarden.policies.base import Block, Warn, PolicyViolationError
from aiwarden.policies.engine import PolicyEngine


# ── Schema Validation ────────────────────────────────────────────────────────

def test_validation():
    print("=" * 60)
    print(" TEST: Schema Validation")
    print("=" * 60)

    # Valid rule
    errors = validate_rule({
        "name": "test", "action": "block", "hook": "pre",
        "match": {"model": {"startswith": "gpt"}},
    })
    assert errors == []
    print("  ✅ Valid rule passes validation")

    # Missing name
    errors = validate_rule({"action": "block"})
    assert any("name" in e for e in errors)
    print(f"  ✅ Missing name caught: {errors[0]}")

    # Missing action
    errors = validate_rule({"name": "x"})
    assert any("action" in e for e in errors)
    print(f"  ✅ Missing action caught: {errors[0]}")

    # Invalid action
    errors = validate_rule({"name": "x", "action": "destroy"})
    assert any("invalid action" in e for e in errors)
    print(f"  ✅ Invalid action caught: {errors[0]}")

    # Invalid hook
    errors = validate_rule({"name": "x", "action": "block", "hook": "during"})
    assert any("invalid hook" in e for e in errors)
    print(f"  ✅ Invalid hook caught: {errors[0]}")

    # Unknown operator
    errors = validate_rule({"name": "x", "action": "block", "match": {"model": {"startWith": "gpt"}}})
    assert any("unknown operator" in e for e in errors)
    print(f"  ✅ Unknown operator caught: {errors[0]}")

    # Not a dict
    errors = validate_rule("not a dict")
    assert any("must be a dict" in e for e in errors)
    print(f"  ✅ Non-dict caught: {errors[0]}")

    print()


# ── Field Resolution ─────────────────────────────────────────────────────────

def test_field_resolution():
    print("=" * 60)
    print(" TEST: Field Resolution (dotted paths)")
    print("=" * 60)

    data = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 4096,
        "metadata": {"team": "engineering", "env": "prod"},
        "messages": [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ],
    }

    assert resolve_field(data, "model") == "claude-sonnet-4-6"
    assert resolve_field(data, "max_tokens") == 4096
    assert resolve_field(data, "metadata.team") == "engineering"
    assert resolve_field(data, "metadata.env") == "prod"
    assert resolve_field(data, "messages.0.role") == "user"
    assert resolve_field(data, "messages.1.content") == "Hi!"
    assert resolve_field(data, "nonexistent") is None
    assert resolve_field(data, "metadata.nonexistent") is None

    print("  ✅ All field paths resolve correctly")
    print()


# ── Operators ────────────────────────────────────────────────────────────────

def test_operators():
    print("=" * 60)
    print(" TEST: All Operators")
    print("=" * 60)

    # String operators
    assert match_value("hello world", {"contains": "world"})
    assert not match_value("hello world", {"contains": "xyz"})
    assert match_value("hello world", {"not_contains": "xyz"})
    assert not match_value("hello world", {"not_contains": "world"})
    print("  ✅ contains / not_contains")

    assert match_value("gpt-4-turbo", {"startswith": "gpt"})
    assert not match_value("claude-3", {"startswith": "gpt"})
    assert match_value("claude-3", {"not_startswith": "gpt"})
    print("  ✅ startswith / not_startswith")

    assert match_value("file.txt", {"endswith": ".txt"})
    assert not match_value("file.py", {"endswith": ".txt"})
    print("  ✅ endswith")

    assert match_value("prod", {"equals": "prod"})
    assert not match_value("staging", {"equals": "prod"})
    assert match_value("staging", {"not_equals": "prod"})
    print("  ✅ equals / not_equals")

    assert match_value("prod", {"in": ["prod", "staging"]})
    assert not match_value("dev", {"in": ["prod", "staging"]})
    assert match_value("dev", {"not_in": ["prod", "staging"]})
    print("  ✅ in / not_in")

    assert match_value("sudo rm -rf /", {"regex": r"sudo\s"})
    assert not match_value("ls -la", {"regex": r"sudo\s"})
    print("  ✅ regex")

    # Numeric operators
    assert match_value(5000, {"gt": 4000})
    assert not match_value(3000, {"gt": 4000})
    assert match_value(3000, {"lt": 4000})
    assert not match_value(5000, {"lt": 4000})
    assert match_value(4000, {"gte": 4000})
    assert match_value(4001, {"gte": 4000})
    assert not match_value(3999, {"gte": 4000})
    assert match_value(4000, {"lte": 4000})
    assert not match_value(4001, {"lte": 4000})
    print("  ✅ gt / lt / gte / lte")

    # Multiple operators (AND logic)
    assert match_value("gpt-4-turbo", {"startswith": "gpt", "contains": "turbo"})
    assert not match_value("gpt-4-mini", {"startswith": "gpt", "contains": "turbo"})
    print("  ✅ Multiple operators (AND logic)")

    print()


# ── Pre-hook Rules ───────────────────────────────────────────────────────────

def test_pre_rules():
    print("=" * 60)
    print(" TEST: Pre-hook Rules")
    print("=" * 60)

    policy = CustomPolicy({
        "priority": 20,
        "rules": [
            {
                "name": "no-gpt4-in-prod",
                "hook": "pre",
                "action": "block",
                "message": "GPT-4 not allowed in production",
                "match": {"model": {"startswith": "gpt-4"}},
                "when": {"metadata.environment": "production"},
            },
            {
                "name": "warn-high-tokens",
                "hook": "pre",
                "action": "warn",
                "message": "High token request",
                "match": {"max_tokens": {"gt": 4000}},
            },
            {
                "name": "block-intern-expensive",
                "hook": "pre",
                "action": "block",
                "message": "Interns limited to 2000 tokens",
                "match": {"max_tokens": {"gt": 2000}},
                "when": {"metadata.team": "intern"},
            },
        ],
    })

    # Should block: gpt-4 in production
    req1 = {"model": "gpt-4-turbo", "messages": [], "metadata": {"environment": "production"}}
    result1, action1 = policy.pre(req1)
    assert isinstance(action1, Block)
    assert "GPT-4 not allowed" in action1.reason
    print(f"  ✅ Blocked: gpt-4 in production — '{action1.reason}'")

    # Should pass: gpt-4 in staging (when condition not met)
    req2 = {"model": "gpt-4-turbo", "messages": [], "metadata": {"environment": "staging"}}
    _, action2 = policy.pre(req2)
    assert action2 is None
    print(f"  ✅ Passed: gpt-4 in staging (when condition not met)")

    # Should warn: high tokens
    req3 = {"model": "claude-sonnet-4-6", "messages": [], "max_tokens": 8000, "metadata": {}}
    _, action3 = policy.pre(req3)
    assert isinstance(action3, Warn)
    assert "High token" in action3.reason
    print(f"  ✅ Warned: high tokens — '{action3.reason}'")

    # Should pass: normal request
    req4 = {"model": "claude-sonnet-4-6", "messages": [], "max_tokens": 1000, "metadata": {}}
    _, action4 = policy.pre(req4)
    assert action4 is None
    print(f"  ✅ Passed: normal request (no rules match)")

    # Should block: intern with high tokens
    req5 = {"model": "claude-sonnet-4-6", "messages": [], "max_tokens": 3000, "metadata": {"team": "intern"}}
    _, action5 = policy.pre(req5)
    assert isinstance(action5, Block)
    assert "Interns limited" in action5.reason
    print(f"  ✅ Blocked: intern with 3000 tokens — '{action5.reason}'")

    print()


# ── Post-hook Rules ──────────────────────────────────────────────────────────

def test_post_rules():
    print("=" * 60)
    print(" TEST: Post-hook Rules")
    print("=" * 60)

    policy = CustomPolicy({
        "rules": [
            {
                "name": "block-harmful-content",
                "hook": "post",
                "action": "block",
                "message": "Harmful content detected in response",
                "match": {"response.content": {"regex": "(?i)(how to hack|exploit vulnerability)"}},
            },
            {
                "name": "warn-long-response",
                "hook": "post",
                "action": "warn",
                "message": "Response exceeds 2000 tokens",
                "match": {"response.completion_tokens": {"gt": 2000}},
            },
        ],
    })

    # Anthropic-style response with harmful content → should raise
    harmful_response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="Here's how to hack into a system...")],
        usage=SimpleNamespace(input_tokens=100, output_tokens=50),
        stop_reason="end_turn",
    )
    try:
        policy.post({"messages": [], "metadata": {}}, harmful_response)
        assert False, "Should have raised"
    except PolicyViolationError as e:
        assert "Harmful content" in e.reason
        print(f"  ✅ Blocked harmful response: '{e.reason}'")

    # Safe response → should pass
    safe_response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="Here's a helpful answer about security best practices")],
        usage=SimpleNamespace(input_tokens=100, output_tokens=50),
        stop_reason="end_turn",
    )
    result = policy.post({"messages": [], "metadata": {}}, safe_response)
    assert result is safe_response
    print(f"  ✅ Passed: safe response content")

    # Long response → should warn
    long_response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="Short text")],
        usage=SimpleNamespace(input_tokens=100, output_tokens=3000),
        stop_reason="end_turn",
    )
    result = policy.post({"messages": [], "metadata": {}}, long_response)
    # Warn returns (response, Warn)
    assert isinstance(result, tuple)
    assert isinstance(result[1], Warn)
    assert "2000 tokens" in result[1].reason
    print(f"  ✅ Warned: long response — '{result[1].reason}'")

    # OpenAI-style response → harmful content
    openai_harmful = SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content="Let me explain how to hack the database..."),
            finish_reason="stop",
        )],
        usage=SimpleNamespace(prompt_tokens=50, completion_tokens=100),
    )
    try:
        policy.post({"messages": [], "metadata": {}}, openai_harmful)
        assert False, "Should have raised"
    except PolicyViolationError as e:
        print(f"  ✅ Blocked OpenAI harmful response: '{e.reason}'")

    print()


# ── Priority + Engine Integration ────────────────────────────────────────────

def test_priority_and_engine():
    print("=" * 60)
    print(" TEST: Priority and Engine Integration")
    print("=" * 60)

    # Two rule policies with different priorities
    fast_rules = CustomPolicy({
        "name": "fast-blockers",
        "priority": 10,
        "rules": [
            {"name": "block-gpt4", "hook": "pre", "action": "block",
             "message": "GPT-4 blocked", "match": {"model": {"startswith": "gpt-4"}}},
        ],
    })

    slow_rules = CustomPolicy({
        "name": "content-scan",
        "priority": 90,
        "rules": [
            {"name": "scan-messages", "hook": "pre", "action": "warn",
             "message": "Content scan", "match": {"messages.content": {"contains": "password"}}},
        ],
    })

    engine = PolicyEngine()
    engine._policies = sorted([slow_rules, fast_rules], key=lambda p: p.priority)

    # Fast blocker should fire first (priority 10 before 90)
    req = {"model": "gpt-4", "messages": [{"role": "user", "content": "my password is 123"}], "metadata": {}}
    _, block, fired = engine.run_pre(req)
    assert block is not None
    assert fired[0].name == "fast-blockers"  # engine uses policy.name
    assert "GPT-4 blocked" in fired[0].message
    # slow_rules never ran because fast_rules blocked
    assert len(fired) == 1
    print(f"  ✅ Priority 10 blocks before priority 90 runs")
    print(f"     Fired: {[(f.name, f.message) for f in fired]}")

    # Non-gpt4 model → fast blocker passes, slow scanner fires
    req2 = {"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "my password is 123"}], "metadata": {}}
    _, block2, fired2 = engine.run_pre(req2)
    assert block2 is None  # warn doesn't block
    assert len(fired2) == 1
    assert fired2[0].name == "content-scan"
    assert fired2[0].action == "warn"
    print(f"  ✅ Non-blocking: fast passes, slow warns")
    print(f"     Fired: {[(f.name, f.action) for f in fired2]}")

    print()


# ── Invalid Rules (graceful handling) ────────────────────────────────────────

def test_invalid_rules():
    print("=" * 60)
    print(" TEST: Invalid Rules (graceful handling)")
    print("=" * 60)

    policy = CustomPolicy({
        "rules": [
            None,  # null rule
            {"name": "no-action"},  # missing action
            {"name": "bad-op", "action": "block", "match": {"model": {"unknownOp": "x"}}},  # bad operator
            {"name": "valid", "action": "warn", "message": "OK", "match": {"model": {"equals": "gpt-4"}}},
        ],
    })

    # Only the valid rule should load
    assert len(policy._pre_rules) == 1
    assert policy._pre_rules[0].name == "valid"
    print(f"  ✅ Invalid rules skipped gracefully, valid rule loaded")
    print(f"     Pre-rules: {[r.name for r in policy._pre_rules]}")
    print()


# ── Latency Benchmark ────────────────────────────────────────────────────────

def test_latency():
    print("=" * 60)
    print(" TEST: Latency Benchmark")
    print("=" * 60)

    # 10 pre-rules, 5 post-rules
    policy = CustomPolicy({
        "rules": [
            {"name": f"pre-rule-{i}", "hook": "pre", "action": "warn",
             "message": f"Rule {i}", "match": {"model": {"contains": f"nonexistent-{i}"}}}
            for i in range(10)
        ] + [
            {"name": f"post-rule-{i}", "hook": "post", "action": "warn",
             "message": f"Post {i}", "match": {"response.content": {"contains": f"nonexistent-{i}"}}}
            for i in range(5)
        ],
    })

    request = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": "What is the meaning of life?"}],
        "metadata": {"team": "engineering", "environment": "production"},
    }

    response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="The meaning of life is a philosophical question...")],
        usage=SimpleNamespace(input_tokens=100, output_tokens=200),
        stop_reason="end_turn",
    )

    # Warmup
    for _ in range(100):
        policy.pre(dict(request))
        policy.post(dict(request), response)

    # Benchmark pre
    start = time.perf_counter()
    iterations = 5000
    for _ in range(iterations):
        policy.pre(dict(request))
    pre_elapsed = time.perf_counter() - start
    pre_per_call = (pre_elapsed / iterations) * 1_000_000

    # Benchmark post
    start = time.perf_counter()
    for _ in range(iterations):
        policy.post(dict(request), response)
    post_elapsed = time.perf_counter() - start
    post_per_call = (post_elapsed / iterations) * 1_000_000

    print(f"  Pre-hook  (10 rules): {pre_per_call:.1f}μs/call")
    print(f"  Post-hook  (5 rules): {post_per_call:.1f}μs/call")
    print(f"  Combined:             {pre_per_call + post_per_call:.1f}μs/call")

    assert pre_per_call < 500, f"Pre too slow: {pre_per_call}μs"
    assert post_per_call < 500, f"Post too slow: {post_per_call}μs"
    print(f"  ✅ Both under 500μs budget (LLM calls take 1-5 seconds)")
    print()


# ── Run all ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_validation()
    test_field_resolution()
    test_operators()
    test_pre_rules()
    test_post_rules()
    test_priority_and_engine()
    test_invalid_rules()
    test_latency()

    print("\n" + "=" * 60)
    print(" ALL TESTS PASSED ✅")
    print("=" * 60)

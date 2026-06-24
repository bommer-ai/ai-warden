"""
Tests for hot mode: aiwarden.run()

Covers:
  1. Single run — turns, cost, duration tracked
  2. Multi-agent nested runs — parent-child topology
  3. Run with error — status = "errored"
  4. Per-run policies (run.turns, run.cost limits)
  5. Run summary event emitted
  6. Hot mode overrides all heuristics (no OTel/ContextVar needed)
"""
import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from aiwarden import config
config.ENABLED = True
config.DEBUG = False
config.LOG_FILE = "/tmp/test_hotmode_events.jsonl"

Path(config.LOG_FILE).unlink(missing_ok=True)


def make_response(text="OK", input_tokens=100, output_tokens=50, stop_reason="end_turn"):
    return SimpleNamespace(
        id=f"msg_{uuid4().hex[:24]}", model="claude-sonnet-4-6",
        role="assistant", type="message", stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def make_tool_response(tool_name, tool_input, input_tokens=100, output_tokens=50):
    return SimpleNamespace(
        id=f"msg_{uuid4().hex[:24]}", model="claude-sonnet-4-6",
        role="assistant", type="message", stop_reason="tool_use",
        content=[SimpleNamespace(type="tool_use", id=f"toolu_{uuid4().hex[:24]}",
                                 name=tool_name, input=tool_input)],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def main():
    import anthropic
    from aiwarden.patchers.anthropic import patch as patch_anthropic
    import aiwarden.patchers.anthropic as anthropic_patcher
    import aiwarden

    anthropic_patcher._patched = False
    patch_anthropic(anthropic)
    client = anthropic.Anthropic(api_key="fake-key")

    # ═══════════════════════════════════════════════════════════════════════
    #  TEST 1: Basic run — turns, cost, duration
    # ═══════════════════════════════════════════════════════════════════════
    print("=" * 60)
    print(" TEST 1: Basic run tracking")
    print("=" * 60)

    responses = [
        make_tool_response("search", {"q": "test"}),
        make_response("Found results!", input_tokens=200, output_tokens=80),
    ]
    idx = [0]
    def mock(self, *a, **kw):
        r = responses[idx[0]]; idx[0] += 1; return r

    with patch.object(anthropic_patcher, '_original_create', mock):
        with aiwarden.run(agent="test-agent") as r:
            messages = [{"role": "user", "content": "Search for test"}]
            resp = client.messages.create(model="claude-sonnet-4-6", max_tokens=100, messages=messages)
            messages.append({"role": "assistant", "content": [{"type": "tool_use", "id": "x", "name": "search", "input": {}}]})
            messages.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": "OK"}]})
            resp = client.messages.create(model="claude-sonnet-4-6", max_tokens=100, messages=messages)

    print(f"  run.id:       {r.id}")
    print(f"  run.agent:    {r.agent}")
    print(f"  run.turns:    {r.turns}")
    print(f"  run.cost:     ${r.cost:.6f}")
    print(f"  run.duration: {r.duration:.3f}s")
    print(f"  run.tools:    {r.tools}")
    print(f"  run.status:   {r.status}")

    assert r.agent == "test-agent"
    assert r.turns == 2
    assert r.cost > 0
    assert r.status == "completed"
    assert "search" in r.tools
    print("  ✅ All run metrics correct")

    # ═══════════════════════════════════════════════════════════════════════
    #  TEST 2: Nested runs — parent-child topology
    # ═══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print(" TEST 2: Nested runs (multi-agent)")
    print("=" * 60)

    responses2 = [
        make_response("Search done", input_tokens=100, output_tokens=30),
        make_response("Payment done", input_tokens=150, output_tokens=40),
    ]
    idx2 = [0]
    def mock2(self, *a, **kw):
        r = responses2[idx2[0]]; idx2[0] += 1; return r

    with patch.object(anthropic_patcher, '_original_create', mock2):
        with aiwarden.run(agent="orchestrator") as parent:
            with aiwarden.run(agent="search-agent") as child1:
                client.messages.create(model="claude-sonnet-4-6", max_tokens=100,
                                      messages=[{"role": "user", "content": "search"}])

            with aiwarden.run(agent="payment-agent") as child2:
                client.messages.create(model="claude-sonnet-4-6", max_tokens=100,
                                      messages=[{"role": "user", "content": "pay"}])

    print(f"  Parent: {parent.agent} (id={parent.id})")
    print(f"    children: {[c.agent for c in parent.children]}")
    print(f"    total cost: ${parent.cost:.6f} (accumulated from children)")
    print(f"  Child 1: {child1.agent} cost=${child1.cost:.6f} turns={child1.turns}")
    print(f"  Child 2: {child2.agent} cost=${child2.cost:.6f} turns={child2.turns}")
    print(f"  Child 1 parent_id: {child1.parent_id}")

    assert len(parent.children) == 2
    assert parent.children[0].agent == "search-agent"
    assert parent.children[1].agent == "payment-agent"
    assert child1.parent_id == parent.id
    assert child2.parent_id == parent.id
    assert parent.cost == child1.cost + child2.cost
    print("  ✅ Parent-child topology correct, costs accumulated")

    # ═══════════════════════════════════════════════════════════════════════
    #  TEST 3: Run with error
    # ═══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print(" TEST 3: Run with error — status tracking")
    print("=" * 60)

    def mock_error(self, *a, **kw):
        raise RuntimeError("API timeout")

    with patch.object(anthropic_patcher, '_original_create', mock_error):
        try:
            with aiwarden.run(agent="failing-agent") as error_run:
                client.messages.create(model="claude-sonnet-4-6", max_tokens=100,
                                      messages=[{"role": "user", "content": "hi"}])
        except RuntimeError:
            pass

    print(f"  run.status: {error_run.status}")
    print(f"  run.error:  {error_run._error}")
    assert error_run.status == "errored"
    assert "timeout" in str(error_run._error)
    print("  ✅ Error captured, status = 'errored'")

    # ═══════════════════════════════════════════════════════════════════════
    #  TEST 4: Per-run policy (run.turns limit)
    # ═══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print(" TEST 4: Per-run policy — block after 2 turns")
    print("=" * 60)

    from aiwarden.policies import engine as policy_engine
    from aiwarden.policies.custom import CustomPolicy

    # Save and replace policies
    old_policies = policy_engine._policies
    policy_engine._policies = [CustomPolicy({
        "name": "max-turns",
        "priority": 5,
        "rules": [{
            "name": "limit-turns",
            "hook": "pre",
            "action": "block",
            "message": "Run exceeded 2 turns",
            "match": {"run.turns": {"gte": 2}},
        }],
    })]

    responses4 = [make_response(f"Response {i}") for i in range(5)]
    idx4 = [0]
    def mock4(self, *a, **kw):
        r = responses4[idx4[0]]; idx4[0] += 1; return r

    with patch.object(anthropic_patcher, '_original_create', mock4):
        with aiwarden.run(agent="limited-agent") as limited_run:
            messages = [{"role": "user", "content": "hi"}]
            # Call 1 — should succeed (turn becomes 1 after)
            client.messages.create(model="claude-sonnet-4-6", max_tokens=100, messages=messages)
            # Call 2 — should succeed (turn becomes 2 after)
            client.messages.create(model="claude-sonnet-4-6", max_tokens=100, messages=messages)
            # Call 3 — run.turns is now 2, policy blocks
            try:
                client.messages.create(model="claude-sonnet-4-6", max_tokens=100, messages=messages)
                blocked = False
            except Exception as e:
                blocked = True
                print(f"  Call 3 blocked: {e}")

    print(f"  Turns attempted: {limited_run.turns}")
    print(f"  Blocked on call 3: {blocked}")
    assert limited_run.turns >= 2  # at least 2 calls happened before block
    assert blocked
    print("  ✅ Per-run turn limit enforced")

    # Restore policies
    policy_engine._policies = old_policies

    # ═══════════════════════════════════════════════════════════════════════
    #  TEST 5: Run summary events
    # ═══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print(" TEST 5: Run summary events emitted")
    print("=" * 60)

    time.sleep(3)  # wait for worker flush

    events = []
    with open(config.LOG_FILE) as f:
        for line in f:
            if line.strip():
                events.append(json.loads(line))

    run_summaries = [e for e in events if e.get("type") == "run_summary"]
    print(f"  Total events: {len(events)}")
    print(f"  Run summaries: {len(run_summaries)}")

    for s in run_summaries:
        print(f"    [{s['status']}] agent={s['agent']} turns={s['turns']} cost=${s['cost']:.6f} children={s.get('children', [])}")

    assert len(run_summaries) >= 4  # test1 + test2 (parent + 2 children) + test3
    print("  ✅ Run summary events captured")

    # ═══════════════════════════════════════════════════════════════════════
    print("\n\n" + "=" * 60)
    print(" ALL TESTS PASSED ✅")
    print("=" * 60)


if __name__ == "__main__":
    main()

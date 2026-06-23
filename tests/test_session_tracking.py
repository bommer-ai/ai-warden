"""
Tests run tracking: ContextVar + OTel trace_id signal.

Scenarios:
  1. Single agent run → one run_id, turns increment
  2. Two runs back-to-back (no OTel) → different run_ids
  3. Multi-agent flow (same OTel trace) → SAME run_id for all agents
  4. Sequential requests (different OTel traces) → different run_ids
  5. _run_id override
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
config.LOG_FILE = "/tmp/test_session_events.jsonl"


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_tool_use_response(tool_name, tool_input, input_tokens=100, output_tokens=50):
    return SimpleNamespace(
        id=f"msg_{uuid4().hex[:24]}", model="claude-sonnet-4-6",
        role="assistant", type="message", stop_reason="tool_use",
        content=[SimpleNamespace(type="tool_use", id=f"toolu_{uuid4().hex[:24]}",
                                 name=tool_name, input=tool_input)],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def make_text_response(text, input_tokens=100, output_tokens=30):
    return SimpleNamespace(
        id=f"msg_{uuid4().hex[:24]}", model="claude-sonnet-4-6",
        role="assistant", type="message", stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def run_agent(task, scripted_responses, extra_kwargs=None):
    """Simple agent loop."""
    import anthropic
    client = anthropic.Anthropic(api_key="fake-key")
    messages = [{"role": "user", "content": task}]

    for _ in range(10):
        kwargs = dict(model="claude-sonnet-4-6", max_tokens=4096, messages=messages)
        if extra_kwargs:
            kwargs.update(extra_kwargs)
        response = client.messages.create(**kwargs)

        if response.stop_reason == "end_turn":
            break
        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": [{
                "type": "tool_use", "id": b.id, "name": b.name, "input": b.input
            } for b in response.content if b.type == "tool_use"]})
            messages.append({"role": "user", "content": [{
                "type": "tool_result", "tool_use_id": b.id, "content": f"OK"
            } for b in response.content if b.type == "tool_use"]})


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    Path(config.LOG_FILE).unlink(missing_ok=True)

    import anthropic
    from aiwarden.patchers.anthropic import patch as patch_anthropic
    import aiwarden.patchers.anthropic as anthropic_patcher
    from aiwarden import session

    anthropic_patcher._patched = False
    patch_anthropic(anthropic)

    # ═══════════════════════════════════════════════════════════════════════
    #  TEST 1: Single agent run (no OTel)
    # ═══════════════════════════════════════════════════════════════════════
    print("=" * 65)
    print(" TEST 1: Single agent run — 3 calls, one run_id")
    print("=" * 65)

    session._current_run.set(None)
    session._last_otel_trace.set(None)

    responses = [
        make_tool_use_response("search", {"q": "users"}),
        make_tool_use_response("email", {"to": "users"}),
        make_text_response("Done!"),
    ]
    idx = [0]
    def mock(self, *a, **kw): r = responses[idx[0]]; idx[0] += 1; return r

    with patch.object(anthropic_patcher, '_original_create', mock):
        run_agent("Find users and email them", responses)

    # ═══════════════════════════════════════════════════════════════════════
    #  TEST 2: Second run, different task (no OTel)
    # ═══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 65)
    print(" TEST 2: Second run, different task — new run_id")
    print("=" * 65)

    responses2 = [
        make_tool_use_response("delete", {"path": "x"}),
        make_text_response("Deleted!"),
    ]
    idx2 = [0]
    def mock2(self, *a, **kw): r = responses2[idx2[0]]; idx2[0] += 1; return r

    with patch.object(anthropic_patcher, '_original_create', mock2):
        run_agent("Delete file x", responses2)

    # ═══════════════════════════════════════════════════════════════════════
    #  TEST 3: Multi-agent flow — same OTel trace, two agents
    #  Simulates: Request → Agent A (2 calls) → Agent B (2 calls)
    #  All should share the SAME run_id because same trace
    # ═══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 65)
    print(" TEST 3: Multi-agent flow — same OTel trace")
    print("   Agent A (search) → Agent B (email) — one run_id for both")
    print("=" * 65)

    session._current_run.set(None)
    session._last_otel_trace.set(None)

    trace_for_request = "aaaa1111bbbb2222cccc3333dddd4444"

    # Agent A: searches for data
    responses_a = [
        make_tool_use_response("search_db", {"query": "inactive users"}),
        make_text_response("Found 50 users"),
    ]
    idx_a = [0]
    def mock_a(self, *a, **kw): r = responses_a[idx_a[0]]; idx_a[0] += 1; return r

    with patch.object(anthropic_patcher, '_original_create', mock_a):
        with patch('aiwarden.session._get_otel_trace_id', return_value=trace_for_request):
            run_agent("Find inactive users", responses_a)

    # Agent B: sends emails (SAME trace — part of same request)
    responses_b = [
        make_tool_use_response("send_email", {"count": 50}),
        make_text_response("Sent 50 emails"),
    ]
    idx_b = [0]
    def mock_b(self, *a, **kw): r = responses_b[idx_b[0]]; idx_b[0] += 1; return r

    with patch.object(anthropic_patcher, '_original_create', mock_b):
        with patch('aiwarden.session._get_otel_trace_id', return_value=trace_for_request):
            run_agent("Send re-engagement emails to 50 users", responses_b)

    # ═══════════════════════════════════════════════════════════════════════
    #  TEST 4: New request — different OTel trace → new run_id
    # ═══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 65)
    print(" TEST 4: New request — different OTel trace → new run")
    print("=" * 65)

    new_trace = "ffff9999eeee8888dddd7777cccc6666"

    responses4 = [
        make_tool_use_response("list_files", {"path": "/"}),
        make_text_response("Listed!"),
    ]
    idx4 = [0]
    def mock4(self, *a, **kw): r = responses4[idx4[0]]; idx4[0] += 1; return r

    with patch.object(anthropic_patcher, '_original_create', mock4):
        with patch('aiwarden.session._get_otel_trace_id', return_value=new_trace):
            run_agent("List root files", responses4)

    # ═══════════════════════════════════════════════════════════════════════
    #  TEST 5: _run_id override
    # ═══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 65)
    print(" TEST 5: _run_id override")
    print("=" * 65)

    session._current_run.set(None)
    session._last_otel_trace.set(None)

    responses5 = [
        make_tool_use_response("ping", {"host": "x"}),
        make_text_response("Pong!"),
    ]
    idx5 = [0]
    def mock5(self, *a, **kw): r = responses5[idx5[0]]; idx5[0] += 1; return r

    with patch.object(anthropic_patcher, '_original_create', mock5):
        run_agent("Ping", responses5, extra_kwargs={"_run_id": "custom-run-99"})

    # ═══════════════════════════════════════════════════════════════════════
    #  RESULTS
    # ═══════════════════════════════════════════════════════════════════════
    time.sleep(3)

    print("\n\n" + "=" * 65)
    print(" RESULTS")
    print("=" * 65)

    events = []
    with open(config.LOG_FILE) as f:
        for line in f:
            if line.strip():
                events.append(json.loads(line))

    print(f"\n  Total events: {len(events)}")
    print(f"\n  {'#':<4} {'Run ID':<34} {'Turn':<6} {'Tools':<12} {'Stop'}")
    print(f"  {'─'*4} {'─'*34} {'─'*6} {'─'*12} {'─'*10}")

    for i, e in enumerate(events):
        sid = e.get("run_id", "?")
        turn = e.get("turn", "?")
        tools = [tc["name"] for tc in e.get("tool_calls", [])] or ["(text)"]
        stop = e.get("finish_reason", "?")
        print(f"  {i+1:<4} {sid:<34} {turn:<6} {', '.join(tools):<12} {stop}")

    # ── Verify ───────────────────────────────────────────────────────────

    print(f"\n\n  VERIFICATION:")

    # Test 1: events 1-3, same run_id, turns 1,2,3
    t1 = events[:3]
    t1_ids = set(e["run_id"] for e in t1)
    t1_turns = [e["turn"] for e in t1]
    ok1 = len(t1_ids) == 1 and t1_turns == [1, 2, 3]
    print(f"\n  TEST 1 — Single run: turns={t1_turns} ids={len(t1_ids)}")
    print(f"    {'✅' if ok1 else '❌'} {'Correct' if ok1 else 'FAILED'}")

    # Test 2: events 4-5, different run_id from test 1
    t2 = events[3:5]
    t2_ids = set(e["run_id"] for e in t2)
    ok2 = len(t2_ids) == 1 and t2_ids != t1_ids
    print(f"\n  TEST 2 — New task: different run_id={t2_ids != t1_ids}")
    print(f"    {'✅' if ok2 else '❌'} {'Correct' if ok2 else 'FAILED'}")

    # Test 3: events 6-9 (Agent A: 6,7 + Agent B: 8,9), ALL SAME run_id
    t3 = events[5:9]
    t3_ids = set(e["run_id"] for e in t3)
    t3_turns = [e["turn"] for e in t3]
    ok3 = len(t3_ids) == 1
    print(f"\n  TEST 3 — Multi-agent (same trace): ids={len(t3_ids)} turns={t3_turns}")
    print(f"    Agent A calls: events 6,7")
    print(f"    Agent B calls: events 8,9")
    print(f"    All same run_id: {len(t3_ids) == 1}")
    print(f"    Turns accumulate across agents: {t3_turns}")
    print(f"    {'✅' if ok3 else '❌'} {'Multi-agent flow tracked as ONE run' if ok3 else 'FAILED'}")

    # Test 4: events 10-11, DIFFERENT run_id from test 3
    t4 = events[9:11]
    t4_ids = set(e["run_id"] for e in t4)
    ok4 = len(t4_ids) == 1 and t4_ids != t3_ids
    print(f"\n  TEST 4 — New trace: different run_id={t4_ids != t3_ids}")
    print(f"    {'✅' if ok4 else '❌'} {'Correct' if ok4 else 'FAILED'}")

    # Test 5: events 12-13, run_id = "custom-run-99"
    t5 = events[11:13]
    t5_ids = set(e["run_id"] for e in t5)
    ok5 = t5_ids == {"custom-run-99"}
    print(f"\n  TEST 5 — Override: run_id={t5_ids}")
    print(f"    {'✅' if ok5 else '❌'} {'Correct' if ok5 else 'FAILED'}")

    # ── Summary ──────────────────────────────────────────────────────────
    all_pass = ok1 and ok2 and ok3 and ok4 and ok5
    print(f"\n\n{'═' * 65}")
    if all_pass:
        print(" ALL TESTS PASSED ✅")
    else:
        print(" SOME TESTS FAILED ❌")
    print(f"{'═' * 65}")
    print(f"""
  How it works:
    ContextVar = source of truth (holds RunState with run_id + turn counter)
    OTel trace = change-detection signal

    Same trace?      → keep ContextVar → same run (even across multiple agents)
    Trace changed?   → reset ContextVar → new run
    No OTel?         → turn==0 heuristic (fresh messages = new run)

  This identifies:
    • Single agent calls (one run_id per loop)
    • Multi-agent flows (same run_id for all agents in one request)
    • Sequential requests (different run_ids)
    """)


if __name__ == "__main__":
    main()

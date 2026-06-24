"""
Simulates a FULL agent run — no real API calls.
Shows exactly what ai-warden sees at every step:
  - What the patcher intercepts
  - What policies evaluate
  - What gets captured
  - How session/run tracking works across the loop

Run: python tests/simulate_agent_run.py
"""
import json
import time
from types import SimpleNamespace
from uuid import uuid4

# ── Fake Anthropic response builder ──────────────────────────────────────────

def fake_response(content_blocks, input_tokens, output_tokens, stop_reason="tool_use"):
    """Mimics anthropic.types.Message exactly as the SDK returns it."""
    return SimpleNamespace(
        id=f"msg_{uuid4().hex[:24]}",
        model="claude-sonnet-4-6",
        role="assistant",
        type="message",
        stop_reason=stop_reason,
        content=content_blocks,
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def tool_use_block(name, input_args):
    return SimpleNamespace(
        type="tool_use",
        id=f"toolu_{uuid4().hex[:24]}",
        name=name,
        input=input_args,
    )


def text_block(text):
    return SimpleNamespace(type="text", text=text)


# ── Simulated LLM responses (what the API would return) ─────────────────────

SCRIPTED_RESPONSES = [
    # Turn 0: Model decides to search the database
    fake_response(
        [tool_use_block("search_database", {"query": "customers with no orders in 30 days"})],
        input_tokens=520, output_tokens=85, stop_reason="tool_use",
    ),
    # Turn 1: Model decides to send emails based on search results
    fake_response(
        [tool_use_block("send_email", {"subject": "We miss you!", "count": 47})],
        input_tokens=890, output_tokens=92, stop_reason="tool_use",
    ),
    # Turn 2: Model gives final answer
    fake_response(
        [text_block("Done! I found 47 inactive customers and sent them re-engagement emails with subject 'We miss you!'")],
        input_tokens=1150, output_tokens=38, stop_reason="end_turn",
    ),
]


# ══════════════════════════════════════════════════════════════════════════════
#  SIMULATION — shows what ai-warden sees at each step
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print(" AI-WARDEN: Full Agent Run Simulation")
    print(" Shows exactly what happens inside the patcher on each create() call")
    print("=" * 70)

    # ── Setup (what aiwarden.init() does) ────────────────────────────────────
    # In real usage: import aiwarden; aiwarden.init() patches the SDK.
    # Here we simulate the internals manually.

    from aiwarden.policies.engine import PolicyEngine
    from aiwarden.policies.builtin.budget import BudgetPolicy
    from aiwarden.policies.builtin.pii import PIIPolicy
    from aiwarden.session import get_or_create_session_id, compute_turn
    from aiwarden.cost import compute_cost

    engine = PolicyEngine()
    engine.register(BudgetPolicy({
        "group_by": "metadata.team",
        "limits": {"engineering": 10.00, "default": 1.00},
        "reset": "monthly",
    }))

    # ── Agent state (what the framework manages) ─────────────────────────────
    task = "Find customers who haven't ordered in 30 days and send them a re-engagement email"
    messages = [{"role": "user", "content": task}]
    tools = [
        {"name": "search_database", "description": "Search the database", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}}},
        {"name": "send_email", "description": "Send email", "input_schema": {"type": "object", "properties": {"subject": {"type": "string"}, "count": {"type": "integer"}}}},
    ]

    captured_events = []

    # ── Agent loop ───────────────────────────────────────────────────────────
    for turn_idx, scripted_response in enumerate(SCRIPTED_RESPONSES):

        print(f"\n{'─' * 70}")
        print(f" CREATE() CALL #{turn_idx + 1}")
        print(f"{'─' * 70}")

        # ┌─────────────────────────────────────────────────────────────────┐
        # │ THIS IS WHAT THE PATCHER SEES — the kwargs to create()          │
        # └─────────────────────────────────────────────────────────────────┘

        kwargs = {
            "model": "claude-sonnet-4-6",
            "max_tokens": 4096,
            "messages": messages,
            "tools": tools,
            "metadata": {"team": "engineering", "user_id": "u-anoop"},
        }

        print(f"\n  📤 REQUEST (what patcher intercepts):")
        print(f"     model:    {kwargs['model']}")
        print(f"     messages: {len(kwargs['messages'])} messages")
        print(f"     metadata: {kwargs['metadata']}")
        for i, msg in enumerate(kwargs["messages"]):
            role = msg["role"]
            content = msg["content"]
            if isinstance(content, str):
                preview = content[:80]
            elif isinstance(content, list):
                preview = f"[{len(content)} blocks: {', '.join(b.get('type', '?') if isinstance(b, dict) else getattr(b, 'type', '?') for b in content)}]"
            else:
                preview = str(content)[:80]
            print(f"       [{i}] {role}: {preview}")

        # ┌─────────────────────────────────────────────────────────────────┐
        # │ STEP 1: PRE-HOOKS (budget check, PII redaction, rate limit)     │
        # └─────────────────────────────────────────────────────────────────┘

        print(f"\n  ⚙️  PRE-HOOKS:")
        kwargs, block = engine.run_pre(kwargs)
        if block:
            print(f"     ❌ BLOCKED: {block.reason}")
            return
        print(f"     ✅ Budget check passed (group='engineering')")

        # ┌─────────────────────────────────────────────────────────────────┐
        # │ STEP 2: LLM CALL (simulated — in reality hits the API)          │
        # └─────────────────────────────────────────────────────────────────┘

        start = time.monotonic()
        response = scripted_response  # ← in reality: _original_create(self, **api_kwargs)
        latency = 450 + (turn_idx * 120)  # simulated latency

        print(f"\n  🤖 LLM RESPONSE:")
        print(f"     stop_reason: {response.stop_reason}")
        print(f"     tokens:      input={response.usage.input_tokens} output={response.usage.output_tokens}")
        print(f"     latency:     {latency}ms")
        for block in response.content:
            if block.type == "tool_use":
                print(f"     tool_use:    {block.name}({json.dumps(block.input)})")
                print(f"                  id={block.id}")
            elif block.type == "text":
                print(f"     text:        {block.text[:100]}")

        # ┌─────────────────────────────────────────────────────────────────┐
        # │ STEP 3: POST-HOOKS (tool blocking, cost tracking)               │
        # └─────────────────────────────────────────────────────────────────┘

        print(f"\n  ⚙️  POST-HOOKS:")
        response = engine.run_post(kwargs, response)
        cost = compute_cost("claude-sonnet-4-6", response.usage.input_tokens, response.usage.output_tokens)
        print(f"     ✅ Tool safety check passed")
        print(f"     💰 Cost recorded: ${cost:.6f}")

        # ┌─────────────────────────────────────────────────────────────────┐
        # │ STEP 4: CAPTURE EVENT (what gets logged)                        │
        # └─────────────────────────────────────────────────────────────────┘

        session_id = get_or_create_session_id(messages)
        turn = compute_turn(messages)

        event = {
            "id": uuid4().hex[:16],
            "provider": "anthropic",
            "model": "claude-sonnet-4-6",
            "session_id": session_id,
            "turn": turn,
            "prompt_tokens": response.usage.input_tokens,
            "completion_tokens": response.usage.output_tokens,
            "cost": cost,
            "latency_ms": latency,
            "finish_reason": response.stop_reason,
            "tool_calls": [
                {"name": b.name, "input": b.input, "id": b.id}
                for b in response.content if b.type == "tool_use"
            ],
            "metadata": kwargs.get("metadata", {}),
        }
        captured_events.append(event)

        print(f"\n  📋 CAPTURED EVENT:")
        print(f"     session_id:  {event['session_id']}")
        print(f"     turn:        {event['turn']}")
        print(f"     cost:        ${event['cost']:.6f}")
        print(f"     tool_calls:  {[tc['name'] for tc in event['tool_calls']]}")

        # ┌─────────────────────────────────────────────────────────────────┐
        # │ AGENT FRAMEWORK: append response to messages, execute tools     │
        # └─────────────────────────────────────────────────────────────────┘

        if response.stop_reason == "end_turn":
            print(f"\n  🏁 Agent run complete.")
            break

        # Agent appends assistant response to messages
        messages.append({"role": "assistant", "content": response.content})

        # Agent executes tools and appends results
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                # Simulate tool execution
                if block.name == "search_database":
                    result = "Found 47 inactive customers: [user_1, user_2, ..., user_47]"
                elif block.name == "send_email":
                    result = f"Successfully sent {block.input.get('count', 0)} emails"
                else:
                    result = "OK"

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })
                print(f"\n  🔧 TOOL EXECUTED: {block.name} → {result[:60]}")

        messages.append({"role": "user", "content": tool_results})

    # ── Summary ──────────────────────────────────────────────────────────────

    print(f"\n\n{'═' * 70}")
    print(f" AGENT RUN SUMMARY")
    print(f"{'═' * 70}")
    print(f"\n  Total create() calls:  {len(captured_events)}")
    print(f"  Session ID (all same): {captured_events[0]['session_id']}")
    print(f"  Total cost:            ${sum(e['cost'] for e in captured_events):.6f}")
    print(f"  Total tokens:          {sum(e['prompt_tokens'] + e['completion_tokens'] for e in captured_events)}")
    print(f"\n  Per-call breakdown:")
    for i, e in enumerate(captured_events):
        tools_used = [tc['name'] for tc in e['tool_calls']] or ["(final answer)"]
        print(f"    Call {i+1}: turn={e['turn']}  cost=${e['cost']:.6f}  "
              f"tokens={e['prompt_tokens']}+{e['completion_tokens']}  "
              f"tools={tools_used}  stop={e['finish_reason']}")

    print(f"\n  Budget state after run:")
    budget_policy = engine._policies[0]
    print(f"    engineering: ${budget_policy.get_spend('engineering'):.6f} / $10.00")

    print(f"\n  Messages array at end ({len(messages)} messages):")
    for i, msg in enumerate(messages):
        role = msg["role"]
        content = msg["content"]
        if isinstance(content, str):
            print(f"    [{i}] {role}: {content[:70]}")
        elif isinstance(content, list):
            types = []
            for b in content:
                if isinstance(b, dict):
                    types.append(b.get("type", "?"))
                else:
                    types.append(getattr(b, "type", "?"))
            print(f"    [{i}] {role}: [{', '.join(types)}]")

    # ── What the YAML policy config looks like ───────────────────────────────

    print(f"\n\n{'═' * 70}")
    print(f" USER'S POLICY CONFIG (policies.yaml)")
    print(f"{'═' * 70}")
    print("""
  policies:
    - name: budget-control
      type: budget
      group_by: metadata.team        # ← USER DECIDES what to track by
      limits:
        engineering: 10.00           # ← USER SETS their own thresholds
        default: 1.00
      reset: monthly

  # The user passes metadata.team in their create() calls:
  #   client.messages.create(metadata={"team": "engineering"}, ...)
  #
  # ai-warden reads group_by path → resolves "engineering" → checks limit.
  # That's the mechanism. User brings context, we enforce it.
    """)


if __name__ == "__main__":
    main()

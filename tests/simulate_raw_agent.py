"""
Raw agent run simulation — NO ai-warden.
Shows exactly what goes into create() and what comes back.
This is what any agent looks like at the SDK level.
"""
import json


def main():
    print("=" * 70)
    print(" RAW AGENT RUN — what the SDK sees (no ai-warden)")
    print("=" * 70)

    # ══════════════════════════════════════════════════════════════════════
    #  CALL #1 — Agent sends initial task
    # ══════════════════════════════════════════════════════════════════════

    print("\n\n┌─────────────────────────────────────────────────────────────────┐")
    print("│ client.messages.create() — CALL #1                              │")
    print("└─────────────────────────────────────────────────────────────────┘")

    request_1 = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 4096,
        "system": "You are a customer success agent. Use tools to complete tasks.",
        "messages": [
            {"role": "user", "content": "Find customers who haven't ordered in 30 days and send them a re-engagement email"}
        ],
        "tools": [
            {"name": "search_database", "description": "Search the database", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}}},
            {"name": "send_email", "description": "Send email to customers", "input_schema": {"type": "object", "properties": {"subject": {"type": "string"}, "count": {"type": "integer"}}}},
        ],
        "metadata": {"user_id": "u-anoop-123"},
    }

    print("\n  REQUEST kwargs:")
    print(f"    model:      {request_1['model']}")
    print(f"    max_tokens: {request_1['max_tokens']}")
    print(f"    system:     \"{request_1['system']}\"")
    print(f"    metadata:   {request_1['metadata']}")
    print(f"    tools:      {[t['name'] for t in request_1['tools']]}")
    print(f"    messages:   ({len(request_1['messages'])} messages)")
    print(f"      [0] role=user  content=\"{request_1['messages'][0]['content']}\"")

    # --- API returns ---

    response_1 = {
        "id": "msg_01XFDUDYJgAACzvnptvVoYEL",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-4-6",
        "stop_reason": "tool_use",
        "content": [
            {
                "type": "tool_use",
                "id": "toolu_01A09q90qw90lq917835lBkg",
                "name": "search_database",
                "input": {"query": "customers with no orders in last 30 days"}
            }
        ],
        "usage": {
            "input_tokens": 523,
            "output_tokens": 87,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }
    }

    print("\n  RESPONSE:")
    print(f"    id:          {response_1['id']}")
    print(f"    model:       {response_1['model']}")
    print(f"    stop_reason: {response_1['stop_reason']}")
    print(f"    usage:       input={response_1['usage']['input_tokens']} output={response_1['usage']['output_tokens']}")
    print(f"    content:")
    for block in response_1["content"]:
        print(f"      - type: {block['type']}")
        print(f"        id:   {block['id']}")
        print(f"        name: {block['name']}")
        print(f"        input: {json.dumps(block['input'])}")

    # ══════════════════════════════════════════════════════════════════════
    #  BETWEEN CALLS — Agent executes tool, builds next request
    # ══════════════════════════════════════════════════════════════════════

    print("\n\n  ┄┄┄ Agent executes tool locally ┄┄┄")
    print("  search_database({\"query\": \"customers with no orders in last 30 days\"})")
    print("  → result: \"Found 47 customers: [user_1, user_2, ..., user_47]\"")

    # ══════════════════════════════════════════════════════════════════════
    #  CALL #2 — Agent sends tool result, asks for next step
    # ══════════════════════════════════════════════════════════════════════

    print("\n\n┌─────────────────────────────────────────────────────────────────┐")
    print("│ client.messages.create() — CALL #2                              │")
    print("└─────────────────────────────────────────────────────────────────┘")

    request_2 = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 4096,
        "system": "You are a customer success agent. Use tools to complete tasks.",
        "messages": [
            # ← original user message (STILL HERE)
            {"role": "user", "content": "Find customers who haven't ordered in 30 days and send them a re-engagement email"},
            # ← assistant's tool_use from response #1 (STILL HERE)
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "toolu_01A09q90qw90lq917835lBkg", "name": "search_database", "input": {"query": "customers with no orders in last 30 days"}}
            ]},
            # ← tool result appended by agent framework
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_01A09q90qw90lq917835lBkg", "content": "Found 47 customers: [user_1, user_2, ..., user_47]"}
            ]},
        ],
        "tools": [
            {"name": "search_database", "description": "Search the database", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}}},
            {"name": "send_email", "description": "Send email to customers", "input_schema": {"type": "object", "properties": {"subject": {"type": "string"}, "count": {"type": "integer"}}}},
        ],
        "metadata": {"user_id": "u-anoop-123"},
    }

    print("\n  REQUEST kwargs:")
    print(f"    model:      {request_2['model']}")
    print(f"    max_tokens: {request_2['max_tokens']}")
    print(f"    system:     \"{request_2['system']}\"")
    print(f"    metadata:   {request_2['metadata']}")
    print(f"    tools:      {[t['name'] for t in request_2['tools']]}")
    print(f"    messages:   ({len(request_2['messages'])} messages)  ← GREW from 1 to 3")
    print(f"      [0] role=user       content=\"Find customers who haven't...\"")
    print(f"      [1] role=assistant  content=[tool_use: search_database]")
    print(f"      [2] role=user       content=[tool_result: \"Found 47 customers...\"]")

    # --- API returns ---

    response_2 = {
        "id": "msg_01YKEvmB8rFG3TGcXz9qHNaW",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-4-6",
        "stop_reason": "tool_use",
        "content": [
            {
                "type": "tool_use",
                "id": "toolu_01B82mGVHz8kQ5pLx93R4dnV",
                "name": "send_email",
                "input": {"subject": "We miss you! Here's 15% off your next order", "count": 47}
            }
        ],
        "usage": {
            "input_tokens": 891,
            "output_tokens": 94,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }
    }

    print("\n  RESPONSE:")
    print(f"    id:          {response_2['id']}")
    print(f"    stop_reason: {response_2['stop_reason']}")
    print(f"    usage:       input={response_2['usage']['input_tokens']} output={response_2['usage']['output_tokens']}")
    print(f"    content:")
    for block in response_2["content"]:
        print(f"      - type: {block['type']}")
        print(f"        id:   {block['id']}")
        print(f"        name: {block['name']}")
        print(f"        input: {json.dumps(block['input'])}")

    # ══════════════════════════════════════════════════════════════════════
    #  BETWEEN CALLS — Agent executes tool
    # ══════════════════════════════════════════════════════════════════════

    print("\n\n  ┄┄┄ Agent executes tool locally ┄┄┄")
    print("  send_email({\"subject\": \"We miss you!...\", \"count\": 47})")
    print("  → result: \"Successfully sent 47 emails\"")

    # ══════════════════════════════════════════════════════════════════════
    #  CALL #3 — Agent sends second tool result
    # ══════════════════════════════════════════════════════════════════════

    print("\n\n┌─────────────────────────────────────────────────────────────────┐")
    print("│ client.messages.create() — CALL #3                              │")
    print("└─────────────────────────────────────────────────────────────────┘")

    request_3 = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 4096,
        "system": "You are a customer success agent. Use tools to complete tasks.",
        "messages": [
            # ← ALL previous messages still here
            {"role": "user", "content": "Find customers who haven't ordered in 30 days and send them a re-engagement email"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "toolu_01A09q90qw90lq917835lBkg", "name": "search_database", "input": {"query": "customers with no orders in last 30 days"}}
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_01A09q90qw90lq917835lBkg", "content": "Found 47 customers: [user_1, user_2, ..., user_47]"}
            ]},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "toolu_01B82mGVHz8kQ5pLx93R4dnV", "name": "send_email", "input": {"subject": "We miss you! Here's 15% off your next order", "count": 47}}
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_01B82mGVHz8kQ5pLx93R4dnV", "content": "Successfully sent 47 emails"}
            ]},
        ],
        "tools": [
            {"name": "search_database", "description": "Search the database", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}}},
            {"name": "send_email", "description": "Send email to customers", "input_schema": {"type": "object", "properties": {"subject": {"type": "string"}, "count": {"type": "integer"}}}},
        ],
        "metadata": {"user_id": "u-anoop-123"},
    }

    print("\n  REQUEST kwargs:")
    print(f"    model:      {request_3['model']}")
    print(f"    max_tokens: {request_3['max_tokens']}")
    print(f"    system:     \"{request_3['system']}\"")
    print(f"    metadata:   {request_3['metadata']}")
    print(f"    tools:      {[t['name'] for t in request_3['tools']]}")
    print(f"    messages:   ({len(request_3['messages'])} messages)  ← GREW from 3 to 5")
    print(f"      [0] role=user       content=\"Find customers who haven't...\"")
    print(f"      [1] role=assistant  content=[tool_use: search_database]")
    print(f"      [2] role=user       content=[tool_result: \"Found 47...\"]")
    print(f"      [3] role=assistant  content=[tool_use: send_email]")
    print(f"      [4] role=user       content=[tool_result: \"Successfully sent 47...\"]")

    # --- API returns ---

    response_3 = {
        "id": "msg_01ZPLmNqKJ7vGtEb5sXR9hCW",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-4-6",
        "stop_reason": "end_turn",
        "content": [
            {
                "type": "text",
                "text": "Done! I found 47 customers who haven't ordered in 30 days and sent them a re-engagement email with subject 'We miss you! Here's 15% off your next order'."
            }
        ],
        "usage": {
            "input_tokens": 1152,
            "output_tokens": 41,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }
    }

    print("\n  RESPONSE:")
    print(f"    id:          {response_3['id']}")
    print(f"    stop_reason: {response_3['stop_reason']}  ← DONE, no more tool calls")
    print(f"    usage:       input={response_3['usage']['input_tokens']} output={response_3['usage']['output_tokens']}")
    print(f"    content:")
    for block in response_3["content"]:
        print(f"      - type: {block['type']}")
        print(f"        text: \"{block['text']}\"")

    # ══════════════════════════════════════════════════════════════════════
    #  ANALYSIS — what do we GET and what do we NOT GET
    # ══════════════════════════════════════════════════════════════════════

    print("\n\n" + "=" * 70)
    print(" WHAT WE GET vs WHAT WE DON'T")
    print("=" * 70)

    print("""
  ✅ WHAT WE GET (on every create() call):
  ─────────────────────────────────────────
    • model                    → "claude-sonnet-4-6"
    • messages array           → full history, grows each call
    • tools list               → what the agent can use
    • system prompt            → agent's identity/instructions
    • metadata                 → whatever user passes (user_id, team, etc.)
    • max_tokens               → token limit

  ✅ WHAT WE GET (in every response):
  ─────────────────────────────────────────
    • response.id              → unique per response (msg_01XFD...)
    • response.stop_reason     → "tool_use" or "end_turn"
    • response.content         → tool_use blocks with id, name, input
    • response.usage           → input_tokens, output_tokens
    • response.model           → model used

  ❌ WHAT WE DON'T GET:
  ─────────────────────────────────────────
    • session_id / run_id      → DOES NOT EXIST in protocol
    • turn number              → NOT provided (we compute from messages)
    • total cost so far        → NOT tracked (we must accumulate)
    • who started this run     → NOT in protocol (only if user passes metadata)
    • is this a continuation   → NOT explicit (must infer from messages)
    • time elapsed since start → NOT tracked
    • which call # this is     → NOT provided

  🔍 WHAT WE CAN INFER:
  ─────────────────────────────────────────
    • Same run?        → messages grow (call N is superset of call N-1)
    • Turn number?     → count assistant messages in the array
    • First call?      → no assistant messages = first call
    • Still looping?   → stop_reason == "tool_use"
    • Run finished?    → stop_reason == "end_turn"
    • Tools used?      → tool_use blocks in messages history
    • Run ID?          → first tool_use.id in messages (stable anchor)
                         OR ContextVar set on first call
    """)

    print("=" * 70)
    print(" KEY INSIGHT")
    print("=" * 70)
    print("""
  The messages array IS the run state. It contains:
    - The original task (messages[0])
    - Every tool call made (tool_use blocks with unique IDs)
    - Every tool result
    - The full history

  But there's NO protocol-level "run_id". The API is stateless.
  Each create() is independent. Only messages carry continuity.

  For ai-warden, the ContextVar approach works because:
    - The agent loop runs in ONE thread
    - Every create() in the loop hits our patcher in the same thread
    - We set a UUID on the first call, read it on subsequent calls
    - The loop is sequential (must wait for response before next call)
    """)


if __name__ == "__main__":
    main()

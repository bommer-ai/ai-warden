"""
Simulates an agent loop — multi-turn, all turns share the same session_id.
Uses real Anthropic API via LiteLLM proxy.
"""
import os

import anthropic


# ── agent loop (zero aiwarden imports) ───────────────────────────────────

def run_agent(task: str) -> str:
    """
    Simple agent loop using Anthropic directly.
    No aiwarden imports. Zero code changes.
    """
    # Use auth_token= when going through a proxy (sends Authorization: Bearer)
    # This matches how aws-health-agent authenticates to LiteLLM
    api_key  = os.getenv("ANTHROPIC_API_KEY", "")
    base_url = os.getenv("ANTHROPIC_BASE_URL", "")

    client_kwargs: dict = {}
    if base_url:
        client_kwargs["base_url"] = base_url
        if api_key:
            client_kwargs["auth_token"] = api_key
    elif api_key:
        client_kwargs["api_key"] = api_key

    client = anthropic.Anthropic(**client_kwargs)

    tools = [
        {
            "name":        "search_database",
            "description": "Search the database for records",
            "input_schema": {
                "type":       "object",
                "properties": {"query": {"type": "string"}},
                "required":   ["query"],
            },
        },
        {
            "name":        "send_email",
            "description": "Send an email to a list of users",
            "input_schema": {
                "type":       "object",
                "properties": {
                    "subject": {"type": "string"},
                    "count":   {"type": "integer"},
                },
                "required": ["subject", "count"],
            },
        },
    ]

    messages = [{"role": "user", "content": task}]

    print(f"\nTask: {task}")
    print("-" * 50)

    model = os.getenv("ANTHROPIC_DEFAULT_HAIKU_MODEL", "claude-3-5-haiku-20241022")

    for turn in range(5):   # max 5 turns safety limit
        response = client.messages.create(
            model      = model,
            max_tokens = 1024,
            tools      = tools,
            messages   = messages,
        )

        print(f"\nTurn {turn}: stop_reason={response.stop_reason}")

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    return block.text
            return "Done"

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    print(f"  tool: {block.name}({block.input})")

                    if block.name == "search_database":
                        result = "Found 47 inactive customers: [user_1, user_2, ...]"
                    elif block.name == "send_email":
                        result = f"Successfully sent {block.input.get('count', 0)} emails"
                    else:
                        result = "OK"

                    tool_results.append({
                        "type":        "tool_result",
                        "tool_use_id": block.id,
                        "content":     result,
                    })

            messages.append({"role": "user", "content": tool_results})

    return "Max turns reached"


# ── run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "="*60)
    print("AGENT LOOP — real Anthropic API via LiteLLM proxy")
    print("All turns must share the same session_id in captured events")
    print("="*60)

    result = run_agent(
        "Find customers who haven't ordered in 30 days and send them a re-engagement email"
    )

    print(f"\nFinal result: {result}")

    from aiwarden.capture import flush
    flush()
    print("\nDone. Check session_id is identical across all turns above.")

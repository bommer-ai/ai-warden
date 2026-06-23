"""
Runs 3 independent agent tasks concurrently using threads.
Each task gets its own session_id. All turns within a task share the same session_id.
Zero aiwarden imports — zero code changes.
"""
import os
import threading

import anthropic


def make_client() -> anthropic.Anthropic:
    api_key  = os.getenv("ANTHROPIC_API_KEY", "")
    base_url = os.getenv("ANTHROPIC_BASE_URL", "")
    if base_url:
        return anthropic.Anthropic(base_url=base_url, auth_token=api_key) if api_key \
               else anthropic.Anthropic(base_url=base_url)
    return anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()


TOOLS = [
    {
        "name": "query_db",
        "description": "Run a SQL query and return results",
        "input_schema": {
            "type": "object",
            "properties": {"sql": {"type": "string"}},
            "required": ["sql"],
        },
    },
    {
        "name": "send_slack",
        "description": "Send a message to a Slack channel",
        "input_schema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string"},
                "message": {"type": "string"},
            },
            "required": ["channel", "message"],
        },
    },
    {
        "name": "create_ticket",
        "description": "Create a support ticket",
        "input_schema": {
            "type": "object",
            "properties": {
                "title":    {"type": "string"},
                "priority": {"type": "string", "enum": ["low", "medium", "high"]},
                "body":     {"type": "string"},
            },
            "required": ["title", "priority", "body"],
        },
    },
]


def run_agent(task: str, label: str) -> str:
    """Agent loop — no aiwarden code, zero code changes."""
    client   = make_client()
    model    = os.getenv("ANTHROPIC_DEFAULT_HAIKU_MODEL", "claude-3-5-haiku-20241022")
    messages = [{"role": "user", "content": task}]

    print(f"\n[{label}] Starting: {task[:60]}...")

    for turn in range(6):
        response = client.messages.create(
            model      = model,
            max_tokens = 1024,
            tools      = TOOLS,
            messages   = messages,
        )

        print(f"[{label}] Turn {turn}: {response.stop_reason}")

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
                    print(f"  [{label}] → {block.name}({list(block.input.keys())})")

                    # simulated tool responses
                    if block.name == "query_db":
                        result = "Rows: [{id:1,val:42},{id:2,val:17},{id:3,val:99}]"
                    elif block.name == "send_slack":
                        result = f"Message posted to {block.input.get('channel','?')}"
                    elif block.name == "create_ticket":
                        result = f"Ticket TKT-{hash(block.input.get('title',''))%10000:04d} created"
                    else:
                        result = "OK"

                    tool_results.append({
                        "type":        "tool_result",
                        "tool_use_id": block.id,
                        "content":     result,
                    })

            messages.append({"role": "user", "content": tool_results})

    return "Max turns reached"


# ── tasks ─────────────────────────────────────────────────────────────────────

TASKS = [
    (
        "Agent-A",
        "Query the database for top 3 products by sales this month, "
        "then post a summary to the #sales Slack channel.",
    ),
    (
        "Agent-B",
        "Check the database for any orders stuck in 'pending' status for over 48 hours, "
        "then create a high-priority support ticket for each one you find.",
    ),
    (
        "Agent-C",
        "Query the database for users who signed up this week but haven't completed onboarding, "
        "then send a reminder message to the #onboarding Slack channel with the count.",
    ),
]


if __name__ == "__main__":
    print("\n" + "=" * 65)
    print("MULTI-AGENT TEST — 3 concurrent agents, real API, real patcher")
    print("Each agent gets its own session_id.")
    print("Turns within each agent must share the same session_id.")
    print("=" * 65)

    results = {}
    threads = []

    def _run(label, task):
        results[label] = run_agent(task, label)

    for label, task in TASKS:
        t = threading.Thread(target=_run, args=(label, task), name=label)
        threads.append(t)

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    print("\n" + "=" * 65)
    print("RESULTS")
    print("=" * 65)
    for label, _ in TASKS:
        print(f"\n[{label}]\n{results.get(label, 'N/A')[:200]}")

    print("\n" + "=" * 65)
    print("CAPTURED EVENTS (flush)")
    print("=" * 65)
    from aiwarden.capture import flush
    flush()

    print("\nDone. Each agent should have its own session_id.")
    print("All turns within each agent must share that session_id.")

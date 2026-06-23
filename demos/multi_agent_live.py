"""
LIVE DEMO: Multi-agent policy enforcement with real API calls.

Runs two different agents with different policy scopes:
  - "chatbot" agent: allowed to chat freely, $0.05 budget
  - "file-agent" agent: restricted tools, no filesystem writes

Shows:
  1. Per-agent policy scoping (different rules for different agents)
  2. Budget enforcement (chatbot gets blocked when budget exceeded)
  3. Tool safety (file-agent blocked from writing)
  4. PII redaction (global — applies to all agents)
  5. Custom rules (per-agent declarative guards)
  6. Session tracking (each agent gets its own run_id)
  7. Event capture (all calls logged with policy_fired info)

Uses real Anthropic API via LiteLLM proxy.
"""
import json
import os
import time
from pathlib import Path

# ── Configure ai-warden BEFORE any patching ─────────────────────────────────

from aiwarden import config
config.configure(enabled=True, debug=True, log_file="/tmp/demo_events.jsonl")
Path("/tmp/demo_events.jsonl").unlink(missing_ok=True)

# ── Set up policies programmatically (simulates what YAML loading does) ──────

from aiwarden.policies import engine
from aiwarden.policies.builtin.budget import BudgetPolicy
from aiwarden.policies.builtin.pii import PIIPolicy
from aiwarden.policies.builtin.tools import ToolsPolicy
from aiwarden.policies.custom import CustomPolicy

# Reset engine for clean demo
engine._policies = []

# 1. Global PII protection (applies to ALL agents)
engine.register(PIIPolicy({
    "priority": 90,
    "patterns": {
        "employee_id": r"\bEMP-\d{6}\b",
    },
}))

# 2. Chatbot budget: $0.001 (extremely tight — will block on 2nd call)
engine.register(BudgetPolicy({
    "name": "chatbot-budget",
    "priority": 10,
    "agents": ["chatbot"],
    "limit": 0.001,
    "reset": "daily",
}))

# 3. File agent budget: $0.10
engine.register(BudgetPolicy({
    "name": "file-agent-budget",
    "priority": 10,
    "agents": ["file-agent"],
    "limit": 0.10,
    "reset": "daily",
}))

# 4. File agent: block filesystem write tools
engine.register(ToolsPolicy({
    "name": "file-agent-safety",
    "priority": 50,
    "agents": ["file-agent"],
    "builtin": {"filesystem-safety": True, "no-privilege-escalation": True},
    "rules": [
        {
            "name": "no-write-tools",
            "action": "refusal",
            "message": "File agent is read-only — writing is not allowed.",
            "match": {"tool": ["write_file", "create_file", "delete_file"]},
        },
    ],
}))

# 5. Custom rule: chatbot can't discuss competitors
engine.register(CustomPolicy({
    "name": "chatbot-content-guard",
    "priority": 20,
    "agents": ["chatbot"],
    "rules": [
        {
            "name": "no-competitor-discussion",
            "hook": "pre",
            "action": "warn",
            "message": "User asking about competitors",
            "match": {
                "messages.content": {"regex": "(?i)(chatgpt|openai|gemini|competitor)"},
            },
        },
    ],
}))

print("=" * 70)
print(" AI-WARDEN LIVE DEMO: Multi-Agent Policy Enforcement")
print("=" * 70)
print(f"\n  Policies loaded: {len(engine._policies)}")
for p in engine._policies:
    scope = f"agents={p.agents}" if p.agents else "GLOBAL"
    print(f"    [{p.priority:>3}] {p.name:<25} {scope}")

# ── Patch Anthropic SDK ──────────────────────────────────────────────────────

import anthropic
from aiwarden.patchers.anthropic import patch
patch(anthropic)

# ── Create client ────────────────────────────────────────────────────────────

client_kwargs = {}
base_url = os.getenv("ANTHROPIC_BASE_URL", "")
api_key = os.getenv("ANTHROPIC_API_KEY", "")

if base_url:
    client_kwargs["base_url"] = base_url
    if api_key:
        client_kwargs["auth_token"] = api_key
elif api_key:
    client_kwargs["api_key"] = api_key

client = anthropic.Anthropic(**client_kwargs)
model = os.getenv("ANTHROPIC_DEFAULT_HAIKU_MODEL", "claude-haiku-4-5-20251001")


# ── Helper: run a simple agent ───────────────────────────────────────────────

def run_agent(agent_name: str, task: str, tools: list = None, max_turns: int = 3):
    """Run an agent loop with policy enforcement."""
    print(f"\n{'─' * 70}")
    print(f"  AGENT: {agent_name}")
    print(f"  TASK:  {task}")
    print(f"{'─' * 70}")

    messages = [{"role": "user", "content": task}]

    for turn in range(max_turns):
        try:
            kwargs = {
                "model": model,
                "max_tokens": 512,
                "messages": messages,
                "_agent": agent_name,
            }
            if tools:
                kwargs["tools"] = tools

            response = client.messages.create(**kwargs)

            print(f"\n  Turn {turn + 1}: stop_reason={response.stop_reason}")
            for block in response.content:
                if hasattr(block, "text"):
                    print(f"    Response: {block.text[:120]}")
                elif hasattr(block, "name"):
                    print(f"    Tool call: {block.name}({block.input})")

            if response.stop_reason == "end_turn":
                break

            if response.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": response.content})
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": f"Executed {block.name} successfully.",
                        })
                messages.append({"role": "user", "content": tool_results})

        except Exception as e:
            print(f"\n  ❌ BLOCKED: {e}")
            break

    print()


# ── SCENARIO 1: Chatbot with PII in user message ────────────────────────────

print("\n\n" + "=" * 70)
print(" SCENARIO 1: Chatbot — PII gets redacted before reaching LLM")
print("=" * 70)

run_agent(
    agent_name="chatbot",
    task="My employee ID is EMP-123456 and my email is anoop@company.com. What benefits do I have?",
)

# ── SCENARIO 2: Chatbot asking about competitors (custom rule warns) ─────────

print("\n" + "=" * 70)
print(" SCENARIO 2: Chatbot — custom rule warns on competitor mention")
print("=" * 70)

run_agent(
    agent_name="chatbot",
    task="How does your product compare to ChatGPT and OpenAI?",
)

# ── SCENARIO 3: File agent with tools (read allowed, write blocked) ──────────

print("\n" + "=" * 70)
print(" SCENARIO 3: File agent — read tools allowed, write tools blocked")
print("=" * 70)

file_tools = [
    {
        "name": "read_file",
        "description": "Read contents of a file",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    },
    {
        "name": "write_file",
        "description": "Write contents to a file",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
    },
    {
        "name": "list_files",
        "description": "List files in a directory",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    },
]

run_agent(
    agent_name="file-agent",
    task="List files in /tmp, then create a new file called /tmp/test.txt with content 'hello'",
    tools=file_tools,
)

# ── SCENARIO 4: Chatbot burns through budget ────────────────────────────────

print("\n" + "=" * 70)
print(" SCENARIO 4: Chatbot — budget enforcement (will hit $0.05 limit)")
print("=" * 70)

for i in range(5):
    print(f"\n  --- Call {i+1} ---")
    run_agent(
        agent_name="chatbot",
        task=f"Tell me a one-sentence fact about the number {i+1}.",
        max_turns=1,
    )

# ── Show captured events ─────────────────────────────────────────────────────

time.sleep(3)  # wait for worker flush

print("\n\n" + "=" * 70)
print(" CAPTURED EVENTS SUMMARY")
print("=" * 70)

events = []
with open("/tmp/demo_events.jsonl") as f:
    for line in f:
        if line.strip():
            events.append(json.loads(line))

print(f"\n  Total events: {len(events)}")
print(f"\n  {'#':<4} {'Run ID':<18} {'Turn':<5} {'Agent':<12} {'Policy':<8} {'Cost':<10} {'Model'}")
print(f"  {'─'*4} {'─'*18} {'─'*5} {'─'*12} {'─'*8} {'─'*10} {'─'*20}")

for i, e in enumerate(events):
    run_id = e.get("run_id", "?")[:16]
    turn = e.get("turn", 0)
    # derive agent from custom_fields
    agent = e.get("custom_fields", {}).get("_agent", "—")
    policy = "FIRED" if e.get("policy_fired") else "—"
    if e.get("policy_blocked"):
        policy = "BLOCKED"
    cost = f"${e.get('cost', 0):.5f}"
    model_name = e.get("model", "?")
    print(f"  {i+1:<4} {run_id:<18} {turn:<5} {agent:<12} {policy:<8} {cost:<10} {model_name}")

# Budget state
print(f"\n  Budget state:")
for p in engine._policies:
    if hasattr(p, "get_all_spend"):
        spend = p.get_all_spend()
        if spend:
            print(f"    {p.name}: {spend}")

# Policies that fired
fired_events = [e for e in events if e.get("policy_fired")]
print(f"\n  Events where policies fired: {len(fired_events)}")
for e in fired_events:
    for p in e.get("policies", []):
        print(f"    [{p.get('action')}] {p.get('name')}: {p.get('message', '')[:60]}")

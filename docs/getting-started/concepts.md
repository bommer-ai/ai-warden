# Core Concepts

## Runs

A **run** is a complete agent execution — one task, start to finish, potentially many LLM calls.

```
Run: "Book a flight to NYC"
  ├── create() → tool_use: search_flights     turn 1
  ├── create() → tool_use: book_flight        turn 2
  └── create() → text: "Done! Booked."        turn 3
```

ai-warden auto-detects runs using:

1. **OpenTelemetry trace** (production) — same trace = same run
2. **ContextVar heuristic** (dev) — fresh messages = new run

Or set explicitly: `with aiwarden.agent("chatbot"):` or env var `AIWARDEN_AGENT_NAME`.

---

## Policies

Policies intercept LLM calls at two points:

```
         PRE-HOOKS                    POST-HOOKS
    ┌─────────────────┐         ┌─────────────────┐
    │ Budget check    │         │ Tool blocking   │
    │ Rate limit      │         │ Output filter   │
    │ PII redaction   │         │ Cost recording  │
    └────────┬────────┘         └────────┬────────┘
             │                           │
             ▼                           ▼
        LLM API call ──────────────► Response
```

**Pre-hooks** can block the request or modify it (PII redaction).  
**Post-hooks** can modify the response or raise an error (tool blocking).

---

## Policy types

| Type | What it does | Stateful? |
|------|-------------|-----------|
| `budget` | Track spend, block when exceeded | Yes (accumulates across calls) |
| `pii` | Redact sensitive data before LLM sees it | No (per-call scan) |
| `tools` | Block dangerous tool calls in responses | No (per-call check) |
| `custom` | Your rules: match any field, block or warn | No (declarative conditions) |
| `module` | Your Python code for complex logic | You decide |

---

## Agents

Different agents can have different policies:

```yaml
policies:
  - name: chatbot-budget
    type: budget
    agents: ["chatbot"]          # ← only applies to chatbot
    limit: 50.00

  - name: payment-safety
    type: tools
    agents: ["payment-bot"]      # ← only applies to payment bot

  - name: global-pii
    type: pii                    # ← no agents field = applies to ALL
```

Set the agent name:

```python
# Option A: context manager (recommended)
with aiwarden.agent("chatbot"):
    response = client.messages.create(...)

# Option B: env var (single-agent deployments)
# export AIWARDEN_AGENT_NAME=chatbot

# Option C: startup config
aiwarden.configure(agent_name="chatbot")
```

---

## Events

Every LLM call produces an event (non-blocking, background thread):

```json
{
  "run_id": "a0e3bd0e38974983",
  "turn": 1,
  "provider": "anthropic",
  "model": "claude-sonnet-4-6",
  "cost": 0.000862,
  "latency_ms": 1423,
  "policy_fired": true,
  "policy_blocked": false,
  "policies": [{"name": "content-guard", "action": "warn", "message": "..."}]
}
```

Events are written to JSONL. Use them for dashboards, alerts, compliance audits.

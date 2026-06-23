# Core Concepts

ai-warden has four core concepts: **policies**, **agents**, **runs**, and **events**. Understanding how they connect gives you full control over your LLM governance.

---

## Interception model

ai-warden patches the Anthropic and OpenAI SDKs at the class level. Every instance of `Anthropic()` or `OpenAI()` created in your process is covered — no opt-in needed.

```
Your Code
    │
    ▼
client.messages.create(**kwargs)
    │
    ├─── ai-warden intercepts ───┐
    │                            │
    │    ┌─ PRE-HOOKS ─┐        │
    │    │ Budget       │        │
    │    │ Agent Ctrl   │        │
    │    │ Custom       │        │
    │    │ PII Redact   │        │
    │    └─────────────┘        │
    │         │                  │
    │    Block? → raise error    │
    │         │                  │
    │    Strip _prefixed kwargs  │
    │         │                  │
    │    ┌─ LLM API ──┐        │
    │    │ (real call) │        │
    │    └─────────────┘        │
    │         │                  │
    │    ┌─ POST-HOOKS ┐        │
    │    │ Tools        │        │
    │    │ Budget (log) │        │
    │    └─────────────┘        │
    │         │                  │
    │    Log event to JSONL      │
    │                            │
    └────────────────────────────┘
    │
    ▼
Response returned to your code
```

---

## Policies

A policy is a rule that governs what your agents can do. Policies have two phases:

| Phase | When | Can do |
|-------|------|--------|
| **pre** | Before the LLM call | Block the request, modify it, redact content |
| **post** | After the LLM responds | Intercept tool calls, record metrics, modify response |

### Verdicts

| Verdict | Effect |
|---------|--------|
| **Block** | Request rejected. `PolicyViolationError` raised. LLM never called. |
| **Warn** | Logged in the event. Request/response passes through unchanged. |
| **Refusal** | (post only) Response replaced with a message. Agent can retry. |
| **Interrupt** | (post only) Exception raised. Agent loop breaks. |

### Priority and ordering

Policies run in priority order (lower number = runs first):

```
Priority 10: Budget        ← cheapest check
Priority 15: Agent Control
Priority 20: Custom Rules
Priority 50: Tool Safety
Priority 90: PII           ← most expensive
```

If a pre-hook policy **blocks**, remaining policies are skipped entirely.
Post-hook policies always all run (no short-circuit).

---

## Agents

An agent is a named identity for a group of LLM calls. Different agents can have different policies:

```yaml
policies:
  - name: chatbot-budget
    type: budget
    agents: ["chatbot"]      # only for chatbot
    limit: 10.00

  - name: pii-all
    type: pii                # no agents field = all agents
```

### Setting the agent name

Three ways, in priority order:

| Method | Scope | Example |
|--------|-------|---------|
| `_agent` kwarg | Per-call | `create(..., _agent="chatbot")` |
| `aiwarden.agent()` context manager | Block of code | `with aiwarden.agent("chatbot"):` |
| `AIWARDEN_AGENT_NAME` env var | Process-wide | `export AIWARDEN_AGENT_NAME=chatbot` |

If none is set, the agent name defaults to `"default"`.

```python
import aiwarden

# Option 1: context manager (recommended for multi-agent)
with aiwarden.agent("researcher"):
    response = client.messages.create(...)

# Option 2: per-call kwarg
response = client.messages.create(
    model="claude-sonnet-4-6",
    messages=messages,
    _agent="chatbot",
)
```

---

## Runs

A run represents one complete agent task — from start to finish, potentially spanning many LLM calls:

```
Run: "Research competitors"
  ├── Turn 1: web_search("competitor analysis")
  ├── Turn 2: read_page(url)
  ├── Turn 3: summarize(findings)
  └── Turn 4: "Here's your report."
```

Each run has:

- `run_id` — unique identifier
- `turn` — call counter within the run
- `total_cost` — accumulated spend
- `start_time` — when the run began
- `tools_called` — list of tools used

### Automatic detection

ai-warden detects run boundaries automatically using deterministic signals:

1. **OpenTelemetry trace context** — a new `trace_id` means a new run; same trace continues the existing run
2. **Explicit `_run_id` kwarg** — your code passes a run identifier directly
3. **Conversation structure** — first turn (no assistant messages in history) signals a new run; subsequent turns with assistant messages continue the current run

These are not guesses — each signal is deterministic. The `.create()` call's message history reliably indicates whether this is a new conversation or a continuation.

### Explicit runs (Hot Mode)

For additional tracking (duration, parent-child topology, run summaries), use `aiwarden.run()`:

```python
import aiwarden

with aiwarden.run(agent="researcher") as r:
    # All LLM calls in this block belong to one run
    response1 = client.messages.create(...)
    response2 = client.messages.create(...)

print(r.cost)    # $0.042
print(r.turns)   # 2
print(r.status)  # "completed"
```

Hot mode adds:

- Explicit run boundaries (overrides automatic detection)
- Duration tracking
- Parent-child topology (nested runs)
- Run summary events in the log

---

## Events

Every LLM call produces an event written to `~/.aiwarden/events.jsonl`:

```json
{
  "type": "llm_call",
  "timestamp": "2026-06-24T10:30:00Z",
  "provider": "anthropic",
  "model": "claude-sonnet-4-6",
  "prompt_tokens": 1200,
  "completion_tokens": 450,
  "cost": 0.0105,
  "latency_ms": 2340,
  "run_id": "abc123",
  "turn": 3,
  "agent": "chatbot",
  "caller": {"file": "app/chat.py", "line": 42},
  "policies": [
    {"name": "budget-cap", "action": "pass"},
    {"name": "pii-protection", "action": "warn"}
  ]
}
```

Events are written asynchronously by a background thread — zero impact on your LLM call latency.

### What's captured

| Field | Description |
|-------|-------------|
| `provider` | `anthropic` or `openai` |
| `model` | Model name |
| `prompt_tokens` / `completion_tokens` | Token usage |
| `cost` | Dollar cost (from pricing config) |
| `latency_ms` | End-to-end call time |
| `run_id` / `turn` | Run correlation |
| `agent` | Agent name |
| `caller` | File and line number that made the call |
| `policies` | Which policies fired and their verdicts |
| `tags` | Custom metadata from the request |

---

## Two modes of operation

| Mode | Setup | What you get |
|------|-------|-------------|
| **Zero-touch** | `pip install ai-warden` + YAML | Auto-enforcement, per-call events, budget tracking, automatic run detection |
| **Hot Mode** | Add `aiwarden.run()` to your code | + explicit run boundaries, duration, parent-child topology, run summaries |

Most users start with zero-touch — run detection works automatically from OTel traces and conversation structure. Add hot mode when you need explicit run boundaries or parent-child agent topology.

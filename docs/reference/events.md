# Event Schema

Every LLM call produces a JSONL event at `AIWARDEN_LOG_FILE`.

## Full schema

```json
{
  "id": "3f5d830816c64ae687debfe03c4fd3be",
  "timestamp": "2026-06-18T18:13:40.071162+00:00",
  "provider": "anthropic",
  "type": "chat",
  "run_id": "a0e3bd0e38974983",
  "turn": 1,
  "model": "claude-sonnet-4-6",
  "request_messages": [{"role": "user", "content": "..."}],
  "system": "",
  "response_content": "Here's my answer...",
  "tool_calls": [{"name": "search", "arguments": "{...}", "id": "toolu_..."}],
  "finish_reason": "end_turn",
  "streamed": false,
  "prompt_tokens": 523,
  "completion_tokens": 87,
  "cost": 0.000862,
  "latency_ms": 1423,
  "policy_fired": true,
  "policy_blocked": false,
  "policies": [
    {"name": "content-guard", "action": "warn", "message": "...", "hook": "pre"}
  ],
  "pii_redacted": true,
  "pii_types_found": ["email", "ssn"],
  "tags": {"feature": "onboarding"},
  "metadata": {"team": "engineering"},
  "custom_fields": {"_priority": "high"},
  "caller_file": "/app/agents/chatbot.py",
  "caller_line": 42,
  "caller_function": "handle_message"
}
```

## Field reference

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique event ID |
| `timestamp` | ISO 8601 | When the call completed |
| `provider` | string | `anthropic` or `openai` |
| `run_id` | string | Groups calls in the same agent run |
| `turn` | int | Call number within the run (1, 2, 3...) |
| `model` | string | Model used |
| `cost` | float | Computed cost in USD |
| `latency_ms` | int | Wall-clock time of LLM call |
| `policy_fired` | bool | Any policy triggered (warn or block) |
| `policy_blocked` | bool | Request was blocked (never reached LLM) |
| `policies` | array | Which policies fired and why |
| `pii_redacted` | bool | PII was found and redacted |
| `caller_file` | string | Source file that made the call |

## Blocked events

When a policy blocks a request:

```json
{
  "finish_reason": "blocked",
  "prompt_tokens": 0,
  "completion_tokens": 0,
  "cost": 0.0,
  "latency_ms": 0,
  "policy_blocked": true,
  "policies": [
    {"name": "budget-control", "action": "block", "message": "Budget exceeded..."}
  ]
}
```

Zero tokens, zero cost, zero latency — the LLM was never called.

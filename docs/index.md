# ai-warden

**Policy enforcement and observability for LLM agents. Zero code changes.**

ai-warden sits between your application and the LLM API. Every call to `anthropic.messages.create()` or `openai.chat.completions.create()` is automatically intercepted, governed by your policies, and logged — without modifying a single line of your code.

---

## Install

```bash
pip install ai-warden
```

That's it. Your agents are now protected. PII is redacted, dangerous tools are blocked, and every LLM call is logged to `~/.aiwarden/events.jsonl`.

!!! note "Zero code changes"
    ai-warden patches the Anthropic and OpenAI SDKs at import time via a `.pth` file. No decorators, no wrappers, no configuration required for basic protection.

---

## Quick start

### 1. Create a policy file

Create `.aiwarden/policies.yaml` in your project root:

```yaml
policies:
  - name: pii-protection
    type: pii

  - name: budget-cap
    type: budget
    limit: 50.00
    reset: daily

  - name: tool-safety
    type: tools
    builtin:
      filesystem-safety: true
      no-privilege-escalation: true
      safe-git: true
```

### 2. Run your agent as normal

```python
import anthropic

client = anthropic.Anthropic()
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello!"}],
)
```

ai-warden enforces automatically. If the agent tries to exceed its budget, the call is blocked before tokens are spent. If it tries to run `rm -rf /`, the response is replaced with a refusal message.

### 3. See what happened

```bash
tail -1 ~/.aiwarden/events.jsonl | python -m json.tool
```

Every LLM call is logged: model, tokens, cost, latency, which policies fired, whether anything was blocked.

---

## How it works

```
Your Code → client.messages.create(**kwargs)
                    │
                    ▼
            ┌─── PRE-HOOKS ───┐
            │ [10] Budget      │ ← cheapest check first
            │ [15] Agent ctrl  │
            │ [20] Custom      │
            │ [90] PII redact  │ ← expensive, runs last
            └──────────────────┘
                    │
                    ▼ (blocked? → PolicyViolationError, LLM never called)
                    │
              LLM API call
                    │
                    ▼
            ┌── POST-HOOKS ───┐
            │ [50] Tools       │ ← intercepts dangerous tool calls
            │ [10] Budget      │ ← records actual cost
            └──────────────────┘
                    │
                    ▼
            Response returned to your code
```

**Pre-hooks** fire before the LLM call — they can block, modify, or redact the request.
**Post-hooks** fire after — they intercept tool calls and record metrics.

A blocked request never reaches the LLM: zero tokens consumed, zero cost, zero latency.

---

## What's included

| Policy | What it does | Default | Disable with |
|--------|-------------|---------|--------------|
| [**PII Protection**](policies/pii.md) | Redacts emails, SSNs, credit cards, API keys before the LLM sees them | Enabled | `enabled: false` |
| [**Tool Safety**](policies/tools.md) | Blocks dangerous shell commands, file writes, force pushes | Enabled | `enabled: false` |
| [**Budget Control**](policies/budget.md) | Spend limits per team/agent with daily/weekly/monthly reset | Disabled | — |
| [**Agent Control**](policies/agent-control.md) | Limits turns, cost, and duration per run. Loop detection. | Disabled | — |
| [**Custom Rules**](policies/custom.md) | Declarative rules on any request/response field | Disabled | — |

!!! note "Defaults apply only when no policy file exists"
    Once you create `.aiwarden/policies.yaml`, only the policies listed in it are active. See [Configuration](configuration.md#default-enabled-policies) for details.

---

## Distributed budget enforcement

For multi-process deployments (Kubernetes, Gunicorn workers), enable shared budget tracking via Redis:

```bash
pip install ai-warden[redis]
export AIWARDEN_REDIS_URL=redis://your-redis:6379
```

Budget limits are now enforced across all pods atomically. Without Redis, budgets are tracked per-process.

---

## Next steps

- [Core Concepts](concepts.md) — policies, runs, agents, and how they connect
- [Built-in Policies](policies/overview.md) — all five policy types explained
- [Configuration](configuration.md) — YAML structure, env vars, custom pricing
- [Multi-Agent](multi-agent.md) — different rules for different agents
- [Examples](examples/single-agent.md) — copy-paste recipes

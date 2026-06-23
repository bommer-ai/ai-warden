# Budget Control

**Type:** `budget` | **Priority:** 10 | **Hooks:** pre + post | **Default:** Disabled

Tracks LLM spend over time and blocks requests when a budget limit is exceeded. The LLM is never called when the budget is exhausted — zero tokens, zero cost, zero latency.

---

## How it works

1. **Pre-hook:** Checks accumulated spend against the limit. If `spend >= limit`, blocks the request.
2. **Post-hook:** After the LLM responds, computes the actual cost from token usage and records it.

Cost is computed from model-specific pricing (input tokens + output tokens). Pricing can be customized via `AIWARDEN_PRICING_FILE`.

---

## Configuration

### Global limit

The simplest setup — a single dollar limit for all LLM calls:

```yaml
policies:
  - name: budget-cap
    type: budget
    limit: 100.00
    reset: daily
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `limit` | float | Yes (if no `limits`) | Maximum spend in USD before requests are blocked |
| `reset` | string | No | Reset period: `daily`, `weekly`, or `monthly`. Default: `monthly` |

---

### Per-group limits

Different spend limits for different teams, users, or any grouping:

```yaml
policies:
  - name: team-budgets
    type: budget
    group_by: metadata.team
    limits:
      engineering: 500.00
      research: 200.00
      intern: 20.00
      default: 50.00
    reset: monthly
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `group_by` | string | No | Dot-path into the request to extract the group name. E.g. `metadata.team` |
| `limits` | dict | Yes (if no `limit`) | Map of group name to dollar limit. Use `default` as fallback. |

**Pass the group in your LLM call:**

```python
response = client.messages.create(
    model="claude-sonnet-4-6",
    messages=messages,
    metadata={"team": "engineering"},
)
```

The `metadata.team` value is resolved from the request dict at call time. If the path doesn't resolve or is empty, the group defaults to `__global__`.

---

### Conditional limits

For advanced use cases — different limits based on arbitrary request fields:

```yaml
policies:
  - name: context-budgets
    type: budget
    limits:
      - when:
          metadata.environment: production
        limit: 1000.00
      - when:
          metadata.environment: staging
        limit: 100.00
      - default: 50.00
    reset: monthly
```

Conditions are evaluated in order. The first matching `when` clause wins.

---

### Per-agent limits

Scope budget to a specific named agent:

```yaml
policies:
  - name: chatbot-budget
    type: budget
    agents: ["chatbot"]
    limit: 10.00
    reset: daily

  - name: researcher-budget
    type: budget
    agents: ["researcher"]
    limit: 200.00
    reset: weekly
```

---

## Parameters reference

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | float | — | Single dollar limit (mutually exclusive with `limits`) |
| `limits` | dict or list | — | Per-group or conditional limits (mutually exclusive with `limit`) |
| `group_by` | string | `""` | Dot-path into the request to resolve the group. Empty = global. |
| `reset` | string | `monthly` | When the budget resets: `daily`, `weekly`, or `monthly` |
| `agents` | list[string] | `[]` | Only apply to these agents. Empty = all agents. |

---

## Reset periods

| Value | Resets at | Key format |
|-------|-----------|------------|
| `daily` | Midnight UTC | `2026-06-24` |
| `weekly` | Monday 00:00 UTC | `2026-W25` |
| `monthly` | 1st of month 00:00 UTC | `2026-06` |

Spend from the previous period is not carried over. Each period starts at $0.00.

---

## Distributed enforcement (Redis)

By default, budgets are tracked in-memory per process. In multi-process deployments (Gunicorn workers, Kubernetes pods), each process has its own independent counter.

To enforce budgets across all pods:

```bash
pip install ai-warden[redis]
export AIWARDEN_REDIS_URL=redis://your-redis:6379
```

With Redis enabled:

- Spend is tracked atomically using Lua scripts (`INCRBYFLOAT` + `EXPIRE`)
- All pods share a single counter per group per period
- Budget keys auto-expire with period-appropriate TTLs (daily=2d, weekly=8d, monthly=35d)
- If Redis goes down, ai-warden falls back to per-process tracking with a logged warning

No YAML config changes required. The env var is the only switch.

---

## What happens when blocked

```python
from aiwarden.policies.base import PolicyViolationError

try:
    response = client.messages.create(...)
except PolicyViolationError as e:
    print(e.reason)
    # "Budget exceeded for 'engineering': $500.12 / $500.00 (monthly)"
```

The exception is raised **before** the LLM is called. Your application can catch it and handle gracefully (show a message, queue for later, switch to a cheaper model).

---

## Inspecting current spend

### From code (hot mode)

```python
from aiwarden.policies import engine

# Get the budget policy instance
for policy in engine._get_policies():
    if policy.name == "team-budgets":
        print(policy.get_spend("engineering"))  # 42.50
        print(policy.get_all_spend())           # {"engineering": 42.50, "research": 12.30}
```

### From the event log

```bash
grep '"policy_name":"team-budgets"' ~/.aiwarden/events.jsonl | tail -1
```

---

## Examples

### Startup with tight budget

```yaml
- name: startup-budget
  type: budget
  limit: 50.00
  reset: monthly
```

### Enterprise with team allocation

```yaml
- name: enterprise-budgets
  type: budget
  group_by: metadata.department
  limits:
    engineering: 5000.00
    customer-support: 1000.00
    marketing: 500.00
    default: 100.00
  reset: monthly
```

### Per-agent daily limits

```yaml
- name: chatbot-daily
  type: budget
  agents: ["chatbot"]
  limit: 25.00
  reset: daily

- name: batch-processor-weekly
  type: budget
  agents: ["batch"]
  limit: 500.00
  reset: weekly
```

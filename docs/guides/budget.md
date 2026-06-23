# Budget Control

Set spending limits per agent, team, or globally. Block requests when budget is exceeded.

## Global budget

```yaml title=".aiwarden/policies.yaml"
policies:
  - name: budget-cap
    type: budget
    limit: 100.00
    reset: monthly
```

## Per-team budget

```yaml
policies:
  - name: team-budgets
    type: budget
    group_by: metadata.team
    limits:
      engineering: 500.00
      intern: 20.00
      default: 50.00
    reset: monthly
```

Your code passes the team:
```python
client.messages.create(
    model="claude-sonnet-4-6",
    messages=messages,
    metadata={"team": "engineering"},
)
```

## Per-agent budget

```yaml
policies:
  - name: chatbot-budget
    type: budget
    agents: ["chatbot"]
    limit: 10.00
    reset: daily

  - name: payment-budget
    type: budget
    agents: ["payment-bot"]
    limit: 2.00
    reset: daily
```

## Reset periods

| Value | Resets at |
|-------|-----------|
| `daily` | Midnight UTC |
| `weekly` | Monday midnight UTC |
| `monthly` | 1st of month UTC |

## What happens when blocked

```python
from aiwarden.policies.base import PolicyViolationError

try:
    response = client.messages.create(...)
except PolicyViolationError as e:
    print(e.reason)
    # "Budget exceeded for 'engineering': $500.12 / $500.00 (monthly)"
```

- **Zero tokens consumed** — the LLM call never fires
- **Zero latency added** — instant dict lookup + float comparison
- **Event still logged** — `policy_blocked: true` for audit trail

!!! warning "Process-local tracking"
    Budget is tracked in-memory per process. Multiple workers (gunicorn, k8s pods) each track independently. For distributed enforcement, use a custom BudgetPolicy backed by Redis.

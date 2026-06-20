# Quickstart (5 minutes)

## 1. Install

```bash
pip install aiwarden
```

## 2. Create a policy file

```bash
mkdir -p .aiwarden
```

```yaml title=".aiwarden/policies.yaml"
policies:
  - name: pii-protection
    type: pii
    enabled: true

  - name: budget-cap
    type: budget
    limit: 10.00
    reset: daily

  - name: tool-safety
    type: tools
    builtin:
      filesystem-safety: true
      no-privilege-escalation: true
```

## 3. Run your agent — no code changes

```python
import anthropic

client = anthropic.Anthropic()
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello!"}],
)
# ai-warden is active — PII redacted, budget tracked, tools monitored
```

## 4. See what happened

```bash
cat ~/.aiwarden/events.jsonl | python -m json.tool
```

```json
{
  "provider": "anthropic",
  "model": "claude-sonnet-4-6",
  "run_id": "a0e3bd0e38974983",
  "turn": 1,
  "cost": 0.000862,
  "latency_ms": 1423,
  "policy_fired": false,
  "policy_blocked": false
}
```

## 5. Watch a budget block in action

Set a tiny budget and make multiple calls:

```yaml title=".aiwarden/policies.yaml"
policies:
  - name: tight-budget
    type: budget
    limit: 0.001
    reset: daily
```

```python
# First call succeeds
response = client.messages.create(...)

# Second call raises PolicyViolationError
response = client.messages.create(...)
# ❌ aiwarden.policies.base.PolicyViolationError:
#    Budget exceeded for '__global__': $0.0019 / $0.00 (daily)
```

**No LLM call was made. Zero tokens. Zero cost. Instant block.**

---

Next: [Core Concepts](concepts.md) · [Budget Guide](../guides/budget.md) · [Custom Policies](../guides/custom-policies.md)

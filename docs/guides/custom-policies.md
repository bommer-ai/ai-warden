# Custom Policies

Create your own policies — no code required for declarative rules, or full Python for complex logic.

## Declarative rules (YAML — no code)

```yaml title=".aiwarden/policies.yaml"
policies:
  - name: my-guardrails
    type: custom
    priority: 20
    rules:
      # Block GPT-4 in production
      - name: no-gpt4-prod
        hook: pre
        action: block
        message: "GPT-4 not allowed in production"
        match:
          model:
            startswith: "gpt-4"
        when:
          metadata.environment: production

      # Warn on high token requests
      - name: high-tokens
        hook: pre
        action: warn
        message: "Request exceeds 4000 tokens"
        match:
          max_tokens:
            gt: 4000

      # Block harmful output
      - name: no-harmful-content
        hook: post
        action: block
        message: "Harmful content detected"
        match:
          response.content:
            regex: "(?i)(how to hack|exploit)"
```

## Available operators

| Operator | Type | Example |
|----------|------|---------|
| `contains` | string | `{contains: "password"}` |
| `not_contains` | string | `{not_contains: "approved"}` |
| `startswith` | string/list | `{startswith: ["gpt-4", "gpt-3"]}` |
| `endswith` | string | `{endswith: ".exe"}` |
| `equals` | string | `{equals: "production"}` |
| `in` | list | `{in: ["prod", "staging"]}` |
| `regex` | pattern | `{regex: "(?i)DROP TABLE"}` |
| `gt` | number | `{gt: 4000}` |
| `lt` | number | `{lt: 0}` |
| `gte` / `lte` | number | `{gte: 100}` |

## Field paths

Match on any field using dotted paths:

| Path | What it resolves to |
|------|-------------------|
| `model` | Request model name |
| `max_tokens` | Token limit |
| `metadata.team` | Nested metadata field |
| `messages.content` | Scans all message content |
| `response.content` | Response text (post-hook) |
| `response.completion_tokens` | Output tokens (post-hook) |

## Code-based policies (Python)

For logic that can't be expressed declaratively:

```python title="my_app/policies.py"
from aiwarden.policies.base import Policy, Block, Warn

class RateLimitPolicy(Policy):
    name = "rate-limit"
    priority = 5
    default_hooks = ["pre"]

    def __init__(self, config=None):
        super().__init__(config)
        self._count = 0
        self._max = self.config.get("max_per_minute", 60)

    def pre(self, request):
        self._count += 1
        if self._count > self._max:
            return request, Block(f"Rate limit exceeded: {self._count}/{self._max}")
        return request, None
```

Reference it in YAML:

```yaml
policies:
  - name: my-rate-limiter
    type: module
    module: my_app.policies.RateLimitPolicy
    priority: 5
    max_per_minute: 30
```

## Priority

Lower number = runs first. Cheap blockers before expensive scanners:

```yaml
policies:
  - name: rate-limit      # priority: 5  — cheapest, blocks fastest
    type: module
    priority: 5

  - name: budget          # priority: 10 — dict lookup
    type: budget
    priority: 10

  - name: custom-rules    # priority: 20 — field matching
    type: custom
    priority: 20

  - name: pii             # priority: 90 — regex scan (most expensive)
    type: pii
    priority: 90
```

If a high-priority policy blocks, lower-priority policies never run — zero wasted work.

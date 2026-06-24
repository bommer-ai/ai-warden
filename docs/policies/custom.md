# Custom Policies

**Type:** `custom` | **Priority:** 20 | **Hooks:** pre + post | **Default:** Disabled

Create your own policies with declarative rules. Match on any request or response field, apply conditions, and choose your action — all in YAML. No code needed.

---

## How it works

Custom policies define **rules** — each rule specifies:

1. **When** it applies (hook: pre or post)
2. **What** to match (fields and operators)
3. **What to do** (block, warn)

Rules are evaluated in order. The first matching rule determines the action.

---

## Basic example

```yaml
policies:
  - name: my-guardrails
    type: custom
    rules:
      - name: no-gpt4-in-prod
        hook: pre
        action: block
        message: "GPT-4 not allowed in production. Use claude-sonnet-4-6."
        match:
          model:
            startswith: "gpt-4"
        when:
          metadata.environment: production
```

---

## Rule fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Unique rule identifier. Appears in logs and error messages. |
| `hook` | string | Yes | When to evaluate: `pre` (before LLM call) or `post` (after LLM responds) |
| `action` | string | Yes | What to do on match: `block` or `warn` |
| `message` | string | No | Message included in the block error or warn log |
| `match` | dict | Yes | Field-operator pairs to match against |
| `when` | dict | No | Additional conditions (metadata, environment) |

---

## Operators

| Operator | Type | Example | Description |
|----------|------|---------|-------------|
| `contains` | string | `{contains: "password"}` | String contains substring |
| `not_contains` | string | `{not_contains: "approved"}` | String does NOT contain substring |
| `startswith` | string or list | `{startswith: ["gpt-4", "gpt-3"]}` | Starts with value (or any in list) |
| `endswith` | string | `{endswith: ".exe"}` | Ends with value |
| `equals` | any | `{equals: "production"}` | Exact match |
| `not_equals` | any | `{not_equals: "test"}` | Not exact match |
| `in` | list | `{in: ["prod", "staging"]}` | Value is one of the listed items |
| `not_in` | list | `{not_in: ["dev", "test"]}` | Value is NOT in the list |
| `regex` | string | `{regex: "(?i)DROP TABLE"}` | Regex match (Python `re` syntax) |
| `gt` | number | `{gt: 4000}` | Greater than |
| `lt` | number | `{lt: 100}` | Less than |
| `gte` | number | `{gte: 1000}` | Greater than or equal |
| `lte` | number | `{lte: 8192}` | Less than or equal |

Multiple operators in one match are AND-ed:

```yaml
match:
  max_tokens:
    gt: 4000
    lte: 16000
```

This matches when `4000 < max_tokens <= 16000`.

---

## Matchable fields

### Pre-hook (request fields)

| Field | Type | Description |
|-------|------|-------------|
| `model` | string | Model name (e.g., `claude-sonnet-4-6`, `gpt-4o`) |
| `max_tokens` | integer | Maximum tokens requested |
| `temperature` | float | Sampling temperature |
| `metadata.{key}` | any | Custom metadata passed in the request |
| `messages.content` | string | Concatenated message content |
| `run.turns` | integer | Current turn count in this run |
| `run.cost` | float | Accumulated cost in this run |

### Post-hook (response fields)

| Field | Type | Description |
|-------|------|-------------|
| `response.content` | string | Text content of the response |
| `response.completion_tokens` | integer | Tokens in the response |
| `response.prompt_tokens` | integer | Tokens in the prompt |
| `response.finish_reason` | string | Why the response ended |

---

## Conditions with `when`

The `when` field adds context-based conditions. Rules only fire when ALL `when` conditions match:

```yaml
rules:
  - name: expensive-model-prod-only
    hook: pre
    action: block
    message: "Claude Opus restricted to production."
    match:
      model:
        contains: "opus"
    when:
      metadata.environment:
        not_equals: production
```

`when` supports the same operators as `match`. It evaluates against the request dict using dot-path resolution.

---

## Multiple rules

Rules are evaluated in order. Each rule is independent — multiple rules can match the same request:

```yaml
policies:
  - name: content-safety
    type: custom
    rules:
      - name: no-opus-for-interns
        hook: pre
        action: block
        message: "Interns cannot use Claude Opus."
        match:
          model:
            contains: "opus"
        when:
          metadata.role: intern

      - name: warn-high-tokens
        hook: pre
        action: warn
        message: "High token request — review for necessity."
        match:
          max_tokens:
            gt: 8000

      - name: block-harmful-output
        hook: post
        action: block
        message: "Response contained harmful content."
        match:
          response.content:
            regex: "(?i)(how to (hack|exploit|attack))"
```

---

## Validation

Rules are validated at load time:

- Invalid rules produce a warning log and are skipped
- Your application never crashes due to a bad rule
- A rule with no `match` field is skipped
- Unknown operators are skipped with a warning

---

## Examples

### Model access control

```yaml
- name: model-access
  type: custom
  rules:
    - name: no-expensive-models-dev
      hook: pre
      action: block
      message: "Use claude-sonnet-4-6 in development."
      match:
        model:
          regex: "(opus|gpt-4-turbo)"
      when:
        metadata.environment:
          in: ["development", "staging"]
```

### Token limit enforcement

```yaml
- name: token-limits
  type: custom
  rules:
    - name: cap-max-tokens
      hook: pre
      action: block
      message: "max_tokens capped at 4096 for this service."
      match:
        max_tokens:
          gt: 4096
```

### Response content filtering

```yaml
- name: output-filter
  type: custom
  rules:
    - name: no-code-generation
      hook: post
      action: warn
      message: "Agent generated code — review required."
      match:
        response.content:
          regex: "```(python|javascript|bash)"
```

### Rate limiting by turns

```yaml
- name: turn-guard
  type: custom
  rules:
    - name: warn-at-turn-10
      hook: pre
      action: warn
      message: "Agent has been running for 10+ turns."
      match:
        run.turns:
          gte: 10

    - name: block-at-turn-20
      hook: pre
      action: block
      message: "Agent exceeded 20 turns. Stopping."
      match:
        run.turns:
          gte: 20
```

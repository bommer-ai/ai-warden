---
icon: material/code-tags
---

# :material-code-tags: Custom Policies

**Type:** `custom` | **Priority:** 20 | **Hooks:** pre + post | **Default:** Disabled

Create your own policies with declarative rules. Match on any request or response field, apply conditions, and choose your action — all in YAML. No code needed.

---

## :material-lightning-bolt: Quick example

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

## :material-table: Rule fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | :material-check: | Rule identifier |
| `hook` | string | :material-check: | `pre` or `post` |
| `action` | string | :material-check: | `block` or `warn` |
| `message` | string | :material-close: | Message in error/log |
| `match` | dict | :material-check: | Field-operator pairs |
| `when` | dict | :material-close: | Context conditions |

---

## :material-format-list-checks: Operators

| Operator | Type | Example | Description |
|----------|------|---------|-------------|
| `contains` | string | `{contains: "password"}` | Substring match |
| `not_contains` | string | `{not_contains: "approved"}` | NOT substring |
| `startswith` | string/list | `{startswith: ["gpt-4", "gpt-3"]}` | Prefix match |
| `endswith` | string | `{endswith: ".exe"}` | Suffix match |
| `equals` | any | `{equals: "production"}` | Exact match |
| `not_equals` | any | `{not_equals: "test"}` | NOT exact |
| `in` | list | `{in: ["prod", "staging"]}` | Value in list |
| `not_in` | list | `{not_in: ["dev", "test"]}` | Value NOT in list |
| `regex` | string | `{regex: "(?i)DROP TABLE"}` | Python regex |
| `gt` | number | `{gt: 4000}` | Greater than |
| `lt` | number | `{lt: 100}` | Less than |
| `gte` | number | `{gte: 1000}` | Greater or equal |
| `lte` | number | `{lte: 8192}` | Less or equal |

!!! tip "Multiple operators = AND"
    ```yaml
    match:
      max_tokens:
        gt: 4000
        lte: 16000
    ```
    Matches when `4000 < max_tokens <= 16000`.

---

## :material-target: Matchable fields

=== ":material-arrow-right: Pre-hook (request)"

    | Field | Type | Description |
    |-------|------|-------------|
    | `model` | string | Model name |
    | `max_tokens` | integer | Max tokens requested |
    | `temperature` | float | Sampling temperature |
    | `metadata.{key}` | any | Custom metadata |
    | `messages.content` | string | Concatenated message content |
    | `run.turns` | integer | Current turn count |
    | `run.cost` | float | Accumulated run cost |

=== ":material-arrow-left: Post-hook (response)"

    | Field | Type | Description |
    |-------|------|-------------|
    | `response.content` | string | Response text |
    | `response.completion_tokens` | integer | Output tokens |
    | `response.prompt_tokens` | integer | Input tokens |
    | `response.finish_reason` | string | Why response ended |

---

## :material-filter: Conditions with `when`

The `when` field restricts rules to specific contexts:

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

!!! info "`when` supports the same operators as `match`"
    It evaluates against the request dict using dot-path resolution.

---

## :material-check-decagram: Validation

- :material-check: Invalid rules produce a warning and are skipped
- :material-check: Your application never crashes due to a bad rule
- :material-check: Unknown operators are logged and ignored
- :material-check: Rules validated at load time, not at call time

---

## :material-code-braces: Examples

=== "Model access control"

    ```yaml
    - name: model-access
      type: custom
      rules:
        - name: no-expensive-in-dev
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

=== "Token limit enforcement"

    ```yaml
    - name: token-limits
      type: custom
      rules:
        - name: cap-max-tokens
          hook: pre
          action: block
          message: "max_tokens capped at 4096."
          match:
            max_tokens:
              gt: 4096
    ```

=== "Content filtering"

    ```yaml
    - name: output-filter
      type: custom
      rules:
        - name: no-code-generation
          hook: post
          action: warn
          message: "Agent generated code."
          match:
            response.content:
              regex: "```(python|javascript|bash)"
    ```

=== "Turn guard"

    ```yaml
    - name: turn-guard
      type: custom
      rules:
        - name: warn-at-10
          hook: pre
          action: warn
          message: "Agent running 10+ turns."
          match:
            run.turns:
              gte: 10

        - name: block-at-20
          hook: pre
          action: block
          message: "Agent exceeded 20 turns."
          match:
            run.turns:
              gte: 20
    ```

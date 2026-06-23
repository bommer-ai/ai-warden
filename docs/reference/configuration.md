# Configuration Reference

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AIWARDEN_ENABLED` | `true` | Set `false` to disable all enforcement |
| `AIWARDEN_DEBUG` | `false` | Print events to stdout |
| `AIWARDEN_LOG_FILE` | `~/.aiwarden/events.jsonl` | Event output path |
| `AIWARDEN_AGENT_NAME` | `default` | Default agent name for policy scoping |
| `AIWARDEN_PRICING_FILE` | — | Custom pricing YAML path |
| `AIWARDEN_CALLER_TRACKING` | `true` | Enable stack-walk caller attribution |
| `AIWARDEN_POLICY_FILE` | — | Explicit policy file path |

## Policy file locations

Searched in order:

1. `AIWARDEN_POLICY_FILE` env var (if set)
2. `.aiwarden/policies.yaml` (project directory)
3. `~/.aiwarden/policies.yaml` (home directory)
4. Built-in defaults (PII + tool safety)

## Policy YAML schema

```yaml
policies:
  - name: string              # required — unique policy name
    type: string              # required — pii | tools | budget | custom | module
    enabled: true             # optional — set false to disable
    priority: 100             # optional — lower runs first (10=budget, 90=pii)
    agents: ["agent-name"]    # optional — scope to specific agents

    # Type-specific config below...
```

## Budget policy config

```yaml
- name: budget-cap
  type: budget
  group_by: metadata.team      # dotted path into request
  limit: 100.00                # flat limit (or use 'limits' for per-group)
  limits:                      # per-group limits
    engineering: 500.00
    default: 50.00
  reset: monthly               # daily | weekly | monthly
```

## PII policy config

```yaml
- name: pii-protection
  type: pii
  patterns:                    # custom patterns (merged with built-ins)
    custom_name: "\\bregex\\b"
    cc: false                  # disable a built-in
```

## Tools policy config

```yaml
- name: tool-safety
  type: tools
  builtin:
    filesystem-safety: true
    no-privilege-escalation: true
  rules:
    - name: rule-name
      action: refusal | interrupt | warn
      message: "Human-readable reason"
      match:
        tool: "tool-name-or-glob"
        arg_name: {operator: value}
        any_arg: {operator: value}
      when:
        metadata:
          key: value
```

## Custom policy config

```yaml
- name: my-rules
  type: custom
  rules:
    - name: rule-name
      hook: pre | post
      action: block | warn
      message: "Reason"
      match:
        field.path: {operator: value}
      when:
        field.path: expected_value
```

## Module policy config

```yaml
- name: my-custom-logic
  type: module
  module: my_app.policies.MyPolicyClass
  priority: 5
  # any other keys become self.config in the policy
```

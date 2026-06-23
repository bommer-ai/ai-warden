# Example: Custom Rules

Declarative policies for common scenarios — no code needed.

## Block specific models in production

```yaml
- name: model-restrictions
  type: custom
  rules:
    - name: no-gpt4-prod
      hook: pre
      action: block
      message: "GPT-4 not allowed in production. Use claude-sonnet-4-6."
      match:
        model:
          startswith: "gpt-4"
      when:
        metadata.environment: production
```

## Limit token usage per team

```yaml
- name: token-limits
  type: custom
  rules:
    - name: intern-token-cap
      hook: pre
      action: block
      message: "Interns limited to 2000 tokens per request"
      match:
        max_tokens:
          gt: 2000
      when:
        metadata.team: intern
```

## Content guardrails on responses

```yaml
- name: output-safety
  type: custom
  rules:
    - name: no-harmful-content
      hook: post
      action: block
      message: "Response contained restricted content"
      match:
        response.content:
          regex: "(?i)(how to (hack|exploit|attack))"

    - name: no-competitor-recommendations
      hook: post
      action: warn
      message: "Response mentions competitor"
      match:
        response.content:
          contains: "use ChatGPT instead"
```

## Warn on expensive requests

```yaml
- name: cost-awareness
  type: custom
  rules:
    - name: high-token-warning
      hook: pre
      action: warn
      message: "Request uses 8000+ tokens"
      match:
        max_tokens:
          gt: 8000
```

## Block after N turns in a run

```yaml
- name: run-limits
  type: custom
  rules:
    - name: max-10-turns
      hook: pre
      action: block
      message: "Run exceeded 10 turns"
      match:
        run.turns:
          gte: 10
```

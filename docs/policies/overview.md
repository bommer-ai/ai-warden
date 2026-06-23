# Built-in Policies

ai-warden ships with five policy types. All configured via YAML — no code needed.

---

## Policy types

| Type | Priority | Phase | What it governs |
|------|----------|-------|-----------------|
| [`budget`](budget.md) | 10 | pre (enforce) + post (record cost) | Spend over time (per team, per agent, global) |
| [`agent_control`](agent-control.md) | 15 | pre | The run itself (turns, cost, duration, loops) |
| [`custom`](custom.md) | 20 | pre + post | Anything — declarative rules on any field |
| [`tools`](tools.md) | 50 | post | Tool calls (which tools, what arguments) |
| [`pii`](pii.md) | 90 | pre | Data reaching the LLM (redaction) |

---

## Priority and execution order

Policies run in priority order (lower number = runs first). This ordering is intentional:

1. **Budget (10)** — cheapest check. If the team is over budget, reject instantly.
2. **Agent Control (15)** — check turn/cost/duration limits for this run.
3. **Custom (20)** — your business rules (model restrictions, content filters).
4. **Tools (50)** — inspect the LLM's response for dangerous tool calls.
5. **PII (90)** — expensive regex scan, only runs if nothing else blocked.

!!! tip "Short-circuit saves time"
    If budget blocks a request, PII redaction never runs. The expensive work is avoided entirely.

```
[10] budget   → pass ✓  (0.001ms)
[15] agent    → BLOCK ✗  (0.001ms)
[50] tools    → never runs
[90] pii      → never runs
```

---

## Policy actions

| Action | Phase | Behavior |
|--------|-------|----------|
| **block** | pre | Request never reaches the LLM. `PolicyViolationError` raised. |
| **warn** | pre/post | Logged in the event. Request/response passes through normally. |
| **refusal** | post | LLM response replaced with your message. Agent loop continues gracefully. |
| **interrupt** | post | `PolicyViolationError` raised. Agent loop breaks hard. |

### When to use which

- **block** — budget exceeded, unauthorized model, content policy violation. The LLM should never see this request.
- **warn** — approaching limits, unusual patterns. Log it for review but don't disrupt the agent.
- **refusal** — the LLM tried to call a dangerous tool. Replace with a helpful message so the agent can try a different approach.
- **interrupt** — critical safety violation in the LLM's output. Stop the agent entirely.

---

## Common policy fields

Every policy type supports these fields:

```yaml
policies:
  - name: my-policy          # required — unique identifier
    type: budget             # required — one of: pii, tools, budget, agent_control, custom, module
    enabled: true            # optional — set to false to disable without removing
    priority: 100            # optional — lower runs first (default: type-specific)
    agents: ["chatbot"]      # optional — scope to specific agents (empty = all agents)
    hooks: ["pre", "post"]   # optional — override which phases this policy runs in
```

### Field reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Unique identifier for this policy. Used in logs and error messages. |
| `type` | string | Yes | Policy type: `pii`, `tools`, `budget`, `agent_control`, `custom`, or `module`. |
| `enabled` | boolean | No | Default `true`. Set to `false` to disable without removing from config. |
| `priority` | integer | No | Execution order. Lower = runs first. Each type has a sensible default. |
| `agents` | list[string] | No | If set, policy only applies to these named agents. Empty list = all agents. |
| `hooks` | list[string] | No | Override which phases run: `["pre"]`, `["post"]`, or `["pre", "post"]`. |

---

## Agent scoping

The `agents` field lets you apply different policies to different agents:

```yaml
policies:
  # Strict budget for the chatbot
  - name: chatbot-budget
    type: budget
    agents: ["chatbot"]
    limit: 10.00
    reset: daily

  # Generous budget for the researcher
  - name: researcher-budget
    type: budget
    agents: ["researcher"]
    limit: 200.00
    reset: monthly

  # PII protection for all agents (no agents field)
  - name: pii-global
    type: pii
```

Set the agent name in your code:

=== "Context manager"

    ```python
    import aiwarden

    with aiwarden.agent("chatbot"):
        response = client.messages.create(...)
    ```

=== "Per-call kwarg"

    ```python
    response = client.messages.create(
        model="claude-sonnet-4-6",
        messages=messages,
        _agent="chatbot",  # underscore prefix = stripped before API call
    )
    ```

=== "Environment variable"

    ```bash
    export AIWARDEN_AGENT_NAME=chatbot
    ```

---

## Writing a module policy

For policies that need code beyond what YAML can express, use the `module` type:

```yaml
- name: my-complex-policy
  type: module
  module: mypackage.policies.RateLimitPolicy
  max_requests_per_minute: 60
```

See [Writing a Module Policy](../advanced/module-policy.md) for the full guide.

# Policy Engine

## Flow

```
Agent Code
    │
    │  client.messages.create(model=..., messages=..., tools=..., metadata={...})
    ▼
┌─────────────────────────────────────────────────────┐
│  aiwarden patcher (transparent, zero code changes)  │
│                                                     │
│  1. PRE-PROCESSORS                                  │
│     └─ PIIRedactPreProcessor                        │
│        redacts emails, phone numbers, SSNs          │
│        from request messages before sending         │
└───────────────────┬─────────────────────────────────┘
                    │
                    ▼
             Anthropic API
             (LLM responds with tool_use blocks)
                    │
                    ▼
┌─────────────────────────────────────────────────────┐
│  2. POST-PROCESSORS                                 │
│     └─ PolicyEnforcer                               │
│        for each tool_use block in response:         │
│          ┌─ match tool name?  ──────────── NO ──┐   │
│          │                                      │   │
│          ▼ YES                                  │   │
│          match args?  ──────────────── NO ──────┤   │
│          │                                      │   │
│          ▼ YES                                  │   │
│          match metadata (when:)?  ──── NO ──────┘   │
│          │                                          │
│          ▼ YES — rule matched                       │
│          ┌──────────────────────────────────────┐   │
│          │ action: refusal                      │   │
│          │   replace tool_use with text block   │   │
│          │   stop_reason → "end_turn"           │   │
│          │   agent loop CONTINUES               │   │
│          ├──────────────────────────────────────┤   │
│          │ action: interrupt                    │   │
│          │   raise PolicyViolationError         │   │
│          │   agent loop BREAKS                  │   │
│          ├──────────────────────────────────────┤   │
│          │ action: warn                         │   │
│          │   log warning                        │   │
│          │   agent loop CONTINUES unchanged     │   │
│          └──────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
                    │
                    ▼
             Agent receives response
             (original, or refusal text, or exception)
```

---

## Examples

### Example 1 — Built-in policy blocks `rm -rf` (no config needed)

```python
# Agent code — no changes required
response = client.messages.create(
    model="claude-3-5-sonnet-20241022",
    max_tokens=1024,
    tools=[{"name": "bash", "description": "Run shell commands", "input_schema": {...}}],
    messages=[{"role": "user", "content": "Clean up all temp files"}],
)

# LLM responds with:
# content: [ToolUseBlock(name="bash", input={"command": "rm -rf /tmp/*"})]

# aiwarden intercepts — matches filesystem-safety > no-recursive-delete rule
# Returns instead:
# content: [TextBlock(text="Recursive deletion is not allowed.")]
# stop_reason: "end_turn"

# Agent sees a text response — loop continues, LLM can try a safer approach
```

---

### Example 2 — Custom rule blocks SQL on prod, allows on staging

**`~/.aiwarden/policies.yaml`**
```yaml
rules:
  - name: no-drop-table-prod
    action: interrupt
    message: "DROP TABLE is not allowed in production. Run a migration instead."
    match:
      tool: execute_sql
      query:
        regex: "(?i)DROP\\s+TABLE"
    when:
      metadata:
        deployment: prod
```

```python
# staging — rule does NOT apply (metadata.deployment != prod)
response = client.messages.create(
    ...,
    metadata={"deployment": "staging"},
)
# tool executes normally

# prod — rule fires, raises PolicyViolationError
try:
    response = client.messages.create(
        ...,
        metadata={"deployment": "prod"},
    )
except PolicyViolationError as e:
    print(e)  # "DROP TABLE is not allowed in production."
```

---

### Example 3 — Warn only (observe without blocking)

```yaml
rules:
  - name: log-all-bash
    action: warn
    match:
      tool: bash
```

```
[aiwarden] POLICY WARN — Policy 'log-all-bash' matched tool 'bash'
           (tool: bash  input: {"command": "ls -la"})
```
Agent is unaffected. Use this to audit what your agent is doing before adding hard blocks.

---

### Example 4 — Custom tool, custom args

Your agent has a `send_email` tool. You want to block external addresses.

```yaml
rules:
  - name: no-external-email
    action: refusal
    message: "Emails can only be sent to @yourcompany.com addresses."
    match:
      tool: send_email
      to:
        not_startswith: ["your", "internal"]  # too broad — use regex
      to:
        regex: "^(?!.*@yourcompany\\.com).*$"
```

---

## Config file search order

```
AIWARDEN_POLICY_FILE env var       highest priority — explicit path
.aiwarden/policies.yaml            project-level — commit to repo
~/.aiwarden/policies.yaml          global — all projects on this machine
(none found)                       filesystem-safety + no-privilege-escalation
                                   run by default
```

---

## Built-in templates

| Template | Default | What it catches |
|---|---|---|
| `filesystem-safety` | **ON** | `rm -rf`, writes to `/etc/` `/sys/` `/boot/` |
| `no-privilege-escalation` | **ON** | `sudo`, `su`, `chmod 777` |
| `no-credential-access` | off | `.env`, `.aws/credentials`, `printenv` |
| `safe-git` | off | `push --force`, `reset --hard`, `branch -D` |
| `no-auto-install` | off | `pip install`, `npm install`, `yarn add` |
| `network-safety` | off | `curl`, `wget` (warn only) |

Enable in config:
```yaml
builtin:
  filesystem-safety: true
  no-privilege-escalation: true
  no-credential-access: true
  safe-git: true
```

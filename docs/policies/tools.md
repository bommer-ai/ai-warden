# Tool Safety

**Type:** `tools` | **Priority:** 50 | **Hooks:** post | **Default:** Enabled

Inspects LLM responses for dangerous tool calls and blocks them before your agent executes them. The response is replaced with a refusal message — the agent sees "I'm not allowed to do that" and can try a different approach.

---

## How it works

1. The LLM responds with `tool_use` blocks (e.g., "call bash with `rm -rf /`")
2. Tool Safety inspects each tool call against your rules
3. On match: the response is replaced with a refusal message (or exception raised)
4. The agent never executes the dangerous command

!!! note "Post-hook only"
    Tool Safety runs in the post-hook because it inspects the LLM's output (what tool the model wants to call), not the input. The LLM call has already happened — tokens are consumed — but the dangerous action is prevented.

---

## Built-in templates

Enable pre-built rule sets with a single flag:

```yaml
policies:
  - name: tool-safety
    type: tools
    builtin:
      filesystem-safety: true
      no-privilege-escalation: true
      safe-git: true
      no-credential-access: true
      no-auto-install: true
      network-safety: true
```

### Template reference

| Template | What it blocks |
|----------|----------------|
| `filesystem-safety` | `rm -rf`, `rm -fr`, writes to `/etc/`, `/sys/`, `/proc/` |
| `no-privilege-escalation` | `sudo`, `su`, `chmod 777`, `chown root` |
| `safe-git` | `git push --force`, `git reset --hard`, `git clean -f` |
| `no-credential-access` | Reading `.env`, `.ssh/`, `.aws/credentials` |
| `no-auto-install` | `pip install`, `npm install`, `apt-get install` without confirmation |
| `network-safety` | Warns on `curl`, `wget`, `nc` (warn action, not block) |

Templates stack — enable as many as you need. Custom rules can be added alongside templates.

---

## Custom rules

Write your own rules for tool-call inspection:

```yaml
policies:
  - name: tool-safety
    type: tools
    rules:
      - name: no-prod-db-writes
        action: refusal
        message: "Database writes blocked in production."
        match:
          tool: execute_sql
          query:
            regex: "(?i)(INSERT|UPDATE|DELETE|DROP)"
        when:
          metadata:
            environment: production

      - name: no-external-fetch
        action: warn
        match:
          tool: bash
          command:
            contains: "curl"
```

---

## Rule fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Unique rule identifier. Appears in logs. |
| `action` | string | Yes | One of: `refusal`, `interrupt`, `warn` |
| `message` | string | No | Message shown to the agent (for refusal/interrupt) |
| `match` | dict | Yes | Matching criteria (see below) |
| `when` | dict | No | Additional context conditions |

---

## Actions

| Action | Behavior | Agent loop |
|--------|----------|------------|
| `refusal` | LLM response replaced with `message`. Agent sees "I can't do that." | Continues — agent tries something else |
| `interrupt` | `PolicyViolationError` raised with `message`. | Breaks — agent loop ends |
| `warn` | Logged in the event. Original response passes through. | Continues unchanged |

### When to use which

- **refusal** — for most cases. The agent gets feedback and can adjust its approach.
- **interrupt** — for critical violations where the agent should stop entirely (e.g., force-push to main).
- **warn** — for monitoring. Log that something happened without disrupting the agent.

---

## Match syntax

### Tool name matching

```yaml
# Exact match
match:
  tool: bash

# Glob pattern
match:
  tool: "*write*"

# List (any of)
match:
  tool: ["bash", "shell", "run_command"]

# Wildcard (all tools)
match:
  tool: "*"
```

### Argument matching

Match on specific tool input arguments:

```yaml
match:
  tool: bash
  command:
    contains: "rm -rf"
```

| Operator | Type | Example | Matches |
|----------|------|---------|---------|
| `contains` | string | `{contains: "rm -rf"}` | Any string containing the substring |
| `startswith` | string or list | `{startswith: ["/etc/", "/sys/"]}` | String starting with any of the prefixes |
| `not_startswith` | string or list | `{not_startswith: ["/tmp/"]}` | String NOT starting with the prefixes |
| `equals` | string | `{equals: "production"}` | Exact match |
| `in` | list | `{in: ["prod", "staging"]}` | Value is one of the listed items |
| `regex` | pattern | `{regex: "rm\\s+-[rRfF]*[rR]"}` | Regex match (Python `re` syntax) |

### Any-argument matching

Match if **any** argument contains the pattern (regardless of which field):

```yaml
match:
  tool: "*"
  any_arg:
    contains: "password"
```

### Context scoping with `when`

Restrict rules to specific metadata contexts:

```yaml
match:
  tool: execute_sql
  query:
    regex: "(?i)DROP"
when:
  metadata:
    deployment: production
```

The rule only fires when `metadata.deployment == "production"` in the request. Without `when`, the rule applies globally.

---

## Combining templates and custom rules

Templates and custom rules stack:

```yaml
policies:
  - name: tool-safety
    type: tools
    builtin:
      filesystem-safety: true
      safe-git: true
    rules:
      - name: no-docker-rm
        action: refusal
        message: "Docker container removal not allowed."
        match:
          tool: bash
          command:
            regex: "docker\\s+(rm|container\\s+rm)"
```

Built-in template rules and your custom rules are merged into one rule set.

---

## Examples

### Block destructive SQL in production

```yaml
- name: db-safety
  type: tools
  rules:
    - name: no-drop-in-prod
      action: interrupt
      message: "DROP TABLE blocked in production. Use a migration."
      match:
        tool: execute_sql
        query:
          regex: "(?i)DROP\\s+(TABLE|DATABASE)"
      when:
        metadata:
          environment: production
```

### Restrict file writes to project directory

```yaml
- name: file-safety
  type: tools
  rules:
    - name: no-writes-outside-project
      action: refusal
      message: "File writes restricted to project directory."
      match:
        tool: ["write_file", "create_file"]
        path:
          not_startswith: ["/home/deploy/myproject/", "/tmp/"]
```

### Warn on network access

```yaml
- name: network-monitor
  type: tools
  rules:
    - name: log-external-requests
      action: warn
      match:
        tool: bash
        command:
          regex: "(curl|wget|nc|ncat)\\s"
```

# Tool Safety

Block dangerous tool calls before your agent executes them.

## Built-in templates

```yaml title=".aiwarden/policies.yaml"
policies:
  - name: tool-safety
    type: tools
    builtin:
      filesystem-safety: true          # blocks rm -rf, writes to /etc
      no-privilege-escalation: true    # blocks sudo, su, chmod 777
      safe-git: true                   # blocks force-push, hard reset
      no-credential-access: true       # blocks reading .env, .ssh/
      no-auto-install: true            # blocks pip install, npm install
      network-safety: true             # warns on curl, wget
```

## Custom rules

```yaml
policies:
  - name: tool-safety
    type: tools
    rules:
      - name: no-production-writes
        action: refusal
        message: "Database writes blocked in production"
        match:
          tool: execute_sql
          query:
            regex: "(?i)(INSERT|UPDATE|DELETE|DROP)"
        when:
          metadata:
            environment: production

      - name: no-send-to-many
        action: interrupt
        message: "Cannot send to more than 100 recipients"
        match:
          tool: send_email
          count:
            gt: 100
```

## Actions

| Action | Behavior | Agent loop |
|--------|----------|-----------|
| `refusal` | Replaces response with a text message | Continues (agent sees "not allowed") |
| `interrupt` | Raises `PolicyViolationError` | Breaks |
| `warn` | Logs warning, passes through | Continues unchanged |

## Matching DSL

| Matcher | Example |
|---------|---------|
| `tool: "bash"` | Exact tool name |
| `tool: "*write*"` | Glob pattern |
| `tool: ["bash", "shell"]` | List of names |
| `command: {contains: "rm -rf"}` | Arg contains string |
| `path: {startswith: "/etc/"}` | Arg starts with |
| `query: {regex: "(?i)DROP"}` | Arg matches regex |
| `any_arg: {contains: "password"}` | Any arg value matches |
| `when: {metadata: {env: "prod"}}` | Only in specific context |

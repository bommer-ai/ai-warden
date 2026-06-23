# Policy Types

## Built-in

| Type | Hook | Priority | What it does |
|------|------|----------|-------------|
| `budget` | pre + post | 10 | Track spend, block when exceeded |
| `tools` | post | 50 | Block dangerous tool calls |
| `pii` | pre | 90 | Redact sensitive data |

## User-defined

| Type | Hook | What it does |
|------|------|-------------|
| `custom` | pre + post | Declarative rules on any field (YAML, no code) |
| `module` | any | Your Python class for complex logic |

## Comparison: when to use what

| I want to... | Use |
|---|---|
| Block a model in production | `type: custom` rule |
| Limit spending per team | `type: budget` |
| Remove emails from prompts | `type: pii` |
| Block `rm -rf` in tool calls | `type: tools` |
| Rate limit by user | `type: module` (needs state) |
| Block responses containing X | `type: custom` post-hook rule |
| Custom PII patterns | `type: pii` with `patterns:` |

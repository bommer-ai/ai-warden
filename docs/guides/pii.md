# PII Redaction

Redact sensitive data from messages before they reach the LLM.

## Built-in patterns

Enabled by default: email, phone, SSN, API keys (`sk-...`), credit card numbers.

```yaml title=".aiwarden/policies.yaml"
policies:
  - name: pii-protection
    type: pii
```

**Before redaction:**
```
"My email is anoop@company.com and SSN is 123-45-6789"
```

**What the LLM sees:**
```
"My email is [REDACTED:email] and SSN is [REDACTED:ssn]"
```

## Add custom patterns

```yaml
policies:
  - name: pii-protection
    type: pii
    patterns:
      employee_id: "\\bEMP-\\d{6}\\b"
      internal_ip: "\\b10\\.\\d+\\.\\d+\\.\\d+\\b"
      account_number: "\\bACCT-[A-Z0-9]{8}\\b"
```

## Disable a built-in pattern

```yaml
policies:
  - name: pii-protection
    type: pii
    patterns:
      cc: false     # disable credit card detection (too many false positives)
```

## How it works

- Patterns are compiled **once** at startup (zero per-call overhead)
- Only the **last user message** content is scanned (agent loops don't re-scan history)
- System prompt is also redacted
- Found PII types are logged in the event (`pii_types_found: ["email", "ssn"]`)

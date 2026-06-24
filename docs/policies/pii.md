# PII Protection

**Type:** `pii` | **Priority:** 90 | **Hooks:** pre | **Default:** Enabled

Redacts personally identifiable information from the request before it reaches the LLM. The model never sees the real values — only `[REDACTED:type]` placeholders.

---

## How it works

1. Before the LLM call, PII Protection scans all message content
2. Matches are replaced with `[REDACTED:pattern_name]` tokens
3. The LLM receives the sanitized input — it can still reason about the structure but never sees real data
4. The event log records which patterns matched (but not the original values)

!!! note "High priority number = runs last"
    PII Protection has priority 90 — it runs after budget and agent control checks. If a request is going to be blocked anyway, there's no point paying the regex scan cost.

---

## Default configuration (zero config)

```yaml
policies:
  - name: pii-protection
    type: pii
```

With no additional configuration, these patterns are active:

| Pattern | What it matches | Example |
|---------|----------------|---------|
| `email` | Email addresses | `user@example.com` → `[REDACTED:email]` |
| `phone` | Phone numbers (US/intl formats) | `+1-555-0123` → `[REDACTED:phone]` |
| `ssn` | US Social Security Numbers | `123-45-6789` → `[REDACTED:ssn]` |
| `cc` | Credit card numbers (Luhn-valid patterns) | `4111-1111-1111-1111` → `[REDACTED:cc]` |
| `api_key` | Common API key formats (`sk-...`, `key-...`) | `sk-abc123...` → `[REDACTED:api_key]` |

---

## Adding custom patterns

Add your own regex patterns for domain-specific PII:

```yaml
policies:
  - name: pii-protection
    type: pii
    patterns:
      employee_id: "\\bEMP-\\d{6}\\b"
      internal_ip: "\\b10\\.\\d+\\.\\d+\\.\\d+\\b"
      account_number: "\\bACCT-[A-Z0-9]{8}\\b"
      mrn: "\\bMRN-\\d{8}\\b"
```

Custom patterns are added alongside the built-in ones. Each key becomes the redaction label:

```
"Patient MRN-12345678 at 10.0.1.50" → "Patient [REDACTED:mrn] at [REDACTED:internal_ip]"
```

---

## Disabling a built-in pattern

If a built-in pattern produces too many false positives for your use case:

```yaml
policies:
  - name: pii-protection
    type: pii
    patterns:
      cc: false          # disable credit card detection
      phone: false       # disable phone number detection
```

Set the pattern name to `false` to disable it. Other built-in patterns remain active.

---

## Parameters reference

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `patterns` | dict | `{}` | Custom patterns (string = regex) or disabled builtins (false) |
| `agents` | list[string] | `[]` | Only apply to these agents. Empty = all agents. |

---

## What gets scanned

- User messages (both string format and content-block array format)
- System prompt content
- All `text` type content blocks

What is **not** scanned:

- Tool results (these are outputs, not inputs to the LLM)
- Image content blocks
- Model name, max_tokens, and other non-content fields

---

## Performance

- Patterns are compiled once at startup (first LLM call)
- Per-call overhead is proportional to message length and number of active patterns
- Typical overhead: < 1ms for messages under 10KB with default patterns
- For high-throughput batch scenarios with large messages, consider disabling patterns you don't need

---

## Examples

### Healthcare application

```yaml
- name: hipaa-pii
  type: pii
  patterns:
    mrn: "\\bMRN[-:]?\\d{6,10}\\b"
    dob: "\\b\\d{2}/\\d{2}/\\d{4}\\b"
    npi: "\\b\\d{10}\\b"
    phone: "\\(\\d{3}\\)\\s?\\d{3}[-.]\\d{4}"
```

### Financial application

```yaml
- name: financial-pii
  type: pii
  patterns:
    account_number: "\\b\\d{8,12}\\b"
    routing_number: "\\b\\d{9}\\b"
    swift_code: "\\b[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?\\b"
    iban: "\\b[A-Z]{2}\\d{2}[A-Z0-9]{4,30}\\b"
```

### Disable for specific agents

If your research agent handles anonymized data and doesn't need PII scanning:

```yaml
- name: pii-for-chatbot-only
  type: pii
  agents: ["chatbot", "support-bot"]
  patterns:
    employee_id: "\\bEMP-\\d{6}\\b"
```

Agents not in the `agents` list are unaffected by this policy.

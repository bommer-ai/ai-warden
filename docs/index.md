# ai-warden

**Governance middleware for LLM agents.**  
Budget control. PII protection. Tool safety. One import. Zero code changes.

---

```bash
pip install aiwarden
```

```python
import aiwarden

# That's it. Every LLM call is now governed.
# PII redacted. Budgets enforced. Tools monitored.
```

---

## What it does

| Problem | ai-warden solves it |
|---------|-------------------|
| Agent burns $500 overnight | Budget caps per agent, team, or user |
| PII leaks to LLM APIs | Regex + custom pattern redaction before the call |
| Agent calls dangerous tools | Block `rm -rf`, `sudo`, file writes — declaratively |
| No visibility into agent runs | Every call logged with cost, latency, tools used |
| Different agents need different rules | Per-agent policy scoping via YAML |

## How it works

```
Your code → client.messages.create()
                    ↓
            ┌── ai-warden ──┐
            │  PRE-HOOKS     │  ← budget check, PII redact, custom rules
            │  LLM CALL      │  ← actual API request
            │  POST-HOOKS    │  ← tool blocking, response filtering
            │  CAPTURE       │  ← event logged (non-blocking)
            └────────────────┘
                    ↓
            Response to your agent
```

## Supports

- **Anthropic** (Claude) — sync, async, streaming, beta
- **OpenAI** (GPT) — sync, streaming
- **Any Python agent framework** — LangChain, CrewAI, AutoGen, custom

## Quick links

- [5-minute Quickstart](getting-started/quickstart.md)
- [Set cost budgets](guides/budget.md)
- [Write custom policies](guides/custom-policies.md)
- [Multi-agent setup](guides/multi-agent.md)

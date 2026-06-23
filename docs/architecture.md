# Architecture

## System flow

```
┌─────────────────────────────────────────────────────────────────┐
│  Your Agent Code                                                 │
│  client.messages.create(model, messages, _agent="chatbot")       │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │   PATCHED create()   │  ← monkey-patched at SDK class level
                    └──────────┬──────────┘
                               │
          ┌────────────────────▼────────────────────┐
          │           POLICY ENGINE (pre)            │
          │                                          │
          │  [p=10] Budget check      → block/pass  │
          │  [p=20] Custom rules      → block/warn  │
          │  [p=90] PII redaction     → modify req  │
          │                                          │
          │  Short-circuits on first Block           │
          └────────────────────┬────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │   REAL LLM API CALL  │  ← stripped of _ prefixed keys
                    └──────────┬──────────┘
                               │
          ┌────────────────────▼────────────────────┐
          │           POLICY ENGINE (post)           │
          │                                          │
          │  [p=20] Custom rules   → block/warn     │
          │  [p=50] Tool safety    → refusal/pass   │
          │                                          │
          └────────────────────┬────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │   EVENT CAPTURE      │  ← non-blocking, background thread
                    │   (RunState update)  │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │   RETURN TO AGENT    │
                    └─────────────────────┘
```

## Run tracking

```
Request #1: messages=[user_msg]              → turn=0 → NEW RunState
Request #2: messages=[user, asst, tool]      → turn=1 → SAME RunState
Request #3: messages=[user, asst, tool, ...] → turn=2 → SAME RunState

Run detection priority:
  1. _agent kwarg / aiwarden.agent() context
  2. OTel trace_id (same trace = same run)
  3. ContextVar heuristic (no assistant msgs = new run)
```

## Module structure

```
aiwarden/
├── __init__.py          → agent(), tag(), configure()
├── config.py            → env vars, runtime config
├── capture.py           → background JSONL writer
├── cost.py              → pricing table + compute_cost()
├── event.py             → LLMEvent, NormalizedRequest/Response
├── session.py           → RunState, ContextVar + OTel tracking
├── patchers/
│   ├── _common.py       → shared build_and_capture()
│   ├── anthropic.py     → Anthropic SDK patcher
│   └── openai.py        → OpenAI SDK patcher
└── policies/
    ├── base.py          → Policy ABC, Block, Warn
    ├── engine.py        → PolicyEngine (priority, agent scoping)
    ├── loader.py        → YAML loading + validation
    ├── builtin/         → pii, budget, tools (shipped defaults)
    └── custom/          → declarative rule engine (user's no-code policies)
```

## Design principles

- **Never crash the user's app** — all errors caught, logged, swallowed
- **Zero config for basic value** — just `pip install` and PII + tool safety is active
- **User brings context** — we provide mechanisms (budget, rules), they configure limits
- **SDK-level patching** — full request/response control, streaming handled
- **Non-blocking capture** — events queued to background thread, no latency added
- **Priority-based short-circuit** — cheap blockers run first, expensive policies only if needed

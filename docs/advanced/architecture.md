# Architecture

## Module structure

```
aiwarden/
├── __init__.py          → agent(), run(), tag(), configure()
├── config.py            → env vars, runtime config
├── capture.py           → background JSONL writer
├── cost.py              → pricing table + compute_cost()
├── event.py             → LLMEvent dataclass
├── session.py           → RunState, ContextVar + OTel tracking
├── runner.py            → Hot mode (aiwarden.run() wrapper)
├── patchers/
│   ├── _common.py       → shared event building
│   ├── anthropic.py     → Anthropic SDK patcher
│   └── openai.py        → OpenAI SDK patcher
└── policies/
    ├── base.py          → Policy ABC, Block, Warn
    ├── engine.py        → PolicyEngine (priority, agent scoping)
    ├── loader.py        → YAML loading + validation
    ├── builtin/         → budget, pii, tools, agent_control
    └── custom/          → declarative rule engine
```

## Auto-activation

`aiwarden.pth` is installed to `site-packages`. Python executes it on startup:

```
Python starts → site module runs .pth files → imports aiwarden.bootstrap
→ detects installed SDKs → patches Messages.create at class level
```

No user import needed. All LLM calls are intercepted from the first one.

## Event capture

Events are enqueued to a thread-safe Queue and flushed by a daemon thread:

- Batch size: 50 events or 2-second timeout
- Non-blocking: `put_nowait()` — never adds latency to LLM calls
- Crash recovery: worker restarts automatically on unexpected errors
- Shutdown: `atexit` handler flushes remaining buffer

## Policy engine

Policies load lazily on first LLM call. Sorted by priority. Pre-hooks short-circuit on block. Post-hooks always run all. Agent scoping filters policies by `_agent` context.

## Supported SDKs

| SDK | Patch target | Streaming |
|-----|-------------|-----------|
| Anthropic | `Messages.create` (class-level) | `_StreamWrapper` with finalize guard |
| OpenAI | `Completions.create` (class-level) | Chunk accumulation + fake response |

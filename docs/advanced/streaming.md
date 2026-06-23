# Streaming

How ai-warden handles streaming LLM calls.

## Pre-hooks: fully enforced

Pre-hooks fire **before** the stream starts. Budget, PII, agent control — all work:

```
create(stream=True) → pre-hooks fire → stream starts (or blocked)
```

If a pre-hook blocks, the stream never starts. Zero tokens.

## Post-hooks: observability + interrupt

Post-hooks fire **after** the stream completes. Two behaviors:

| Action | Works in streaming? | Why |
|--------|-------------------|-----|
| `interrupt` | Yes | Raises exception — agent catches it |
| `warn` | Yes | Logs the warning |
| `refusal` | Partial | Stream already delivered; final message available for inspection |

## For agents

Most agent frameworks don't use streaming for tool loops — they need the complete response to extract tool calls. Pre-hooks and post-hooks both work fully for non-streaming calls, which is the agent's actual execution path.

## Events

Both streaming and non-streaming calls produce identical events. Streaming events are captured on stream completion with `streamed: true`.

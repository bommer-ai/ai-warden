# Hot Mode

Wrap your agent code for exact run tracking — boundaries, topology, metrics.

## Basic usage

```python
import aiwarden

with aiwarden.run(agent="chatbot") as r:
    response = client.messages.create(...)
    response = client.messages.create(...)

# After the run:
print(r.turns)      # 2
print(r.cost)       # $0.0042
print(r.duration)   # 1.8s
print(r.status)     # "completed"
print(r.tools)      # ["search", "book_flight"]
```

## What hot mode adds over zero-touch

| | Zero-touch | Hot mode |
|---|---|---|
| Run start | Detected (heuristic) | Exact |
| Run end | Unknown | Exact |
| Duration | Unavailable | Measured |
| Status | Unavailable | completed / errored |
| Parent-child | Flat | Tree (nested wrappers) |
| Run summary event | Not emitted | Emitted |

## Multi-agent topology

```python
with aiwarden.run(agent="orchestrator") as parent:
    with aiwarden.run(agent="search") as search:
        search_agent.execute(task)

    with aiwarden.run(agent="payment") as payment:
        payment_agent.execute(task)

# parent.children = [search, payment]
# parent.cost = search.cost + payment.cost (auto-accumulated)
# search.parent_id = parent.id
```

## Error tracking

```python
try:
    with aiwarden.run(agent="risky-agent") as r:
        agent.execute(dangerous_task)
except Exception:
    pass

print(r.status)  # "errored"
print(r._error)  # the exception
```

## Run summary event

On exit, hot mode emits a summary event to your log file:

```json
{
  "type": "run_summary",
  "run_id": "abc123",
  "agent": "chatbot",
  "status": "completed",
  "turns": 3,
  "cost": 0.0042,
  "duration_ms": 1800,
  "tools_used": ["search", "book_flight"],
  "children": []
}
```

## When to use hot mode

- You need per-run cost/duration metrics
- You're running multiple agents and want topology
- You need error tracking per run
- You want run summary events in your log

If you just need enforcement (budget, PII, tools) — zero-touch is sufficient.

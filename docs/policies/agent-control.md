# Agent Control

**Type:** `agent_control` | **Priority:** 15 | **Hooks:** pre | **Default:** Disabled

Governs the run itself — how many turns, how much spend, how long, and whether the agent is stuck in a loop. Prevents runaway agents from consuming unlimited resources.

---

## How it works

Agent Control tracks state **per run** (not globally). Each time your agent starts a new task, the counters reset. It checks limits in the pre-hook — before each LLM call — and blocks if any limit is exceeded.

Requires [Hot Mode](../hot-mode.md) (`aiwarden.run()`) for accurate run boundaries. Without it, ai-warden auto-detects runs from request patterns, which may be less precise.

---

## Configuration

```yaml
policies:
  - name: agent-limits
    type: agent_control
    agents: ["chatbot"]
    max_turns: 25
    max_cost: 5.00
    max_duration: 300
    max_tool_repeats: 3
```

---

## Parameters reference

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_turns` | integer | — | Maximum LLM calls allowed in one run. Blocks at turn N+1. |
| `max_cost` | float | — | Maximum dollar spend per run. Blocks when accumulated cost exceeds this. |
| `max_duration` | integer | — | Maximum run duration in seconds. Blocks after this time. |
| `max_tool_repeats` | integer | — | Block when the same tool is called N times consecutively. |
| `agents` | list[string] | `[]` | Only apply to these agents. Empty = all agents. |

All parameters are optional. Only set the limits you care about. Unset limits are not enforced.

---

## What each limit does

### `max_turns`

Counts LLM calls within a single run. Blocks the request at turn N+1:

```
Turn 1: search_flights    ✓
Turn 2: compare_prices    ✓
...
Turn 25: final_response   ✓
Turn 26: another_call     ✗ BLOCKED
```

**Use case:** Prevent agents from going on indefinitely. A well-designed agent should complete its task within a bounded number of turns.

---

### `max_cost`

Tracks dollar cost accumulated within the current run:

```
Turn 1: $0.003  (total: $0.003)  ✓
Turn 2: $0.015  (total: $0.018)  ✓
...
Turn N: $0.12   (total: $5.01)   ✗ BLOCKED
```

**Use case:** Prevent a single task from consuming the entire budget. Different from the `budget` policy which tracks spend across time periods.

---

### `max_duration`

Wall-clock time since the run started:

```
t=0s:   run starts
t=120s: turn 5 → allowed (120 < 300)
t=310s: turn 12 → BLOCKED (310 > 300)
```

**Use case:** Time-bound agent execution. Useful for background tasks that should complete within a window.

---

### `max_tool_repeats`

Detects loops — the same tool called consecutively without progress:

```
search → search → search → search  ← BLOCKED (4 consecutive, limit was 3)
search → calculate → search → search  ← allowed (not consecutive)
```

**Use case:** Agents sometimes get stuck calling the same tool repeatedly with slight variations, expecting different results. This catches that pattern.

---

## Early warnings

At **80%** of any limit, a `warn` event is logged (but the request continues):

```
"Agent approaching turn limit: 20/25"
"Agent approaching cost limit: $4.10/$5.00"
```

This gives you visibility before the hard block fires.

---

## Difference from budget policy

| | `agent_control` | `budget` |
|---|---|---|
| **Scope** | One run (one task) | Across time (daily/monthly) |
| **Tracks** | Turns + cost + duration + loops | Cost only |
| **Resets** | Every new run | On time period boundary |
| **Use case** | "One task shouldn't loop forever" | "Team shouldn't spend $500/month" |
| **Requires** | Hot mode recommended | Works without hot mode |

They complement each other. Use both:

```yaml
policies:
  # Per-run safety net
  - name: agent-limits
    type: agent_control
    max_turns: 50
    max_cost: 10.00

  # Monthly team budget
  - name: team-budget
    type: budget
    group_by: metadata.team
    limits:
      engineering: 500.00
    reset: monthly
```

---

## Examples

### Conservative chatbot

```yaml
- name: chatbot-limits
  type: agent_control
  agents: ["chatbot"]
  max_turns: 10
  max_cost: 1.00
  max_duration: 60
  max_tool_repeats: 2
```

### Long-running researcher

```yaml
- name: researcher-limits
  type: agent_control
  agents: ["researcher"]
  max_turns: 100
  max_cost: 20.00
  max_duration: 1800
  max_tool_repeats: 5
```

### Loop detection only

```yaml
- name: loop-detector
  type: agent_control
  max_tool_repeats: 3
```

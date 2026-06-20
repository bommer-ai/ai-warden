# Python API Reference

## `aiwarden`

```python
import aiwarden
```

| Function | Purpose |
|----------|---------|
| `aiwarden.configure(...)` | Runtime config (enabled, debug, log_file, agent_name) |
| `aiwarden.agent(name)` | Context manager — scope LLM calls to an agent |
| `aiwarden.get_agent()` | Get current agent name from context |
| `aiwarden.tag(**kwargs)` | Context manager — add tags to events |

### `aiwarden.agent(name)`

```python
with aiwarden.agent("chatbot"):
    # All create() calls inside use "chatbot" as agent name
    response = client.messages.create(...)
```

### `aiwarden.tag(**kwargs)`

```python
with aiwarden.tag(feature="onboarding", experiment="v2"):
    response = client.messages.create(...)
    # Event includes tags: {"feature": "onboarding", "experiment": "v2"}
```

---

## `aiwarden.policies`

```python
from aiwarden.policies import register_policy
from aiwarden.policies.base import Policy, Block, Warn, PolicyViolationError
```

### `register_policy(policy)`

```python
from aiwarden.policies import register_policy

register_policy(MyPolicy({"priority": 5, "max_calls": 100}))
```

### `Policy` base class

```python
class MyPolicy(Policy):
    name = "my-policy"
    priority = 50
    default_hooks = ["pre"]        # "pre", "post", or both

    def pre(self, request: dict) -> tuple[dict, Block | Warn | None]:
        if should_block(request):
            return request, Block("reason")
        if should_warn(request):
            return request, Warn("reason")
        return request, None

    def post(self, request: dict, response) -> response:
        # Can modify response or return (response, Warn("..."))
        return response
```

---

## `aiwarden.config`

```python
from aiwarden import config

config.configure(
    enabled=True,
    debug=False,
    log_file="/var/log/aiwarden/events.jsonl",
    caller_tracking=True,
    agent_name="my-service",
)
```

---

## `aiwarden.cost`

```python
from aiwarden.cost import compute_cost, set_pricing

# Override pricing at runtime
set_pricing("my-fine-tuned-model", prompt=0.01, completion=0.03)

# Compute cost
cost = compute_cost("claude-sonnet-4-6", prompt_tokens=1000, completion_tokens=500)
```

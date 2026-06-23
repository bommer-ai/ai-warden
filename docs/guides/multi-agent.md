# Multi-Agent Setup

Different agents, different rules. One config file.

## Assign policies to agents

```yaml title=".aiwarden/policies.yaml"
policies:
  # Global — applies to ALL agents
  - name: pii-protection
    type: pii

  # Chatbot only
  - name: chatbot-budget
    type: budget
    agents: ["chatbot"]
    limit: 50.00
    reset: daily

  # Payment bot only — strict tool control
  - name: payment-safety
    type: tools
    agents: ["payment-bot"]
    rules:
      - name: only-approved-tools
        action: refusal
        message: "Tool not approved for payment processing"
        match:
          tool: "*"
          # block everything except approved tools
        # (use allowlist pattern below instead)

  # Research agent — higher budget, fewer restrictions
  - name: research-budget
    type: budget
    agents: ["research-agent"]
    limit: 200.00
    reset: monthly
```

## Set the agent name

=== "Context manager (recommended)"

    ```python
    import aiwarden

    with aiwarden.agent("chatbot"):
        response = client.messages.create(...)
        # chatbot policies apply

    with aiwarden.agent("payment-bot"):
        response = client.messages.create(...)
        # payment-bot policies apply
    ```

=== "Environment variable"

    ```bash
    export AIWARDEN_AGENT_NAME=chatbot
    python my_chatbot.py
    ```

=== "Startup config"

    ```python
    import aiwarden
    aiwarden.configure(agent_name="payment-bot")
    ```

## Parallel agents (async)

Each async task gets its own scoped agent name:

```python
import asyncio
import aiwarden

async def run_search():
    with aiwarden.agent("search-agent"):
        await search_agent.execute(task)

async def run_payment():
    with aiwarden.agent("payment-bot"):
        await payment_agent.execute(task)

# Both run in parallel with separate policy scopes
async def handle_request(task):
    await asyncio.gather(run_search(), run_payment())
```

## How scoping works

| Policy config | Effect |
|--------------|--------|
| No `agents` field | Applies to **all** agents (global) |
| `agents: ["chatbot"]` | Only runs when agent = "chatbot" |
| `agents: ["a", "b"]` | Runs for agent "a" or "b" |

No agent name set = only global policies run (safe default).

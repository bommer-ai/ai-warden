# Example: Multi-Agent with Separate Budgets

Three agents — chatbot, payment processor, and researcher — each with different budgets, turn limits, and tool restrictions.

---

## Policy file (`.aiwarden/policies.yaml`)

```yaml
policies:
  # ─── Global (all agents) ──────────────────────────────────────
  - name: pii-all
    type: pii
    patterns:
      customer_id: "\\bCUST-\\d{8}\\b"

  # ─── Chatbot: generous budget, basic safety ───────────────────
  - name: chatbot-budget
    type: budget
    agents: ["chatbot"]
    limit: 50.00
    reset: daily

  - name: chatbot-control
    type: agent_control
    agents: ["chatbot"]
    max_turns: 30
    max_tool_repeats: 3

  # ─── Payment bot: tight budget, strict controls ───────────────
  - name: payment-budget
    type: budget
    agents: ["payment-bot"]
    limit: 2.00
    reset: daily

  - name: payment-control
    type: agent_control
    agents: ["payment-bot"]
    max_turns: 5
    max_cost: 0.50

  - name: payment-tools
    type: tools
    agents: ["payment-bot"]
    rules:
      - name: no-large-refund
        action: refusal
        message: "Refunds over $500 require manual approval."
        match:
          tool: process_refund
          amount:
            gt: 500

      - name: no-bulk-transactions
        action: interrupt
        message: "Batch transactions not allowed for this agent."
        match:
          tool: batch_process
          count:
            gt: 10

  # ─── Research agent: high budget, loose controls ──────────────
  - name: research-budget
    type: budget
    agents: ["research-agent"]
    limit: 200.00
    reset: monthly

  - name: research-control
    type: agent_control
    agents: ["research-agent"]
    max_turns: 100
    max_cost: 20.00
    max_duration: 1800
```

---

## Application code

```python
import aiwarden
import anthropic

client = anthropic.Anthropic()

# Each agent is tracked independently
with aiwarden.run(agent="chatbot") as chat_run:
    # All LLM calls here are governed by chatbot policies
    response = client.messages.create(
        model="claude-sonnet-4-6",
        messages=[{"role": "user", "content": user_message}],
    )

with aiwarden.run(agent="payment-bot") as pay_run:
    # Governed by payment-bot policies (tighter limits)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        messages=[{"role": "user", "content": "Process refund for order 123"}],
        tools=[refund_tool, lookup_tool],
    )

with aiwarden.run(agent="research-agent") as research_run:
    # Governed by research-agent policies (generous limits)
    for query in research_queries:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            messages=[{"role": "user", "content": query}],
        )

# After runs complete:
print(f"Chatbot:  ${chat_run.cost:.4f}, {chat_run.turns} turns")
print(f"Payment:  ${pay_run.cost:.4f}, {pay_run.turns} turns")
print(f"Research: ${research_run.cost:.4f}, {research_run.turns} turns")
```

---

## What happens

| Scenario | Agent | Result |
|----------|-------|--------|
| Normal chat | chatbot | Allowed. 12 turns, $0.15. |
| 6th LLM call | payment-bot | Blocked: "Agent exceeded max turns: 5/5" |
| $800 refund | payment-bot | Refusal: "Refunds over $500 require manual approval." |
| Deep research (80 turns) | research-agent | Allowed. Within 100-turn limit. |
| Research hits $20 | research-agent | Blocked: "Run cost exceeded: $20.12 / $20.00" |
| PII in any request | all | Redacted before LLM sees it. |

---

## Key concepts demonstrated

### Agent isolation

Each agent has its own budget counter. Chatbot spending $50 doesn't affect the payment bot's $2 limit. They are completely independent.

### Policy layering

A single request may be checked by multiple policies:

```
payment-bot call:
  [10] payment-budget  → check $2 daily limit
  [15] payment-control → check 5-turn limit
  [50] payment-tools   → check tool restrictions
  [90] pii-all         → redact PII
```

### Graceful degradation

The payment bot sees a refusal message ("manual approval needed") rather than a hard crash. It can inform the user and suggest next steps. Only `interrupt` causes a hard stop.

---

## Without hot mode

If you don't want to add `aiwarden.run()` to your code, use the `_agent` kwarg:

```python
response = client.messages.create(
    model="claude-sonnet-4-6",
    messages=messages,
    _agent="payment-bot",  # stripped before API call
)
```

Or set the env var per-process:

```bash
AIWARDEN_AGENT_NAME=chatbot python chatbot_service.py
AIWARDEN_AGENT_NAME=payment-bot python payment_service.py
```

# Example: Single Agent with Full Protection

A complete setup for a customer support chatbot with PII protection, budget control, tool safety, and run limits.

---

## The application (zero code changes)

```python
import anthropic

client = anthropic.Anthropic()

def answer_question(question: str, team: str = "support") -> str:
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[
            {"role": "system", "content": "You are a helpful support agent."},
            {"role": "user", "content": question},
        ],
        metadata={"team": team},
    )
    return response.content[0].text
```

No imports from ai-warden. No wrappers. No decorators. Your code stays clean.

---

## Policy file (`.aiwarden/policies.yaml`)

```yaml
policies:
  # 1. Redact customer PII before it reaches Claude
  - name: customer-pii
    type: pii
    patterns:
      customer_id: "\\bCUST-\\d{8}\\b"
      order_id: "\\bORD-\\d{10}\\b"
      account_number: "\\b\\d{10}\\b"

  # 2. Daily spend limit — blocks when exceeded
  - name: daily-budget
    type: budget
    limit: 25.00
    reset: daily

  # 3. Per-run limits — prevent runaway agents
  - name: run-limits
    type: agent_control
    max_turns: 15
    max_cost: 2.00
    max_tool_repeats: 3

  # 4. Block dangerous tool calls
  - name: tool-safety
    type: tools
    builtin:
      filesystem-safety: true
      no-privilege-escalation: true
    rules:
      - name: no-bulk-email
        action: refusal
        message: "Cannot send to more than 50 recipients."
        match:
          tool: send_email
          count:
            gt: 50
```

---

## What happens at runtime

### Normal request

```python
answer = answer_question("How do I reset my password?")
# Works normally. Event logged. Cost tracked against $25 daily budget.
```

### PII in the input

```python
answer = answer_question("My account CUST-12345678 has a billing issue")
# Claude sees: "My account [REDACTED:customer_id] has a billing issue"
# Claude responds normally. The real customer ID never leaves your process.
```

### Agent tries a dangerous tool call

```python
# Claude responds with: tool_use(name="bash", input={"command": "rm -rf /data"})
# ai-warden intercepts in post-hook:
#   → Response replaced with: "I'm not allowed to run destructive commands."
#   → Agent retries with a safe alternative.
```

### Budget exceeded

```python
# After $25 of spend today...
try:
    answer = answer_question("Another question")
except PolicyViolationError as e:
    print(e.reason)
    # "Budget exceeded for '__global__': $25.12 / $25.00 (daily)"
    # Claude was NEVER called. Zero tokens consumed.
```

### Agent stuck in a loop

```
Turn 1: search_docs("billing")       ✓
Turn 2: search_docs("billing FAQ")   ✓
Turn 3: search_docs("billing help")  ✗ BLOCKED: "possible loop detected"
```

---

## Handling policy violations

```python
from aiwarden.policies.base import PolicyViolationError

def safe_answer(question: str) -> str:
    try:
        return answer_question(question)
    except PolicyViolationError as e:
        if "Budget exceeded" in e.reason:
            return "I'm currently unavailable. Please try again tomorrow."
        return f"I can't help with that right now: {e.reason}"
```

---

## Install and run

```bash
pip install ai-warden
python your_app.py
```

That's it. ai-warden activates automatically via `.pth` file when Python starts.

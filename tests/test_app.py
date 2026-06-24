"""
Simulates a user's existing app.
NO imports of aiwarden anywhere.
Zero code changes.
"""
import time
from unittest.mock import MagicMock, patch as mock_patch

import openai
import aiwarden.patchers.openai as _patcher   # only for mock injection


def _make_response(content="Paris is the capital of France.",
                   model="gpt-4o", prompt_tokens=120, completion_tokens=18):
    r = MagicMock()
    r.choices[0].message.content    = content
    r.choices[0].message.tool_calls = None
    r.choices[0].finish_reason      = "stop"
    r.usage.prompt_tokens           = prompt_tokens
    r.usage.completion_tokens       = completion_tokens
    return r


# ── user's app functions — completely unchanged ───────────────────────────────

def answer_question(question: str) -> str:
    return openai.chat.completions.create(
        model    = "gpt-4o",
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user",   "content": question},
        ],
    ).choices[0].message.content


def answer_with_user_tag(question: str, user_id: str) -> str:
    return openai.chat.completions.create(
        model    = "gpt-4o",
        messages = [{"role": "user", "content": question}],
        user     = user_id,               # auto-captured as tag
    ).choices[0].message.content


def answer_with_pii(question: str) -> str:
    return openai.chat.completions.create(
        model    = "gpt-4o-mini",
        messages = [{"role": "user", "content": question}],
    ).choices[0].message.content


# ── run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "="*60)
    print("USER APP — no aiwarden imports, zero code changes")
    print("="*60)

    # mock _original inside our patcher — our wrapper still runs
    with mock_patch.object(_patcher, "_original", return_value=_make_response()):

        print("\n[Call 1] Simple question")
        answer_question("What is the capital of France?")

        print("\n[Call 2] With user field — should appear as tag")
        answer_with_user_tag("Tell me a joke", user_id="user_42")

    with mock_patch.object(_patcher, "_original",
                           return_value=_make_response("I can help with that.")):
        print("\n[Call 3] Contains PII — should be redacted in capture")
        answer_with_pii(
            "My email is john.doe@example.com and my phone is 555-867-5309"
        )

    from aiwarden.capture import flush
    flush()
    print("\nDone.")

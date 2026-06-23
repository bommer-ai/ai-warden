"""
Real agent loop test — calls LLM via OpenAI-compatible endpoint to verify
run completion detection.

Run with: python tests/test_real_agent_loop.py

Requires: get-litellm-key available or OPENAI_API_KEY + OPENAI_BASE_URL set.
"""
import json
import os

import openai

from aiwarden.session import _current_run

LITELLM_URL = "https://litellm.kumoroku.com/v1"
MODEL = "claude-haiku-4-5-20251001"


def get_client():
    api_key = os.environ.get("OPENAI_API_KEY") or os.popen(
        "~/.local/bin/get-litellm-key 2>/dev/null"
    ).read().strip()
    base_url = os.environ.get("OPENAI_BASE_URL", LITELLM_URL)
    return openai.OpenAI(api_key=api_key, base_url=base_url)


def run_agent_loop():
    client = get_client()

    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get the current weather for a city.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "City name"}
                    },
                    "required": ["city"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_population",
                "description": "Get the population of a city.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "City name"}
                    },
                    "required": ["city"],
                },
            },
        },
    ]

    messages = [
        {
            "role": "user",
            "content": "Get the weather and population for Tokyo. Use both tools.",
        }
    ]

    print("=" * 60)
    print("AGENT LOOP — real API calls via OpenAI SDK")
    print(f"Model: {MODEL}")
    print("=" * 60)

    turn = 0
    while True:
        turn += 1
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=1024,
            tools=tools,
            messages=messages,
        )

        state = _current_run.get()
        choice = response.choices[0]
        print(f"\nTurn {turn}:")
        print(f"  finish_reason: {choice.finish_reason}")
        print(f"  run_id:        {state.run_id}")
        print(f"  run turn:      {state.turn}")
        print(f"  completed:     {state.completed}")
        print(f"  cost so far:   ${state.total_cost:.6f}")

        if choice.finish_reason == "stop":
            print(f"  response:      {choice.message.content[:100]}")
            break

        # Process tool calls
        if choice.message.tool_calls:
            messages.append(choice.message.model_dump())
            for tc in choice.message.tool_calls:
                fn_name = tc.function.name
                fn_args = json.loads(tc.function.arguments)
                print(f"  tool call:     {fn_name}({json.dumps(fn_args)})")

                if fn_name == "get_weather":
                    result = "Sunny, 28C, humidity 45%"
                elif fn_name == "get_population":
                    result = "13.96 million (2023)"
                else:
                    result = "unknown"

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
        else:
            print(f"  response:      {choice.message.content[:100]}")
            break

    print("\n" + "=" * 60)
    print("RUN 1 COMPLETED")
    print(f"  run_id:    {state.run_id}")
    print(f"  turns:     {state.turn}")
    print(f"  cost:      ${state.total_cost:.6f}")
    print(f"  completed: {state.completed}")
    print("=" * 60)

    first_run_id = state.run_id

    # --- Second run: should get a NEW run_id ---
    print("\n\nStarting second run (new task)...")
    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=256,
        messages=[{"role": "user", "content": "Say hello in Japanese. One word only."}],
    )

    state = _current_run.get()
    text = response.choices[0].message.content

    print(f"\nTurn 1 (new run):")
    print(f"  finish_reason: {response.choices[0].finish_reason}")
    print(f"  run_id:        {state.run_id}")
    print(f"  run turn:      {state.turn}")
    print(f"  completed:     {state.completed}")
    print(f"  response:      {text}")

    print("\n" + "=" * 60)
    print("VERIFICATION")
    print(f"  Run 1 ID:  {first_run_id}")
    print(f"  Run 2 ID:  {state.run_id}")
    print(f"  Different: {first_run_id != state.run_id}")
    print("=" * 60)

    assert first_run_id != state.run_id, "Second run should have a different run_id!"
    print("\nPASSED — run completion detection works correctly.")


if __name__ == "__main__":
    run_agent_loop()

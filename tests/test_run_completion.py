"""
Tests for run completion detection via stop_reason.

Simulates a real agent loop:
  1. Agent calls LLM → LLM says "use tool X" (stop_reason: tool_use)
  2. Agent executes tool, sends result back to LLM
  3. LLM says "use tool Y" (stop_reason: tool_use)
  4. Agent executes tool, sends result back
  5. LLM says "Here's your answer" (stop_reason: end_turn, no tool calls)
  → Run marked completed
  6. Next create() call → new run starts

Also tests:
  - OpenAI finish_reason: "stop" triggers completion
  - tool_use with tool calls does NOT trigger completion
  - max_tokens does NOT trigger completion
  - Consecutive runs get different run_ids
"""
from aiwarden.patchers._common import build_and_capture
from aiwarden.session import RunState, _current_run, get_run_state, _new_run


def _reset_session():
    """Clear session state between tests."""
    _current_run.set(None)


class TestRunCompletion:
    def setup_method(self):
        _reset_session()

    def test_tool_use_does_not_complete_run(self):
        """stop_reason=tool_use with tool calls → run stays active."""
        build_and_capture(
            provider="anthropic",
            kwargs={"model": "claude-sonnet-4-6"},
            messages=[{"role": "user", "content": "search for X"}],
            model="claude-sonnet-4-6",
            text_content="I'll search for that.",
            tool_calls=[{"name": "web_search", "arguments": "{}", "id": "tc1"}],
            finish_reason="tool_use",
            prompt_tokens=100,
            completion_tokens=50,
        )
        state = _current_run.get()
        assert state is not None
        assert state.completed is False
        assert state.turn == 1

    def test_end_turn_with_no_tools_completes_run(self):
        """stop_reason=end_turn with no tool calls → run completed."""
        build_and_capture(
            provider="anthropic",
            kwargs={"model": "claude-sonnet-4-6"},
            messages=[{"role": "user", "content": "hello"}],
            model="claude-sonnet-4-6",
            text_content="Hello! How can I help?",
            tool_calls=[],
            finish_reason="end_turn",
            prompt_tokens=100,
            completion_tokens=20,
        )
        state = _current_run.get()
        assert state is not None
        assert state.completed is True

    def test_openai_stop_completes_run(self):
        """finish_reason=stop (OpenAI) with no tool calls → run completed."""
        build_and_capture(
            provider="openai",
            kwargs={"model": "gpt-4o"},
            messages=[{"role": "user", "content": "hello"}],
            model="gpt-4o",
            text_content="Hi there!",
            tool_calls=[],
            finish_reason="stop",
            prompt_tokens=50,
            completion_tokens=10,
        )
        state = _current_run.get()
        assert state.completed is True

    def test_max_tokens_does_not_complete_run(self):
        """finish_reason=max_tokens → run NOT completed (truncated, not done)."""
        build_and_capture(
            provider="anthropic",
            kwargs={"model": "claude-sonnet-4-6"},
            messages=[{"role": "user", "content": "write a long essay"}],
            model="claude-sonnet-4-6",
            text_content="Here's the beginning...",
            tool_calls=[],
            finish_reason="max_tokens",
            prompt_tokens=100,
            completion_tokens=4096,
        )
        state = _current_run.get()
        assert state.completed is False

    def test_agent_loop_multiple_turns_then_complete(self):
        """Simulates a 4-turn agent loop: 3 tool calls + 1 final response."""
        messages = [{"role": "user", "content": "Book a flight to Paris"}]

        # Turn 1: LLM wants to search flights
        build_and_capture(
            provider="anthropic",
            kwargs={"model": "claude-sonnet-4-6"},
            messages=messages,
            model="claude-sonnet-4-6",
            text_content="Let me search for flights.",
            tool_calls=[{"name": "search_flights", "arguments": "{}", "id": "tc1"}],
            finish_reason="tool_use",
            prompt_tokens=100,
            completion_tokens=30,
        )
        state = _current_run.get()
        run_id = state.run_id
        assert state.turn == 1
        assert state.completed is False

        # Turn 2: LLM wants to compare prices
        messages.append({"role": "assistant", "content": "searching..."})
        messages.append({"role": "user", "content": "[tool result: 3 flights found]"})
        build_and_capture(
            provider="anthropic",
            kwargs={"model": "claude-sonnet-4-6"},
            messages=messages,
            model="claude-sonnet-4-6",
            text_content="Let me compare prices.",
            tool_calls=[{"name": "compare_prices", "arguments": "{}", "id": "tc2"}],
            finish_reason="tool_use",
            prompt_tokens=200,
            completion_tokens=25,
        )
        state = _current_run.get()
        assert state.run_id == run_id
        assert state.turn == 2
        assert state.completed is False

        # Turn 3: LLM wants to book
        messages.append({"role": "assistant", "content": "comparing..."})
        messages.append({"role": "user", "content": "[tool result: cheapest is $450]"})
        build_and_capture(
            provider="anthropic",
            kwargs={"model": "claude-sonnet-4-6"},
            messages=messages,
            model="claude-sonnet-4-6",
            text_content="I'll book the cheapest option.",
            tool_calls=[{"name": "book_flight", "arguments": "{}", "id": "tc3"}],
            finish_reason="tool_use",
            prompt_tokens=300,
            completion_tokens=20,
        )
        state = _current_run.get()
        assert state.run_id == run_id
        assert state.turn == 3
        assert state.completed is False

        # Turn 4: LLM done — final answer
        messages.append({"role": "assistant", "content": "booking..."})
        messages.append({"role": "user", "content": "[tool result: booked!]"})
        build_and_capture(
            provider="anthropic",
            kwargs={"model": "claude-sonnet-4-6"},
            messages=messages,
            model="claude-sonnet-4-6",
            text_content="Done! Your flight to Paris is booked for $450.",
            tool_calls=[],
            finish_reason="end_turn",
            prompt_tokens=400,
            completion_tokens=30,
        )
        state = _current_run.get()
        assert state.run_id == run_id
        assert state.turn == 4
        assert state.completed is True
        assert state.total_cost > 0

    def test_new_run_starts_after_completed(self):
        """After a run completes, the next create() starts a fresh run."""
        # First run: single turn, completes
        build_and_capture(
            provider="anthropic",
            kwargs={"model": "claude-sonnet-4-6"},
            messages=[{"role": "user", "content": "hello"}],
            model="claude-sonnet-4-6",
            text_content="Hi!",
            tool_calls=[],
            finish_reason="end_turn",
            prompt_tokens=50,
            completion_tokens=5,
        )
        first_state = _current_run.get()
        first_run_id = first_state.run_id
        assert first_state.completed is True

        # Second run: new user message → should get a new run_id
        build_and_capture(
            provider="anthropic",
            kwargs={"model": "claude-sonnet-4-6"},
            messages=[{"role": "user", "content": "what's the weather?"}],
            model="claude-sonnet-4-6",
            text_content="It's sunny!",
            tool_calls=[],
            finish_reason="end_turn",
            prompt_tokens=50,
            completion_tokens=10,
        )
        second_state = _current_run.get()
        assert second_state.run_id != first_run_id
        assert second_state.turn == 1
        assert second_state.completed is True

    def test_consecutive_runs_independent_tracking(self):
        """Two consecutive agent loops get independent turn/cost tracking."""
        # Run 1: 2 turns
        build_and_capture(
            provider="anthropic",
            kwargs={"model": "claude-sonnet-4-6"},
            messages=[{"role": "user", "content": "task 1"}],
            model="claude-sonnet-4-6",
            text_content="",
            tool_calls=[{"name": "tool_a", "arguments": "{}", "id": "t1"}],
            finish_reason="tool_use",
            prompt_tokens=100,
            completion_tokens=20,
        )
        messages_r1 = [
            {"role": "user", "content": "task 1"},
            {"role": "assistant", "content": "..."},
            {"role": "user", "content": "[result]"},
        ]
        build_and_capture(
            provider="anthropic",
            kwargs={"model": "claude-sonnet-4-6"},
            messages=messages_r1,
            model="claude-sonnet-4-6",
            text_content="Done with task 1.",
            tool_calls=[],
            finish_reason="end_turn",
            prompt_tokens=150,
            completion_tokens=15,
        )
        run1_state = _current_run.get()
        assert run1_state.turn == 2
        assert run1_state.completed is True
        run1_id = run1_state.run_id

        # Run 2: starts fresh
        build_and_capture(
            provider="anthropic",
            kwargs={"model": "claude-sonnet-4-6"},
            messages=[{"role": "user", "content": "task 2"}],
            model="claude-sonnet-4-6",
            text_content="Done with task 2.",
            tool_calls=[],
            finish_reason="end_turn",
            prompt_tokens=80,
            completion_tokens=10,
        )
        run2_state = _current_run.get()
        assert run2_state.run_id != run1_id
        assert run2_state.turn == 1
        assert run2_state.completed is True

"""
Tests for run tracking: ContextVar + OTel trace_id signal.

Scenarios:
  1. Single agent run → one run_id, turns increment
  2. Two runs back-to-back (no OTel) → different run_ids
  3. Multi-agent flow (same OTel trace) → SAME run_id
  4. Sequential requests (different OTel traces) → different run_ids
  5. _run_id override
"""
import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from aiwarden import config
from aiwarden import session
from aiwarden.session import _current_run, _last_otel_trace, get_run_state, RunState


def _make_tool_response(tool_name, tool_input, input_tokens=100, output_tokens=50):
    return SimpleNamespace(
        id=f"msg_{uuid4().hex[:24]}", model="claude-sonnet-4-6",
        role="assistant", type="message", stop_reason="tool_use",
        content=[SimpleNamespace(type="tool_use", id=f"toolu_{uuid4().hex[:24]}",
                                 name=tool_name, input=tool_input)],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def _make_text_response(text, input_tokens=100, output_tokens=30):
    return SimpleNamespace(
        id=f"msg_{uuid4().hex[:24]}", model="claude-sonnet-4-6",
        role="assistant", type="message", stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


@pytest.fixture(autouse=True)
def _reset_session():
    """Reset session state before each test."""
    _current_run.set(None)
    _last_otel_trace.set(None)
    yield
    _current_run.set(None)
    _last_otel_trace.set(None)


class TestRunStateHeuristic:
    """Run detection without OTel (turn==0 heuristic)."""

    def test_first_call_creates_new_run(self):
        messages = [{"role": "user", "content": "hello"}]
        state = get_run_state({}, messages)
        assert state.run_id is not None
        assert state.turn == 0

    def test_second_call_with_assistant_continues_run(self):
        messages = [{"role": "user", "content": "hi"}]
        state1 = get_run_state({}, messages)
        rid1 = state1.run_id

        messages_with_assistant = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {"role": "user", "content": "more"},
        ]
        state2 = get_run_state({}, messages_with_assistant)
        assert state2.run_id == rid1

    def test_fresh_messages_starts_new_run(self):
        messages = [{"role": "user", "content": "first task"}]
        state1 = get_run_state({}, messages)
        rid1 = state1.run_id

        _current_run.set(None)
        new_messages = [{"role": "user", "content": "second task"}]
        state2 = get_run_state({}, new_messages)
        assert state2.run_id != rid1


class TestOTelTraceDetection:
    """Run detection using OTel trace_id as change signal."""

    def test_same_trace_same_run(self):
        trace = "aaaa1111bbbb2222cccc3333dddd4444"
        messages = [{"role": "user", "content": "hi"}]

        with patch('aiwarden.session._get_otel_trace_id', return_value=trace):
            state1 = get_run_state({}, messages)
            state2 = get_run_state({}, messages)

        assert state1.run_id == state2.run_id

    def test_different_trace_new_run(self):
        messages = [{"role": "user", "content": "hi"}]

        with patch('aiwarden.session._get_otel_trace_id', return_value="trace_aaa"):
            state1 = get_run_state({}, messages)

        with patch('aiwarden.session._get_otel_trace_id', return_value="trace_bbb"):
            state2 = get_run_state({}, messages)

        assert state1.run_id != state2.run_id

    def test_multi_agent_same_trace_shares_run(self):
        """Two agents in the same OTel trace share one run_id."""
        trace = "shared_trace_12345678901234567890"
        messages_a = [{"role": "user", "content": "agent A"}]
        messages_b = [{"role": "user", "content": "agent B"}]

        with patch('aiwarden.session._get_otel_trace_id', return_value=trace):
            state_a = get_run_state({}, messages_a)
            state_b = get_run_state({}, messages_b)

        assert state_a.run_id == state_b.run_id


class TestRunIdOverride:
    """Explicit _run_id kwarg override."""

    def test_run_id_override(self):
        messages = [{"role": "user", "content": "hi"}]
        state = get_run_state({"_run_id": "custom-run-99"}, messages)
        assert state.run_id == "custom-run-99"

    def test_run_id_override_persists(self):
        messages = [{"role": "user", "content": "hi"}]
        state1 = get_run_state({"_run_id": "my-run"}, messages)
        state2 = get_run_state({"_run_id": "my-run"}, messages)
        assert state1.run_id == state2.run_id == "my-run"

    def test_different_run_id_creates_new_state(self):
        messages = [{"role": "user", "content": "hi"}]
        state1 = get_run_state({"_run_id": "run-1"}, messages)
        state2 = get_run_state({"_run_id": "run-2"}, messages)
        assert state1.run_id != state2.run_id


class TestTurnCounting:
    """Turn counter increments correctly."""

    def test_turn_increments(self):
        from aiwarden.session import increment_turn
        state = RunState(run_id="test")
        assert state.turn == 0
        increment_turn(state)
        assert state.turn == 1
        increment_turn(state)
        assert state.turn == 2

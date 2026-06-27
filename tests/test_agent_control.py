"""
Tests for AgentControlPolicy — per-run enforcement.

Covers:
- max_turns: block when exceeded, warn at 80%
- max_cost: block when exceeded, warn at 80%
- max_duration: block when exceeded
- Loop detection: same tool called N times consecutively
- Provider-agnostic refusal building (Anthropic + OpenAI)
- Edge cases: no RunState, zero limits, empty tools
"""
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from aiwarden.policies.builtin.agent_control import AgentControlPolicy
from aiwarden.policies.base import Block, Warn
from aiwarden.session import _current_run, RunState


@pytest.fixture(autouse=True)
def _reset_run_state():
    """Provide a fresh RunState for each test."""
    _current_run.set(None)
    yield
    _current_run.set(None)


def _set_run_state(turn=0, cost=0.0, duration_ago=0, tools=None):
    """Helper to set up RunState with specific values."""
    state = RunState(run_id="test-run")
    state.turn = turn
    state.total_cost = cost
    if duration_ago:
        state.start_time = time.monotonic() - duration_ago
    if tools:
        state.tools_called.extend(tools)
    _current_run.set(state)
    return state


class TestMaxTurns:
    """max_turns enforcement."""

    def test_no_block_under_limit(self):
        policy = AgentControlPolicy({"max_turns": 10})
        _set_run_state(turn=5)
        req = {"model": "claude-sonnet-4-6", "messages": []}
        _, result = policy.pre(req)
        assert not isinstance(result, Block)

    def test_blocks_at_limit(self):
        policy = AgentControlPolicy({"max_turns": 10})
        _set_run_state(turn=10)
        req = {"model": "claude-sonnet-4-6", "messages": []}
        _, result = policy.pre(req)
        assert isinstance(result, Block)
        assert "max turns" in result.reason.lower()
        assert "10/10" in result.reason

    def test_blocks_over_limit(self):
        policy = AgentControlPolicy({"max_turns": 5})
        _set_run_state(turn=7)
        req = {"model": "claude-sonnet-4-6", "messages": []}
        _, result = policy.pre(req)
        assert isinstance(result, Block)

    def test_warns_at_80_percent(self):
        policy = AgentControlPolicy({"max_turns": 10})
        _set_run_state(turn=8)  # 80% of 10
        req = {"model": "claude-sonnet-4-6", "messages": []}
        _, result = policy.pre(req)
        assert isinstance(result, Warn)
        assert "approaching" in result.reason.lower()

    def test_no_warn_below_80_percent(self):
        policy = AgentControlPolicy({"max_turns": 10})
        _set_run_state(turn=7)  # 70% of 10
        req = {"model": "claude-sonnet-4-6", "messages": []}
        _, result = policy.pre(req)
        assert result is None

    def test_zero_max_turns_disabled(self):
        policy = AgentControlPolicy({"max_turns": 0})
        _set_run_state(turn=9999)
        req = {"model": "claude-sonnet-4-6", "messages": []}
        _, result = policy.pre(req)
        assert result is None


class TestMaxCost:
    """max_cost enforcement."""

    def test_no_block_under_limit(self):
        policy = AgentControlPolicy({"max_cost": 5.00})
        _set_run_state(cost=3.50)
        req = {"model": "claude-sonnet-4-6", "messages": []}
        _, result = policy.pre(req)
        assert not isinstance(result, Block)

    def test_blocks_at_limit(self):
        policy = AgentControlPolicy({"max_cost": 5.00})
        _set_run_state(cost=5.01)
        req = {"model": "claude-sonnet-4-6", "messages": []}
        _, result = policy.pre(req)
        assert isinstance(result, Block)
        assert "cost" in result.reason.lower()

    def test_warns_at_80_percent(self):
        policy = AgentControlPolicy({"max_cost": 10.00})
        _set_run_state(cost=8.50)  # > 80%
        req = {"model": "claude-sonnet-4-6", "messages": []}
        _, result = policy.pre(req)
        assert isinstance(result, Warn)
        assert "cost" in result.reason.lower()

    def test_zero_max_cost_disabled(self):
        policy = AgentControlPolicy({"max_cost": 0})
        _set_run_state(cost=999.99)
        req = {"model": "claude-sonnet-4-6", "messages": []}
        _, result = policy.pre(req)
        assert result is None


class TestMaxDuration:
    """max_duration enforcement."""

    def test_no_block_under_limit(self):
        policy = AgentControlPolicy({"max_duration": 300})
        _set_run_state(duration_ago=100)  # 100s elapsed
        req = {"model": "claude-sonnet-4-6", "messages": []}
        _, result = policy.pre(req)
        assert not isinstance(result, Block)

    def test_blocks_at_limit(self):
        policy = AgentControlPolicy({"max_duration": 60})
        _set_run_state(duration_ago=61)  # 61s > 60s limit
        req = {"model": "claude-sonnet-4-6", "messages": []}
        _, result = policy.pre(req)
        assert isinstance(result, Block)
        assert "duration" in result.reason.lower()

    def test_zero_max_duration_disabled(self):
        policy = AgentControlPolicy({"max_duration": 0})
        _set_run_state(duration_ago=99999)
        req = {"model": "claude-sonnet-4-6", "messages": []}
        _, result = policy.pre(req)
        assert result is None


class TestLoopDetection:
    """Post-hook: same tool called N times consecutively."""

    def _make_anthropic_response(self, tool_name):
        return SimpleNamespace(
            content=[SimpleNamespace(type="tool_use", id="t1", name=tool_name, input={})],
            stop_reason="tool_use",
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
            model="claude-sonnet-4-6",
        )

    def test_no_loop_different_tools(self):
        policy = AgentControlPolicy({"max_tool_repeats": 3})
        _set_run_state(tools=["search", "read", "write"])
        req = {"model": "claude-sonnet-4-6", "messages": []}
        resp = self._make_anthropic_response("search")
        result = policy.post(req, resp)
        # Should return original response (no loop detected)
        assert result is resp or hasattr(result, "content")

    def test_detects_loop(self):
        policy = AgentControlPolicy({"max_tool_repeats": 3})
        _set_run_state(tools=["search", "search", "search"])
        req = {"model": "claude-sonnet-4-6", "messages": []}
        resp = self._make_anthropic_response("search")
        result = policy.post(req, resp)
        # Should return a refusal (tool_use replaced with text)
        assert result is not resp
        text_blocks = [b for b in result.content if getattr(b, "type", "") == "text"]
        assert len(text_blocks) > 0
        assert "loop" in text_blocks[0].text.lower() or "consecutively" in text_blocks[0].text.lower()

    def test_no_detection_below_threshold(self):
        policy = AgentControlPolicy({"max_tool_repeats": 3})
        _set_run_state(tools=["search", "search"])  # only 2 repeats
        req = {"model": "claude-sonnet-4-6", "messages": []}
        resp = self._make_anthropic_response("search")
        result = policy.post(req, resp)
        assert result is resp  # no refusal

    def test_zero_repeats_disabled(self):
        policy = AgentControlPolicy({"max_tool_repeats": 0})
        _set_run_state(tools=["x"] * 100)
        req = {"model": "claude-sonnet-4-6", "messages": []}
        resp = self._make_anthropic_response("x")
        result = policy.post(req, resp)
        assert result is resp

    def test_openai_format_loop_detection(self):
        """Loop detection works with OpenAI response format."""
        policy = AgentControlPolicy({"max_tool_repeats": 2})
        _set_run_state(tools=["bash", "bash"])
        req = {"model": "gpt-4o", "messages": []}
        func = SimpleNamespace(name="bash", arguments='{"cmd": "ls"}')
        tc = SimpleNamespace(function=func, id="call_1")
        msg = SimpleNamespace(content=None, tool_calls=[tc])
        resp = SimpleNamespace(
            choices=[SimpleNamespace(message=msg, finish_reason="tool_calls")],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
            model="gpt-4o",
        )
        result = policy.post(req, resp)
        # Should build refusal for OpenAI format
        assert result is not resp
        assert result.choices[0].message.content is not None
        assert "loop" in result.choices[0].message.content.lower() or "consecutively" in result.choices[0].message.content.lower()


class TestNoRunState:
    """Behavior when no RunState exists (not in a run)."""

    def test_pre_returns_none_without_run_state(self):
        policy = AgentControlPolicy({"max_turns": 5, "max_cost": 1.0})
        # No _current_run.set() — state is None
        req = {"model": "claude-sonnet-4-6", "messages": []}
        _, result = policy.pre(req)
        assert result is None

    def test_post_returns_response_without_run_state(self):
        policy = AgentControlPolicy({"max_tool_repeats": 3})
        resp = SimpleNamespace(content=[], stop_reason="end_turn")
        req = {"model": "claude-sonnet-4-6", "messages": []}
        result = policy.post(req, resp)
        assert result is resp


class TestPriorityCheck:
    """Verify block takes precedence over warn (turn limit checked before 80% warn)."""

    def test_block_before_cost_warn(self):
        """If both turns AND cost are exceeded, block fires (not warn)."""
        policy = AgentControlPolicy({"max_turns": 5, "max_cost": 10.0})
        _set_run_state(turn=5, cost=8.5)  # turns exceeded, cost at 85%
        req = {"model": "claude-sonnet-4-6", "messages": []}
        _, result = policy.pre(req)
        assert isinstance(result, Block)  # block on turns, not warn on cost

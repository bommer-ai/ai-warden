"""
Tests for hot mode: aiwarden.run()

Covers:
  1. Single run — turns, cost, duration tracked
  2. Multi-agent nested runs — parent-child topology
  3. Run with error — status = "errored"
  4. Per-run policies (run.turns, run.cost limits)
  5. Run summary event emitted
"""
import time
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

import anthropic
import aiwarden
import aiwarden.patchers.anthropic as anthropic_patcher
from aiwarden import config
from aiwarden.patchers.anthropic import patch as patch_anthropic
from aiwarden.policies import engine as policy_engine
from aiwarden.policies.custom import CustomPolicy


def _make_response(text="OK", input_tokens=100, output_tokens=50, stop_reason="end_turn"):
    return SimpleNamespace(
        id=f"msg_{uuid4().hex[:24]}", model="claude-sonnet-4-6",
        role="assistant", type="message", stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def _make_tool_response(tool_name, tool_input, input_tokens=100, output_tokens=50):
    return SimpleNamespace(
        id=f"msg_{uuid4().hex[:24]}", model="claude-sonnet-4-6",
        role="assistant", type="message", stop_reason="tool_use",
        content=[SimpleNamespace(type="tool_use", id=f"toolu_{uuid4().hex[:24]}",
                                 name=tool_name, input=tool_input)],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


@pytest.fixture(autouse=True)
def _setup_patcher():
    """Ensure Anthropic patcher is active for all tests."""
    anthropic_patcher._patched = False
    patch_anthropic(anthropic)
    config.ENABLED = True
    config.LOG_FILE = "/tmp/test_hotmode_events.jsonl"
    yield


class TestBasicRun:
    """Single run: turns, cost, duration tracked."""

    def test_run_tracks_turns_and_cost(self):
        responses = [
            _make_tool_response("search", {"q": "test"}),
            _make_response("Found results!", input_tokens=200, output_tokens=80),
        ]
        idx = [0]
        def mock(self, *a, **kw):
            r = responses[idx[0]]; idx[0] += 1; return r

        with patch.object(anthropic_patcher, '_original_create', mock):
            with aiwarden.run(agent="test-agent") as r:
                messages = [{"role": "user", "content": "Search for test"}]
                client = anthropic.Anthropic(api_key="fake")
                client.messages.create(model="claude-sonnet-4-6", max_tokens=100, messages=messages)
                messages.append({"role": "assistant", "content": [{"type": "tool_use", "id": "x", "name": "search", "input": {}}]})
                messages.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": "OK"}]})
                client.messages.create(model="claude-sonnet-4-6", max_tokens=100, messages=messages)

        assert r.agent == "test-agent"
        assert r.turns == 2
        assert r.cost > 0
        assert r.status == "completed"
        assert "search" in r.tools


class TestNestedRuns:
    """Multi-agent nested runs: parent-child topology."""

    def test_nested_runs_accumulate_cost(self):
        responses = [
            _make_response("Search done", input_tokens=100, output_tokens=30),
            _make_response("Payment done", input_tokens=150, output_tokens=40),
        ]
        idx = [0]
        def mock(self, *a, **kw):
            r = responses[idx[0]]; idx[0] += 1; return r

        with patch.object(anthropic_patcher, '_original_create', mock):
            with aiwarden.run(agent="orchestrator") as parent:
                client = anthropic.Anthropic(api_key="fake")
                with aiwarden.run(agent="search-agent") as child1:
                    client.messages.create(model="claude-sonnet-4-6", max_tokens=100,
                                           messages=[{"role": "user", "content": "search"}])
                with aiwarden.run(agent="payment-agent") as child2:
                    client.messages.create(model="claude-sonnet-4-6", max_tokens=100,
                                           messages=[{"role": "user", "content": "pay"}])

        assert len(parent.children) == 2
        assert child1.parent_id == parent.id
        assert child2.parent_id == parent.id
        assert parent.cost == child1.cost + child2.cost


class TestRunErrors:
    """Run with error — status tracking."""

    def test_error_sets_status_errored(self):
        def mock_error(self, *a, **kw):
            raise RuntimeError("API timeout")

        with patch.object(anthropic_patcher, '_original_create', mock_error):
            try:
                with aiwarden.run(agent="failing-agent") as error_run:
                    client = anthropic.Anthropic(api_key="fake")
                    client.messages.create(model="claude-sonnet-4-6", max_tokens=100,
                                           messages=[{"role": "user", "content": "hi"}])
            except RuntimeError:
                pass

        assert error_run.status == "errored"
        assert "timeout" in str(error_run._error)


class TestPerRunPolicies:
    """Per-run policies enforce turn limits."""

    def test_blocks_after_max_turns(self):
        policy_engine._policies = [CustomPolicy({
            "name": "max-turns", "priority": 5,
            "rules": [{"name": "limit", "hook": "pre", "action": "block",
                       "message": "exceeded", "match": {"run.turns": {"gte": 2}}}],
        })]

        responses = [_make_response(f"Response {i}") for i in range(5)]
        idx = [0]
        def mock(self, *a, **kw):
            r = responses[idx[0]]; idx[0] += 1; return r

        blocked = False
        with patch.object(anthropic_patcher, '_original_create', mock):
            with aiwarden.run(agent="limited") as run:
                client = anthropic.Anthropic(api_key="fake")
                messages = [{"role": "user", "content": "hi"}]
                client.messages.create(model="claude-sonnet-4-6", max_tokens=100, messages=messages)
                client.messages.create(model="claude-sonnet-4-6", max_tokens=100, messages=messages)
                try:
                    client.messages.create(model="claude-sonnet-4-6", max_tokens=100, messages=messages)
                except Exception:
                    blocked = True

        assert blocked
        assert run.turns >= 2

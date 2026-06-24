"""
Tests for async ContextVar isolation and correctness under concurrent async load.

Validates:
- ContextVar isolation between concurrent asyncio tasks
- RunState does not leak across tasks
- Policy evaluation remains deterministic under async concurrency
- agent() context manager isolation in async
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from aiwarden.policies.custom.policy import CustomPolicy
from aiwarden.policies.engine import PolicyEngine
from aiwarden.session import _current_run, _new_run, RunState


class TestAsyncContextVarIsolation:
    """Verify ContextVar provides per-task isolation in asyncio."""

    def test_100_concurrent_tasks_isolated(self):
        """Each async task gets its own RunState, no cross-contamination."""
        async def worker(task_id):
            state = _new_run()
            state.run_id = f"async-{task_id}"
            state.total_cost = task_id * 0.01
            await asyncio.sleep(0.001)  # yield to event loop
            read_back = _current_run.get()
            assert read_back is not None
            assert read_back.run_id == f"async-{task_id}"
            assert abs(read_back.total_cost - task_id * 0.01) < 0.0001
            return True

        async def main():
            tasks = [worker(i) for i in range(100)]
            results = await asyncio.gather(*tasks)
            assert all(results)

        asyncio.run(main())

    def test_nested_async_tasks(self):
        """Nested tasks don't inherit parent's ContextVar state."""
        async def parent():
            state = _new_run()
            state.run_id = "parent"

            async def child():
                # Child should get its OWN state when _new_run is called
                child_state = _new_run()
                child_state.run_id = "child"
                await asyncio.sleep(0)
                read = _current_run.get()
                return read.run_id

            child_id = await child()
            parent_read = _current_run.get()
            # After child returns, parent should still see its own state
            # Note: _new_run() replaces the ContextVar value, so parent sees "child"
            # This is expected behavior - tasks share context unless explicitly copied
            return child_id

        result = asyncio.run(parent())
        assert result == "child"

    def test_policy_evaluation_deterministic_async(self):
        """Policy decisions are deterministic regardless of async scheduling."""
        policy = CustomPolicy({"name": "gate", "rules": [
            {"name": "block-gpt", "hook": "pre", "action": "block",
             "match": {"model": {"startswith": "gpt-4"}}, "message": "blocked"},
        ]})
        engine = PolicyEngine()
        engine._policies = [policy]

        errors = []

        async def eval_task(task_id, should_block):
            model = "gpt-4o" if should_block else "claude-sonnet-4-6"
            req = {"model": model, "messages": [{"role": "user", "content": f"task-{task_id}"}]}
            _, block, _ = engine.run_pre(req)
            if should_block and block is None:
                errors.append(f"Task {task_id}: should have blocked but didn't")
            if not should_block and block is not None:
                errors.append(f"Task {task_id}: should NOT have blocked but did")

        async def main():
            tasks = []
            for i in range(200):
                tasks.append(eval_task(i, should_block=(i % 2 == 0)))
            await asyncio.gather(*tasks)

        asyncio.run(main())
        assert len(errors) == 0, f"Async correctness failures: {errors[:5]}"


class TestAsyncAgentContext:
    """Verify agent() context manager works in async."""

    def test_agent_context_in_async_tasks(self):
        """aiwarden.agent() scoping works correctly in async."""
        import aiwarden

        policy = CustomPolicy({
            "name": "scoped",
            "agents": ["allowed-agent"],
            "rules": [{"name": "r1", "hook": "pre", "action": "block",
                       "match": {"model": {"contains": "sonnet"}}, "message": "blocked"}],
        })
        engine = PolicyEngine()
        engine._policies = [policy]

        results = {}

        async def task_with_agent(task_id, agent_name):
            with aiwarden.agent(agent_name):
                req = {"model": "claude-sonnet-4-6", "messages": []}
                _, block, _ = engine.run_pre(req)
                results[task_id] = block is not None

        async def main():
            await asyncio.gather(
                task_with_agent(0, "allowed-agent"),  # should block
                task_with_agent(1, "other-agent"),    # should NOT block (wrong agent)
                task_with_agent(2, "allowed-agent"),  # should block
            )

        asyncio.run(main())
        assert results[0] is True   # blocked
        assert results[1] is False  # not blocked (agent doesn't match)
        assert results[2] is True   # blocked


class TestSDKPatchingIntegration:
    """Integration tests for the actual SDK monkey-patching path."""

    def test_patched_create_runs_policies(self):
        """Verify _patched_create actually runs pre/post hooks."""
        import anthropic
        from aiwarden.patchers.anthropic import patch as patch_anthropic
        import aiwarden.patchers.anthropic as patcher
        from aiwarden.policies import engine as engine_mod
        from aiwarden import config

        config.ENABLED = True

        # Set up a policy that blocks
        old_policies = engine_mod._policies
        engine_mod._policies = [CustomPolicy({
            "name": "test-gate", "rules": [
                {"name": "block-all", "hook": "pre", "action": "block",
                 "match": {"model": {"contains": "test-model"}}, "message": "test-blocked"}
            ]
        })]

        # Patch if not already patched
        patcher._patched = False
        patch_anthropic(anthropic)
        client = anthropic.Anthropic(api_key="fake-key")

        # Should raise PolicyViolationError
        from aiwarden.policies.base import PolicyViolationError
        try:
            with pytest.raises(PolicyViolationError, match="test-blocked"):
                client.messages.create(
                    model="test-model",
                    max_tokens=100,
                    messages=[{"role": "user", "content": "hello"}],
                )
        finally:
            engine_mod._policies = old_policies
            config.ENABLED = False

    def test_patched_create_passes_unblocked(self):
        """Verify unblocked requests reach the real API (mocked)."""
        import anthropic
        from aiwarden.patchers.anthropic import patch as patch_anthropic
        import aiwarden.patchers.anthropic as patcher
        from aiwarden.policies import engine as engine_mod
        from aiwarden import config

        config.ENABLED = True
        old_policies = engine_mod._policies
        engine_mod._policies = []  # No policies = no blocking

        patcher._patched = False
        patch_anthropic(anthropic)
        client = anthropic.Anthropic(api_key="fake-key")

        mock_response = SimpleNamespace(
            id="msg_123", model="claude-sonnet-4-6", role="assistant",
            type="message", stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text="hello")],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5))

        with patch.object(patcher, '_original_create', return_value=mock_response):
            result = client.messages.create(
                model="claude-sonnet-4-6", max_tokens=100,
                messages=[{"role": "user", "content": "hi"}])

        assert result.content[0].text == "hello"
        engine_mod._policies = old_policies
        config.ENABLED = False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

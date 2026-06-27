"""
Memory growth tests.

Measures:
- Budget policy spend dict growth with many groups
- RunState tools_called list growth
- Event queue growth under load (without draining)
- Policy engine with large rule sets (memory footprint)
"""
import sys
import threading
import time
import tracemalloc

import pytest

from aiwarden.policies.builtin.budget import BudgetPolicy
from aiwarden.policies.builtin.pii import PIIPolicy
from aiwarden.policies.custom.policy import CustomPolicy
from aiwarden.policies.engine import PolicyEngine
from aiwarden.session import RunState

from benchmarks.conftest import (
    generate_custom_rules,
    generate_pii_patterns,
    make_request,
)


def get_size_mb(obj):
    return sys.getsizeof(obj) / (1024 * 1024)


class TestBudgetMemory:
    """Budget policy spend tracking memory growth."""

    def test_1000_groups_memory(self):
        policy = BudgetPolicy({"limit": 1000.0, "group_by": "metadata.team", "reset": "monthly"})
        tracemalloc.start()
        snapshot_before = tracemalloc.take_snapshot()

        for i in range(1000):
            request = {"metadata": {"team": f"team-{i}"}, "model": "claude-sonnet-4-6"}
            policy._add_spend(f"team-{i}", 0.01)

        snapshot_after = tracemalloc.take_snapshot()
        tracemalloc.stop()

        stats = snapshot_after.compare_to(snapshot_before, "lineno")
        total_growth = sum(s.size_diff for s in stats if s.size_diff > 0)
        growth_kb = total_growth / 1024

        print(f"\n  Budget: 1000 groups memory growth: {growth_kb:.1f}KB")
        assert growth_kb < 500

    def test_10000_groups_memory(self):
        policy = BudgetPolicy({"limit": 1000.0, "group_by": "metadata.team", "reset": "monthly"})
        tracemalloc.start()
        snapshot_before = tracemalloc.take_snapshot()

        for i in range(10_000):
            policy._add_spend(f"team-{i}", 0.01)

        snapshot_after = tracemalloc.take_snapshot()
        tracemalloc.stop()

        stats = snapshot_after.compare_to(snapshot_before, "lineno")
        total_growth = sum(s.size_diff for s in stats if s.size_diff > 0)
        growth_kb = total_growth / 1024

        print(f"\n  Budget: 10000 groups memory growth: {growth_kb:.1f}KB")
        assert growth_kb < 5000

    def test_concurrent_budget_no_corruption(self):
        policy = BudgetPolicy({"limit": 999999.0, "group_by": "metadata.team", "reset": "monthly"})
        errors = []

        def worker(group_id):
            try:
                for _ in range(100):
                    policy._add_spend(f"group-{group_id}", 0.001)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        total_spend = sum(
            periods.get(policy._current_period(), 0.0)
            for periods in policy._spend.values()
        )
        expected = 50 * 100 * 0.001
        assert abs(total_spend - expected) < 0.001, f"Expected ~{expected}, got {total_spend}"
        print(f"\n  Concurrent budget: 50 threads x 100 ops = {total_spend:.3f} (expected {expected:.3f})")


class TestRunStateMemory:
    """RunState tools_called growth."""

    def test_10000_tools_memory(self):
        state = RunState(run_id="bench-run")
        tracemalloc.start()
        snapshot_before = tracemalloc.take_snapshot()

        for i in range(10_000):
            state.tools_called.append(f"tool_{i % 100}")

        snapshot_after = tracemalloc.take_snapshot()
        tracemalloc.stop()

        stats = snapshot_after.compare_to(snapshot_before, "lineno")
        total_growth = sum(s.size_diff for s in stats if s.size_diff > 0)
        growth_kb = total_growth / 1024

        print(f"\n  RunState: 10K appends, capped at {len(state.tools_called)} entries: {growth_kb:.1f}KB")
        assert growth_kb < 200  # bounded by maxlen
        from aiwarden.session import _MAX_TOOLS_TRACKED
        assert len(state.tools_called) == _MAX_TOOLS_TRACKED


class TestPolicyMemoryFootprint:
    """Memory footprint of policy rule sets."""

    def test_100_rules_footprint(self):
        tracemalloc.start()
        snapshot_before = tracemalloc.take_snapshot()

        policy = CustomPolicy({"name": "bench", "rules": generate_custom_rules(100)})

        snapshot_after = tracemalloc.take_snapshot()
        tracemalloc.stop()

        stats = snapshot_after.compare_to(snapshot_before, "lineno")
        total_growth = sum(s.size_diff for s in stats if s.size_diff > 0)
        growth_kb = total_growth / 1024

        print(f"\n  CustomPolicy: 100 rules footprint: {growth_kb:.1f}KB")
        assert growth_kb < 500

    def test_1000_rules_footprint(self):
        tracemalloc.start()
        snapshot_before = tracemalloc.take_snapshot()

        policy = CustomPolicy({"name": "bench", "rules": generate_custom_rules(1000)})

        snapshot_after = tracemalloc.take_snapshot()
        tracemalloc.stop()

        stats = snapshot_after.compare_to(snapshot_before, "lineno")
        total_growth = sum(s.size_diff for s in stats if s.size_diff > 0)
        growth_kb = total_growth / 1024

        print(f"\n  CustomPolicy: 1000 rules footprint: {growth_kb:.1f}KB")
        assert growth_kb < 5000

    def test_pii_15_patterns_footprint(self):
        tracemalloc.start()
        snapshot_before = tracemalloc.take_snapshot()

        policy = PIIPolicy({"patterns": generate_pii_patterns(10)})

        snapshot_after = tracemalloc.take_snapshot()
        tracemalloc.stop()

        stats = snapshot_after.compare_to(snapshot_before, "lineno")
        total_growth = sum(s.size_diff for s in stats if s.size_diff > 0)
        growth_kb = total_growth / 1024

        print(f"\n  PIIPolicy: 15 compiled patterns footprint: {growth_kb:.1f}KB")
        assert growth_kb < 100


class TestEventQueueGrowth:
    """Event queue growth when worker can't keep up."""

    def test_queue_drain(self):
        from aiwarden.capture import _queue, capture
        from aiwarden import config

        old_enabled = config.ENABLED
        config.ENABLED = True

        initial_size = _queue.qsize()

        for i in range(100):
            capture({"test": True, "i": i})

        queue_after = _queue.qsize()
        growth = queue_after - initial_size
        print(f"\n  Queue after 100 captures: grew by {growth} (worker draining in background)")

        config.ENABLED = old_enabled
        time.sleep(3)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

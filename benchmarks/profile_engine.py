#!/usr/bin/env python3
"""
Profiling script for the ai-warden policy engine.

Generates:
1. cProfile output — function-level hotspot identification
2. tracemalloc report — top memory allocators
3. Component-level timing breakdown

Usage:
    python benchmarks/profile_engine.py
"""
import cProfile
import io
import pstats
import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from aiwarden.policies.builtin.budget import BudgetPolicy
from aiwarden.policies.builtin.pii import PIIPolicy
from aiwarden.policies.builtin.tools import ToolsPolicy
from aiwarden.policies.builtin.agent_control import AgentControlPolicy
from aiwarden.policies.custom.policy import CustomPolicy
from aiwarden.policies.engine import PolicyEngine
from aiwarden.patchers._common import build_and_capture, extract_caller
from aiwarden import config

from benchmarks.conftest import (
    generate_custom_rules,
    generate_pii_patterns,
    make_anthropic_response,
    make_pii_request,
    make_request,
    make_tool_policy_config,
)

config.ENABLED = True
config.DEBUG = False
config.LOG_FILE = "/tmp/bench_profile_events.jsonl"
config.CALLER_TRACKING = True


def profile_full_engine(iterations=5000):
    """Profile engine.run_pre + run_post with realistic workload."""
    print("=" * 70)
    print(" CPROFILE: Full Engine (run_pre + run_post)")
    print(f" Iterations: {iterations}")
    print("=" * 70)

    engine = PolicyEngine()
    engine._policies = sorted([
        BudgetPolicy({"limit": 999999.0, "group_by": "metadata.team", "reset": "monthly"}),
        AgentControlPolicy({"max_turns": 100, "max_cost": 100.0}),
        CustomPolicy({"name": "custom", "rules": generate_custom_rules(20)}),
        PIIPolicy({"patterns": generate_pii_patterns(5)}),
        ToolsPolicy(make_tool_policy_config(num_rules=5)),
    ], key=lambda p: p.priority)

    request = make_request(content="Email user@example.com with SSN 123-45-6789", metadata={"team": "eng"})
    response = make_anthropic_response(
        tool_calls=[{"name": "read_file", "input": {"path": "/home/user/doc.txt"}}]
    )

    def workload():
        for _ in range(iterations):
            r = dict(request)
            r, block, pre_fired = engine.run_pre(r)
            engine.run_post(r, response)

    profiler = cProfile.Profile()
    profiler.enable()
    workload()
    profiler.disable()

    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream)
    stats.sort_stats("cumulative")
    stats.print_stats(30)
    print(stream.getvalue())

    print("\n  Top functions by TOTAL time:")
    stream2 = io.StringIO()
    stats2 = pstats.Stats(profiler, stream=stream2)
    stats2.sort_stats("tottime")
    stats2.print_stats(20)
    print(stream2.getvalue())


def profile_pii_policy(iterations=2000):
    """Profile PII policy in isolation."""
    print("\n" + "=" * 70)
    print(" CPROFILE: PII Policy (10KB message, 10 patterns)")
    print(f" Iterations: {iterations}")
    print("=" * 70)

    policy = PIIPolicy({"patterns": generate_pii_patterns(5)})
    request = make_pii_request(size_kb=10)

    def workload():
        for _ in range(iterations):
            policy.pre(dict(request))

    profiler = cProfile.Profile()
    profiler.enable()
    workload()
    profiler.disable()

    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream)
    stats.sort_stats("tottime")
    stats.print_stats(15)
    print(stream.getvalue())


def profile_custom_rules(iterations=5000):
    """Profile custom rule evaluation."""
    print("\n" + "=" * 70)
    print(" CPROFILE: Custom Policy (100 rules, no match)")
    print(f" Iterations: {iterations}")
    print("=" * 70)

    policy = CustomPolicy({"name": "bench", "rules": generate_custom_rules(100)})
    request = make_request(metadata={"team": "eng", "env": "production"})

    def workload():
        for _ in range(iterations):
            policy.pre(dict(request))

    profiler = cProfile.Profile()
    profiler.enable()
    workload()
    profiler.disable()

    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream)
    stats.sort_stats("tottime")
    stats.print_stats(15)
    print(stream.getvalue())


def profile_memory():
    """tracemalloc: identify top allocators during engine operation."""
    print("\n" + "=" * 70)
    print(" TRACEMALLOC: Memory Allocation Analysis")
    print("=" * 70)

    engine = PolicyEngine()
    engine._policies = sorted([
        BudgetPolicy({"limit": 999999.0}),
        AgentControlPolicy({"max_turns": 100}),
        CustomPolicy({"name": "c", "rules": generate_custom_rules(20)}),
        PIIPolicy({"patterns": generate_pii_patterns(5)}),
    ], key=lambda p: p.priority)

    request = make_request(content="user@example.com SSN 123-45-6789", metadata={"team": "eng"})

    # Warmup
    for _ in range(100):
        engine.run_pre(dict(request))

    tracemalloc.start()
    snapshot_before = tracemalloc.take_snapshot()

    for _ in range(10_000):
        engine.run_pre(dict(request))

    snapshot_after = tracemalloc.take_snapshot()
    tracemalloc.stop()

    print("\n  Top 15 memory allocators (10K iterations):")
    stats = snapshot_after.compare_to(snapshot_before, "lineno")
    for i, stat in enumerate(stats[:15]):
        print(f"    {i+1:2d}. {stat}")

    total_growth = sum(s.size_diff for s in stats if s.size_diff > 0)
    print(f"\n  Total memory growth: {total_growth/1024:.1f}KB ({total_growth/1024/10000*1000:.2f} bytes/iteration)")


def profile_component_timing():
    """Manual timing of each component in the hot path."""
    print("\n" + "=" * 70)
    print(" COMPONENT TIMING BREAKDOWN")
    print("=" * 70)

    engine = PolicyEngine()
    budget = BudgetPolicy({"limit": 999999.0, "group_by": "metadata.team", "reset": "monthly"})
    agent_ctrl = AgentControlPolicy({"max_turns": 100})
    custom = CustomPolicy({"name": "c", "rules": generate_custom_rules(20)})
    pii = PIIPolicy({"patterns": generate_pii_patterns(5)})
    tools = ToolsPolicy(make_tool_policy_config(5))

    request = make_request(content="user@example.com SSN 123-45-6789", metadata={"team": "eng"})
    response = make_anthropic_response(
        tool_calls=[{"name": "read_file", "input": {"path": "/tmp/f.txt"}}]
    )
    iterations = 5000

    components = {
        "BudgetPolicy.pre()": lambda: budget.pre(dict(request)),
        "AgentControlPolicy.pre()": lambda: agent_ctrl.pre(dict(request)),
        "CustomPolicy.pre() [20 rules]": lambda: custom.pre(dict(request)),
        "PIIPolicy.pre() [10 patterns]": lambda: pii.pre(dict(request)),
        "ToolsPolicy.post() [5 rules]": lambda: tools.post(dict(request), response),
        "extract_caller()": extract_caller,
        "engine.run_pre() [all]": lambda: engine.run_pre(dict(request)) if engine._policies else None,
    }

    engine._policies = sorted([budget, agent_ctrl, custom, pii], key=lambda p: p.priority)

    print(f"\n  {'Component':<40} {'Mean (μs)':<12} {'P99 (μs)':<12}")
    print(f"  {'-'*40} {'-'*12} {'-'*12}")

    for name, fn in components.items():
        # warmup
        for _ in range(100):
            fn()
        times = []
        for _ in range(iterations):
            start = time.perf_counter_ns()
            fn()
            times.append(time.perf_counter_ns() - start)
        mean = sum(times) / len(times) / 1000
        p99 = sorted(times)[int(0.99 * len(times))] / 1000
        print(f"  {name:<40} {mean:<12.1f} {p99:<12.1f}")


def main():
    profile_component_timing()
    profile_full_engine()
    profile_pii_policy()
    profile_custom_rules()
    profile_memory()
    print("\n\n  Profiling complete.")


if __name__ == "__main__":
    main()

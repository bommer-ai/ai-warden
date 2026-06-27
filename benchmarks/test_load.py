"""
Load tests — throughput and latency measurements.

Measures:
- Rule evaluation latency with varying rule counts (1/10/100/1000)
- PII redaction with varying message sizes (1KB/10KB/100KB)
- Full engine pre/post with all policies active
- Concurrent execution (threading)
"""
import statistics
import threading
import time

import pytest

from aiwarden.policies.builtin.budget import BudgetPolicy
from aiwarden.policies.builtin.pii import PIIPolicy
from aiwarden.policies.builtin.tools import ToolsPolicy
from aiwarden.policies.builtin.agent_control import AgentControlPolicy
from aiwarden.policies.custom.policy import CustomPolicy
from aiwarden.policies.engine import PolicyEngine

from benchmarks.conftest import (
    generate_complex_rules,
    generate_custom_rules,
    generate_pii_patterns,
    make_anthropic_response,
    make_pii_request,
    make_request,
    make_tool_policy_config,
)


def measure(fn, iterations=1000, warmup=100):
    for _ in range(warmup):
        fn()
    times = []
    for _ in range(iterations):
        start = time.perf_counter_ns()
        fn()
        elapsed = time.perf_counter_ns() - start
        times.append(elapsed)
    return {
        "iterations": iterations,
        "min_ns": min(times),
        "max_ns": max(times),
        "mean_ns": statistics.mean(times),
        "median_ns": statistics.median(times),
        "p95_ns": sorted(times)[int(0.95 * len(times))],
        "p99_ns": sorted(times)[int(0.99 * len(times))],
        "stddev_ns": statistics.stdev(times),
        "mean_us": statistics.mean(times) / 1000,
        "p95_us": sorted(times)[int(0.95 * len(times))] / 1000,
        "p99_us": sorted(times)[int(0.99 * len(times))] / 1000,
    }


def print_results(name, results):
    print(f"\n  {name}:")
    print(f"    Mean: {results['mean_us']:.1f}μs | P95: {results['p95_us']:.1f}μs | P99: {results['p99_us']:.1f}μs")
    print(f"    Min: {results['min_ns']/1000:.1f}μs | Max: {results['max_ns']/1000:.1f}μs | StdDev: {results['stddev_ns']/1000:.1f}μs")


class TestCustomRuleLatency:
    """Latency with varying number of custom rules."""

    def test_1_rule(self):
        policy = CustomPolicy({"name": "bench", "rules": generate_custom_rules(1)})
        request = make_request()
        results = measure(lambda: policy.pre(dict(request)))
        print_results("1 custom rule (no match)", results)
        assert results["p99_us"] < 100

    def test_10_rules(self):
        policy = CustomPolicy({"name": "bench", "rules": generate_custom_rules(10)})
        request = make_request()
        results = measure(lambda: policy.pre(dict(request)))
        print_results("10 custom rules (no match)", results)
        assert results["p99_us"] < 200

    def test_100_rules(self):
        policy = CustomPolicy({"name": "bench", "rules": generate_custom_rules(100)})
        request = make_request()
        results = measure(lambda: policy.pre(dict(request)))
        print_results("100 custom rules (no match)", results)
        assert results["p99_us"] < 2000

    def test_1000_rules(self):
        policy = CustomPolicy({"name": "bench", "rules": generate_custom_rules(1000)})
        request = make_request()
        results = measure(lambda: policy.pre(dict(request)), iterations=500)
        print_results("1000 custom rules (no match)", results)
        assert results["p99_us"] < 20000

    def test_50_complex_rules(self):
        policy = CustomPolicy({"name": "bench", "rules": generate_complex_rules(50)})
        request = make_request(metadata={"team": "eng"})
        results = measure(lambda: policy.pre(dict(request)))
        print_results("50 complex rules (4 fields each, no match)", results)
        assert results["p99_us"] < 5000


class TestPIILatency:
    """PII redaction latency with varying payloads."""

    def test_1kb_5_patterns(self):
        policy = PIIPolicy({})
        request = make_pii_request(size_kb=1)
        results = measure(lambda: policy.pre(dict(request)))
        print_results("PII: 1KB, 5 patterns", results)
        assert results["p99_us"] < 500

    def test_10kb_5_patterns(self):
        policy = PIIPolicy({})
        request = make_pii_request(size_kb=10)
        results = measure(lambda: policy.pre(dict(request)))
        print_results("PII: 10KB, 5 patterns", results)
        assert results["p99_us"] < 5000

    def test_100kb_5_patterns(self):
        policy = PIIPolicy({})
        request = make_pii_request(size_kb=100)
        results = measure(lambda: policy.pre(dict(request)), iterations=200)
        print_results("PII: 100KB, 5 patterns", results)
        assert results["p99_us"] < 50000

    def test_1kb_15_patterns(self):
        policy = PIIPolicy({"patterns": generate_pii_patterns(10)})
        request = make_pii_request(size_kb=1)
        results = measure(lambda: policy.pre(dict(request)))
        print_results("PII: 1KB, 15 patterns (5 builtin + 10 custom)", results)
        assert results["p99_us"] < 1000

    def test_10kb_15_patterns(self):
        policy = PIIPolicy({"patterns": generate_pii_patterns(10)})
        request = make_pii_request(size_kb=10)
        results = measure(lambda: policy.pre(dict(request)))
        print_results("PII: 10KB, 15 patterns", results)
        assert results["p99_us"] < 10000


class TestFullEngineLatency:
    """Full engine.run_pre() with realistic policy stacks."""

    def _make_engine(self, num_custom_rules=0):
        engine = PolicyEngine()
        policies = [
            BudgetPolicy({"limit": 1000.0}),
            AgentControlPolicy({"max_turns": 100}),
            PIIPolicy({}),
        ]
        if num_custom_rules > 0:
            policies.append(CustomPolicy({
                "name": "custom", "rules": generate_custom_rules(num_custom_rules)
            }))
        engine._policies = sorted(policies, key=lambda p: p.priority)
        return engine

    def test_3_builtin_policies(self):
        engine = self._make_engine()
        request = make_request(content="user@example.com is my email")
        results = measure(lambda: engine.run_pre(dict(request)))
        print_results("engine.run_pre: 3 builtin policies", results)
        assert results["p99_us"] < 500

    def test_3_builtin_plus_10_custom(self):
        engine = self._make_engine(num_custom_rules=10)
        request = make_request(content="user@example.com is my email")
        results = measure(lambda: engine.run_pre(dict(request)))
        print_results("engine.run_pre: 3 builtin + 10 custom rules", results)
        assert results["p99_us"] < 1000

    def test_3_builtin_plus_100_custom(self):
        engine = self._make_engine(num_custom_rules=100)
        request = make_request(content="user@example.com is my email")
        results = measure(lambda: engine.run_pre(dict(request)))
        print_results("engine.run_pre: 3 builtin + 100 custom rules", results)
        assert results["p99_us"] < 5000

    def test_post_hooks_with_tool_policy(self):
        engine = PolicyEngine()
        config = make_tool_policy_config(num_rules=10)
        engine._policies = [ToolsPolicy(config)]
        response = make_anthropic_response(tool_calls=[
            {"name": "safe_tool", "input": {"path": "/home/user/file.txt"}},
        ])
        request = make_request()
        results = measure(lambda: engine.run_post(dict(request), response))
        print_results("engine.run_post: ToolsPolicy 10 rules, 1 tool call", results)
        assert results["p99_us"] < 500


class TestConcurrency:
    """Concurrent access to engine."""

    def test_100_threads_pre_hooks(self):
        engine = PolicyEngine()
        engine._policies = [
            BudgetPolicy({"limit": 999999.0}),
            PIIPolicy({}),
            CustomPolicy({"name": "c", "rules": generate_custom_rules(10)}),
        ]
        engine._policies.sort(key=lambda p: p.priority)

        errors = []
        latencies = []

        def worker():
            try:
                request = make_request(content="test@example.com")
                start = time.perf_counter_ns()
                engine.run_pre(dict(request))
                elapsed = time.perf_counter_ns() - start
                latencies.append(elapsed)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(100)]
        start = time.monotonic()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        wall_time = time.monotonic() - start

        assert len(errors) == 0, f"Errors: {errors}"
        assert len(latencies) == 100

        mean_us = statistics.mean(latencies) / 1000
        p99_us = sorted(latencies)[99] / 1000
        print(f"\n  100 threads concurrent pre-hooks:")
        print(f"    Wall time: {wall_time*1000:.1f}ms")
        print(f"    Mean per-thread: {mean_us:.1f}μs | P99: {p99_us:.1f}μs")
        print(f"    Errors: {len(errors)}")

    def test_sustained_load_10k_calls(self):
        engine = PolicyEngine()
        engine._policies = [
            PIIPolicy({}),
            CustomPolicy({"name": "c", "rules": generate_custom_rules(10)}),
        ]
        engine._policies.sort(key=lambda p: p.priority)

        request = make_request(content="contact user@test.com please")
        start = time.monotonic()
        for _ in range(10_000):
            engine.run_pre(dict(request))
        elapsed = time.monotonic() - start

        throughput = 10_000 / elapsed
        per_call_us = (elapsed / 10_000) * 1_000_000
        print(f"\n  Sustained 10K calls:")
        print(f"    Total: {elapsed*1000:.1f}ms")
        print(f"    Per call: {per_call_us:.1f}μs")
        print(f"    Throughput: {throughput:.0f} calls/sec")
        assert per_call_us < 1000


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

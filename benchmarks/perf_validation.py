#!/usr/bin/env python3
"""
Comprehensive Performance Validation Suite for ai-warden Rule Engine.

Methodology:
- Multiple independent runs per benchmark (30 full, 10 quick)
- Correct confidence intervals using t-distribution
- GC disabled during measurement windows
- Percentiles computed over INDIVIDUAL measurements (not run-means)
- Environment metadata recorded in output
- lru_cache cleared between benchmarks for isolation
- End-to-end SDK patching path benchmarked with config.ENABLED=True
- Async pathway benchmarked
- Multi-message workloads included

Usage:
    python benchmarks/perf_validation.py              # full mode (30 runs)
    python benchmarks/perf_validation.py --quick      # quick mode (10 runs)
"""
import asyncio
import gc
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import threading
import time
import tracemalloc
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Callable
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

QUICK_MODE = "--quick" in sys.argv
NUM_RUNS = 10 if QUICK_MODE else 30
INNER_ITERS = 1000 if QUICK_MODE else 2000


# ═══════════════════════════════════════════════════════════════════════════════
#  INFRASTRUCTURE
# ═══════════════════════════════════════════════════════════════════════════════

def _t_critical(n: int, confidence: float = 0.95) -> float:
    """
    Approximate t-distribution critical value for two-tailed CI.
    Uses Abramowitz & Stegun approximation for df > 2.
    """
    df = n - 1
    if df <= 1:
        return 12.706
    # Common values for 95% CI
    t_table = {
        2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447,
        7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201,
        12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120,
        17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086, 25: 2.060,
        29: 2.045, 30: 2.042, 40: 2.021, 60: 2.000, 120: 1.980,
    }
    if df in t_table:
        return t_table[df]
    # For large df, converge toward z=1.96
    if df > 120:
        return 1.96
    # Interpolate
    keys = sorted(t_table.keys())
    for i in range(len(keys) - 1):
        if keys[i] <= df <= keys[i + 1]:
            lo, hi = keys[i], keys[i + 1]
            frac = (df - lo) / (hi - lo)
            return t_table[lo] + frac * (t_table[hi] - t_table[lo])
    return 1.96


@dataclass
class BenchResult:
    name: str
    runs: int
    iters_per_run: int
    # All individual measurements (runs × iters), in microseconds
    all_measurements_us: list = field(default_factory=list)
    # Per-run means for inter-run statistics
    run_means_us: list = field(default_factory=list)
    memory_kb: float = 0.0

    @property
    def n_total(self): return len(self.all_measurements_us)
    @property
    def mean(self): return statistics.mean(self.run_means_us) if self.run_means_us else 0
    @property
    def median(self): return statistics.median(self.run_means_us) if self.run_means_us else 0
    @property
    def stdev(self): return statistics.stdev(self.run_means_us) if len(self.run_means_us) > 1 else 0
    @property
    def cv(self): return (self.stdev / self.mean * 100) if self.mean > 0 else 0

    # Percentiles from individual measurements (correct methodology)
    @property
    def p50(self): return self._pct(0.50)
    @property
    def p90(self): return self._pct(0.90)
    @property
    def p95(self): return self._pct(0.95)
    @property
    def p99(self): return self._pct(0.99)
    @property
    def p999(self): return self._pct(0.999)
    @property
    def min_val(self): return min(self.all_measurements_us) if self.all_measurements_us else 0
    @property
    def max_val(self): return max(self.all_measurements_us) if self.all_measurements_us else 0
    @property
    def throughput(self): return 1_000_000 / self.mean if self.mean > 0 else 0

    @property
    def ci_95(self):
        """Correct 95% CI using t-distribution on run-means."""
        n = len(self.run_means_us)
        if n < 2:
            return (self.mean, self.mean)
        t_crit = _t_critical(n)
        se = self.stdev / math.sqrt(n)
        return (self.mean - t_crit * se, self.mean + t_crit * se)

    def _pct(self, p):
        if not self.all_measurements_us:
            return 0
        s = sorted(self.all_measurements_us)
        idx = min(int(p * len(s)), len(s) - 1)
        return s[idx]

    def to_dict(self):
        ci = self.ci_95
        return {
            "name": self.name, "runs": self.runs, "iters_per_run": self.iters_per_run,
            "total_measurements": self.n_total,
            "mean_us": round(self.mean, 3), "median_us": round(self.median, 3),
            "p50_us": round(self.p50, 3), "p90_us": round(self.p90, 3),
            "p95_us": round(self.p95, 3), "p99_us": round(self.p99, 3),
            "p999_us": round(self.p999, 3),
            "min_us": round(self.min_val, 3), "max_us": round(self.max_val, 3),
            "stdev_us": round(self.stdev, 3), "cv_pct": round(self.cv, 2),
            "ci_95_lower": round(ci[0], 3), "ci_95_upper": round(ci[1], 3),
            "ci_method": f"t-distribution (df={self.runs - 1})",
            "throughput_per_sec": round(self.throughput, 0),
            "memory_kb": round(self.memory_kb, 1),
        }


def _clear_caches():
    """Clear all lru_caches to ensure benchmark isolation."""
    from aiwarden.policies.custom.resolver import _split_path
    from aiwarden.policies.custom.operators import _compile_regex as op_regex
    from aiwarden.policies.builtin.tools_rules import _compile_regex as tr_regex
    from aiwarden.policies.builtin.tools_rules import _compile_glob
    _split_path.cache_clear()
    op_regex.cache_clear()
    tr_regex.cache_clear()
    _compile_glob.cache_clear()


def bench(name: str, fn: Callable, runs: int = NUM_RUNS, iters: int = INNER_ITERS,
          warmup: int = 200) -> BenchResult:
    """
    Run a benchmark with statistical rigor.
    Each run: warmup → GC → measure → collect individual timings.
    """
    _clear_caches()
    result = BenchResult(name=name, runs=runs, iters_per_run=iters)

    for _ in range(runs):
        for _ in range(warmup):
            fn()

        gc.collect()
        gc.disable()

        times_ns = []
        for _ in range(iters):
            start = time.perf_counter_ns()
            fn()
            times_ns.append(time.perf_counter_ns() - start)

        gc.enable()

        run_mean_us = statistics.mean(times_ns) / 1000
        result.run_means_us.append(run_mean_us)
        result.all_measurements_us.extend(t / 1000 for t in times_ns)

    return result


def print_result(r: BenchResult):
    ci = r.ci_95
    print(f"  {r.name}")
    print(f"    Mean: {r.mean:.2f}μs ± {r.stdev:.2f} (CV={r.cv:.1f}%, N={r.runs} runs)")
    print(f"    95% CI: [{ci[0]:.2f}, {ci[1]:.2f}]μs (t-dist, df={r.runs - 1})")
    print(f"    P50={r.p50:.2f} P90={r.p90:.2f} P95={r.p95:.2f} P99={r.p99:.2f} P99.9={r.p999:.2f}μs")
    print(f"    Throughput: {r.throughput:,.0f}/s | Measurements: {r.n_total:,}")


def get_environment():
    """Collect machine/environment metadata for reproducibility."""
    commit = "unknown"
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        pass
    return {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "python_version": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "commit_sha": commit,
        "mode": "quick" if QUICK_MODE else "full",
        "runs_per_benchmark": NUM_RUNS,
        "iters_per_run": INNER_ITERS,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  FIXTURES
# ═══════════════════════════════════════════════════════════════════════════════

def make_request(content="Hello, help me.", num_messages=1, metadata=None):
    messages = []
    for i in range(num_messages):
        role = "user" if i % 2 == 0 else "assistant"
        messages.append({"role": role, "content": f"{content} (msg {i})"})
    req = {"model": "claude-sonnet-4-6", "max_tokens": 1024, "messages": messages}
    if metadata:
        req["metadata"] = metadata
    return req


def make_pii_content(size_kb):
    pii = "Contact john@example.com or call 555-123-4567. SSN: 123-45-6789. Key: sk-abcdefghijklmnopqrstuvwxyz. CC: 4111 1111 1111 1111. "
    pad = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 5
    block = pii + pad
    return (block * (size_kb * 1024 // len(block) + 1))[:size_kb * 1024]


def make_rules(n):
    return [{"name": f"r-{i}", "hook": "pre", "action": "warn",
             "match": {"model": {"contains": f"nonexistent-{i}"}}}
            for i in range(n)]


def make_response(text="OK", input_tokens=100, output_tokens=50, tool_calls=None):
    content = []
    if tool_calls:
        for tc in tool_calls:
            content.append(SimpleNamespace(type="tool_use", id=f"toolu_{uuid4().hex[:24]}",
                                          name=tc["name"], input=tc.get("input", {})))
    else:
        content.append(SimpleNamespace(type="text", text=text))
    return SimpleNamespace(
        id=f"msg_{uuid4().hex[:24]}", model="claude-sonnet-4-6", role="assistant",
        type="message", stop_reason="end_turn" if not tool_calls else "tool_use",
        content=content,
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens))


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE 1: CORE LATENCY (isolated policy engine)
# ═══════════════════════════════════════════════════════════════════════════════

def run_core_benchmarks():
    from aiwarden.policies.builtin.budget import BudgetPolicy
    from aiwarden.policies.builtin.pii import PIIPolicy
    from aiwarden.policies.builtin.tools import ToolsPolicy
    from aiwarden.policies.builtin.agent_control import AgentControlPolicy
    from aiwarden.policies.custom.policy import CustomPolicy
    from aiwarden.policies.engine import PolicyEngine
    from aiwarden.patchers._common import extract_caller
    from aiwarden import config

    print("\n" + "=" * 70)
    print(" PHASE 1: CORE LATENCY (policy engine only, capture disabled)")
    print("=" * 70)
    results = []
    config.ENABLED = False
    config.CALLER_TRACKING = False

    # Single rule miss
    policy = CustomPolicy({"name": "b", "rules": make_rules(1)})
    req = make_request()
    r = bench("custom_1rule_miss", lambda: policy.pre(dict(req)))
    print_result(r); results.append(r)

    # Single rule match
    policy_m = CustomPolicy({"name": "b", "rules": [
        {"name": "match", "hook": "pre", "action": "block",
         "match": {"model": {"contains": "sonnet"}}, "message": "blocked"}]})
    r = bench("custom_1rule_match", lambda: policy_m.pre(dict(req)))
    print_result(r); results.append(r)

    # PII 1KB
    pii = PIIPolicy({})
    pii_req = {"model": "x", "messages": [{"role": "user", "content": make_pii_content(1)}]}
    r = bench("pii_1kb_5pat", lambda: pii.pre(dict(pii_req)))
    print_result(r); results.append(r)

    # Budget cycle
    budget = BudgetPolicy({"limit": 999999.0, "group_by": "metadata.team", "reset": "monthly"})
    b_req = make_request(metadata={"team": "eng"})
    b_resp = make_response()
    r = bench("budget_cycle", lambda: (budget.pre(dict(b_req)), budget.post(dict(b_req), b_resp)))
    print_result(r); results.append(r)

    # Tool interception (builtin rules, tool that triggers matching)
    tools = ToolsPolicy({"name": "t", "type": "tools", "enabled": True,
                         "builtin": {"filesystem-safety": True, "no-privilege-escalation": True}})
    tool_resp = SimpleNamespace(
        id="msg_1", model="claude-sonnet-4-6", role="assistant", type="message",
        stop_reason="tool_use",
        content=[SimpleNamespace(type="tool_use", id="t1", name="bash",
                                 input={"command": "ls -la /home/user"})],
        usage=SimpleNamespace(input_tokens=100, output_tokens=50))
    r = bench("tools_builtin_match", lambda: tools.post(dict(req), tool_resp))
    print_result(r); results.append(r)

    # Full engine pre (4 policies)
    engine = PolicyEngine()
    engine._policies = sorted([
        BudgetPolicy({"limit": 999999.0}),
        AgentControlPolicy({"max_turns": 100}),
        CustomPolicy({"name": "c", "rules": make_rules(10)}),
        PIIPolicy({}),
    ], key=lambda p: p.priority)
    full_req = make_request(content="Email user@example.com about the project")
    r = bench("engine_pre_4policies", lambda: engine.run_pre(dict(full_req)))
    print_result(r); results.append(r)

    # extract_caller overhead
    config.CALLER_TRACKING = True
    r = bench("extract_caller", extract_caller)
    config.CALLER_TRACKING = False
    print_result(r); results.append(r)

    return results


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE 2: END-TO-END SDK PATCHING PATH (production config)
# ═══════════════════════════════════════════════════════════════════════════════

def run_e2e_benchmarks():
    from aiwarden import config
    from aiwarden.policies.engine import PolicyEngine
    from aiwarden.policies.builtin.pii import PIIPolicy
    from aiwarden.policies.builtin.budget import BudgetPolicy
    from aiwarden.policies.custom.policy import CustomPolicy
    from aiwarden.patchers._common import build_and_capture, extract_caller
    from aiwarden.policies import engine as engine_singleton

    print("\n" + "=" * 70)
    print(" PHASE 2: END-TO-END (full production path, capture enabled)")
    print("=" * 70)
    results = []

    # Enable production features
    config.ENABLED = True
    config.CALLER_TRACKING = True
    config.LOG_FILE = "/tmp/aiwarden_bench_events.jsonl"

    # Set up policies on the singleton
    old_policies = engine_singleton._policies
    engine_singleton._policies = sorted([
        BudgetPolicy({"limit": 999999.0}),
        CustomPolicy({"name": "c", "rules": make_rules(10)}),
        PIIPolicy({}),
    ], key=lambda p: p.priority)

    # Benchmark build_and_capture in isolation
    kwargs = {"model": "claude-sonnet-4-6", "max_tokens": 1024,
              "messages": [{"role": "user", "content": "Email user@test.com please"}],
              "metadata": {"team": "eng"}}
    response = make_response(input_tokens=200, output_tokens=80)

    def do_build_and_capture():
        build_and_capture(
            provider="anthropic", kwargs=kwargs,
            messages=kwargs["messages"], model=kwargs["model"],
            text_content="OK", tool_calls=[], finish_reason="end_turn",
            prompt_tokens=200, completion_tokens=80, latency_ms=1500,
            streamed=False, pre_fired=[], post_fired=[], pii_found=[])

    r = bench("build_and_capture", do_build_and_capture)
    print_result(r); results.append(r)

    # Full interception path: pre + post + build_and_capture
    def full_interception():
        req = dict(kwargs)
        req, block, pre_fired = engine_singleton.run_pre(req)
        resp, post_fired = engine_singleton.run_post(req, response)
        build_and_capture(
            provider="anthropic", kwargs=req,
            messages=req.get("messages", []), model=req.get("model", ""),
            text_content="OK", tool_calls=[], finish_reason="end_turn",
            prompt_tokens=200, completion_tokens=80, latency_ms=1500,
            streamed=False, pre_fired=pre_fired, post_fired=post_fired,
            pii_found=req.get("_pii_found", []))

    r = bench("full_interception_path", full_interception)
    print_result(r); results.append(r)

    # Multi-message (20 messages, realistic agentic conversation)
    multi_msg_req = make_request(content="User query with user@example.com", num_messages=20)
    multi_msg_req["metadata"] = {"team": "eng"}

    def multi_message_interception():
        req = dict(multi_msg_req)
        req["messages"] = list(multi_msg_req["messages"])  # proper copy for PII
        req, block, pre_fired = engine_singleton.run_pre(req)

    r = bench("multi_message_20msg_pre", multi_message_interception, iters=INNER_ITERS // 2)
    print_result(r); results.append(r)

    # Restore
    config.ENABLED = False
    config.CALLER_TRACKING = False
    engine_singleton._policies = old_policies

    return results


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE 3: ASYNC PATHWAY
# ═══════════════════════════════════════════════════════════════════════════════

def run_async_benchmarks():
    from aiwarden.policies.custom.policy import CustomPolicy
    from aiwarden.policies.engine import PolicyEngine
    from aiwarden.session import _current_run, _new_run

    print("\n" + "=" * 70)
    print(" PHASE 3: ASYNC PATHWAY (ContextVar isolation)")
    print("=" * 70)
    results = []

    engine = PolicyEngine()
    engine._policies = [CustomPolicy({"name": "c", "rules": make_rules(10)})]

    # Async correctness: 100 concurrent tasks, verify isolation
    async def async_eval(task_id):
        state = _new_run()
        state.run_id = f"async-{task_id}"
        req = {"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": f"task {task_id}"}]}
        engine.run_pre(req)
        await asyncio.sleep(0)  # yield to event loop
        read_back = _current_run.get()
        return read_back.run_id == f"async-{task_id}"

    async def run_async_correctness():
        tasks = [async_eval(i) for i in range(100)]
        return await asyncio.gather(*tasks)

    # Measure async latency
    async def async_bench_inner():
        req = {"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "hi"}]}
        start = time.perf_counter_ns()
        engine.run_pre(req)
        return time.perf_counter_ns() - start

    async def async_bench_concurrent(n_tasks):
        tasks = [async_bench_inner() for _ in range(n_tasks)]
        return await asyncio.gather(*tasks)

    # Correctness test
    correctness_results = asyncio.run(run_async_correctness())
    correct = sum(correctness_results)
    print(f"\n  Async ContextVar correctness: {correct}/100 tasks isolated correctly")
    if correct < 100:
        print(f"  *** ASYNC ISOLATION FAILURE: {100 - correct} tasks leaked state")

    # Latency measurement
    async_times = asyncio.run(async_bench_concurrent(1000))
    async_us = [t / 1000 for t in async_times]
    mean_us = statistics.mean(async_us)
    p99_us = sorted(async_us)[int(0.99 * len(async_us))]
    print(f"  Async eval latency (1000 tasks): mean={mean_us:.2f}μs p99={p99_us:.2f}μs")

    return [{"async_correctness": correct, "async_mean_us": round(mean_us, 2),
             "async_p99_us": round(p99_us, 2)}]


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE 4: SCALABILITY
# ═══════════════════════════════════════════════════════════════════════════════

def run_scalability():
    from aiwarden.policies.custom.policy import CustomPolicy
    from aiwarden.policies.builtin.pii import PIIPolicy
    from aiwarden import config
    config.ENABLED = False

    print("\n" + "=" * 70)
    print(" PHASE 4: SCALABILITY")
    print("=" * 70)
    results = {}

    # Rule count scaling
    print("\n  Rule Count:")
    print(f"  {'Rules':<8} {'Mean(μs)':<12} {'CI 95%':<22} {'Per-rule(ns)':<14} {'Throughput':<12}")
    print(f"  {'-'*8} {'-'*12} {'-'*22} {'-'*14} {'-'*12}")

    rule_counts = [1, 10, 100, 500, 1000, 2500, 5000, 10000]
    if QUICK_MODE:
        rule_counts = [1, 10, 100, 500, 1000, 2500]
    rule_results = []

    for n in rule_counts:
        policy = CustomPolicy({"name": "s", "rules": make_rules(n)})
        req = make_request()
        iters = max(200, INNER_ITERS // (1 + n // 500))
        r = bench(f"rules_{n}", lambda: policy.pre(dict(req)),
                  runs=min(NUM_RUNS, 15), iters=iters, warmup=50)
        ci = r.ci_95
        per_rule_ns = (r.mean * 1000) / n
        print(f"  {n:<8} {r.mean:<12.2f} [{ci[0]:.2f}, {ci[1]:.2f}]{'':<4} {per_rule_ns:<14.1f} {r.throughput:<12,.0f}/s")
        rule_results.append(r)

    results["rules"] = [r.to_dict() for r in rule_results]

    # Payload scaling
    print("\n  Payload Size (PII):")
    print(f"  {'Size':<10} {'Mean(μs)':<12} {'CI 95%':<22} {'Per-KB(μs)':<12}")
    print(f"  {'-'*10} {'-'*12} {'-'*22} {'-'*12}")

    pii = PIIPolicy({})
    sizes = [0.1, 1, 10, 100, 500] if not QUICK_MODE else [0.1, 1, 10, 100]
    payload_results = []

    for size_kb in sizes:
        content = make_pii_content(max(1, int(size_kb)))
        if size_kb < 1:
            content = content[:int(size_kb * 1024)]
        req = {"model": "x", "messages": [{"role": "user", "content": content}]}
        iters = max(100, INNER_ITERS // (1 + int(size_kb) // 50))
        r = bench(f"pii_{size_kb}kb", lambda: pii.pre(dict(req)),
                  runs=min(NUM_RUNS, 15), iters=iters, warmup=20)
        ci = r.ci_95
        per_kb = r.mean / max(size_kb, 0.1)
        label = f"{size_kb}KB" if size_kb >= 1 else f"{int(size_kb * 1024)}B"
        print(f"  {label:<10} {r.mean:<12.2f} [{ci[0]:.2f}, {ci[1]:.2f}]{'':<4} {per_kb:<12.2f}")
        payload_results.append(r)

    results["payload"] = [r.to_dict() for r in payload_results]
    return results


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE 5: CONCURRENCY + CORRECTNESS
# ═══════════════════════════════════════════════════════════════════════════════

def run_concurrency():
    from aiwarden.policies.custom.policy import CustomPolicy
    from aiwarden.policies.builtin.pii import PIIPolicy
    from aiwarden.policies.builtin.budget import BudgetPolicy
    from aiwarden.policies.engine import PolicyEngine
    from aiwarden import config
    config.ENABLED = False

    print("\n" + "=" * 70)
    print(" PHASE 5: CONCURRENCY + CORRECTNESS UNDER LOAD")
    print("=" * 70)

    engine = PolicyEngine()
    engine._policies = sorted([
        BudgetPolicy({"limit": 999999.0}),
        CustomPolicy({"name": "c", "rules": make_rules(20)}),
        PIIPolicy({}),
    ], key=lambda p: p.priority)

    # Throughput scaling
    thread_counts = [1, 2, 4, 8, 16, 32, 64, 128, 256, 500]
    if QUICK_MODE:
        thread_counts = [1, 2, 4, 16, 64, 256]
    evals_per_thread = 500 if not QUICK_MODE else 200

    print(f"\n  {'Threads':<10} {'Wall(ms)':<12} {'Throughput':<14} {'Scaling':<10} {'Errors':<8}")
    print(f"  {'-'*10} {'-'*12} {'-'*14} {'-'*10} {'-'*8}")

    baseline_tp = None
    conc_results = []
    req = make_request(content="user@example.com test")

    for n_threads in thread_counts:
        errors = []
        barrier = threading.Barrier(n_threads)

        def worker():
            try:
                barrier.wait()
                for _ in range(evals_per_thread):
                    engine.run_pre(dict(req))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        start = time.monotonic()
        for t in threads: t.start()
        for t in threads: t.join()
        wall_ms = (time.monotonic() - start) * 1000

        total = n_threads * evals_per_thread
        throughput = total / (wall_ms / 1000)
        if baseline_tp is None:
            baseline_tp = throughput
        scaling = throughput / baseline_tp

        print(f"  {n_threads:<10} {wall_ms:<12.1f} {throughput:<14,.0f}/s {scaling:<10.2f}x {len(errors):<8}")
        conc_results.append({"threads": n_threads, "throughput": round(throughput), "scaling": round(scaling, 3), "errors": len(errors)})

    # Correctness under load (larger sample)
    print("\n  Correctness validation:")
    gate_policy = CustomPolicy({"name": "gate", "rules": [
        {"name": "block-gpt", "hook": "pre", "action": "block",
         "match": {"model": {"startswith": "gpt-4"}}, "message": "blocked"},
        {"name": "warn-opus", "hook": "pre", "action": "warn",
         "match": {"model": {"contains": "opus"}}, "message": "warning"},
    ]})
    engine2 = PolicyEngine()
    engine2._policies = [gate_policy]

    n_correctness_threads = 50
    evals_per = 1000 if not QUICK_MODE else 200
    false_blocks = []
    missed_blocks = []

    def correctness_worker(tid):
        for i in range(evals_per):
            if tid % 2 == 0:
                req = {"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": f"t{tid}"}]}
                _, block, _ = engine2.run_pre(req)
                if block is not None:
                    false_blocks.append((tid, i))
            else:
                req = {"model": "gpt-4o", "messages": [{"role": "user", "content": f"t{tid}"}]}
                _, block, _ = engine2.run_pre(req)
                if block is None:
                    missed_blocks.append((tid, i))

    threads = [threading.Thread(target=correctness_worker, args=(i,)) for i in range(n_correctness_threads)]
    for t in threads: t.start()
    for t in threads: t.join()

    total_evals = n_correctness_threads * evals_per
    print(f"    Evaluations: {total_evals:,} ({n_correctness_threads} threads × {evals_per})")
    print(f"    False blocks: {len(false_blocks)}")
    print(f"    Missed blocks: {len(missed_blocks)}")
    status = "PASS" if not false_blocks and not missed_blocks else "FAIL"
    print(f"    Status: {status}")

    return {"scaling": conc_results, "correctness": {"status": status, "total_evals": total_evals,
             "false_blocks": len(false_blocks), "missed_blocks": len(missed_blocks)}}


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE 6: SOAK TEST
# ═══════════════════════════════════════════════════════════════════════════════

def run_soak():
    from aiwarden.policies.builtin.pii import PIIPolicy
    from aiwarden.policies.builtin.budget import BudgetPolicy
    from aiwarden.policies.custom.policy import CustomPolicy
    from aiwarden.policies.engine import PolicyEngine
    from aiwarden import config
    config.ENABLED = False

    print("\n" + "=" * 70)
    print(" PHASE 6: SOAK TEST")
    print("=" * 70)

    engine = PolicyEngine()
    engine._policies = sorted([
        BudgetPolicy({"limit": 999999.0}),
        CustomPolicy({"name": "c", "rules": make_rules(20)}),
        PIIPolicy({}),
    ], key=lambda p: p.priority)

    req = make_request(content="user@example.com test content for soak")
    total_evals = 1_000_000 if not QUICK_MODE else 100_000
    window_size = 10_000

    windows = []
    tracemalloc.start()
    mem_start = tracemalloc.get_traced_memory()[0]

    for w in range(total_evals // window_size):
        start = time.perf_counter()
        for _ in range(window_size):
            engine.run_pre(dict(req))
        elapsed = time.perf_counter() - start
        windows.append((elapsed / window_size) * 1_000_000)

    mem_end = tracemalloc.get_traced_memory()[0]
    tracemalloc.stop()
    mem_growth_kb = (mem_end - mem_start) / 1024

    n_windows = len(windows)
    q1 = statistics.mean(windows[:n_windows // 4])
    q4 = statistics.mean(windows[-n_windows // 4:])
    drift_pct = (q4 - q1) / q1 * 100

    print(f"\n  Total evaluations: {total_evals:,}")
    print(f"  First quarter: {q1:.2f}μs | Last quarter: {q4:.2f}μs | Drift: {drift_pct:+.2f}%")
    print(f"  Memory growth: {mem_growth_kb:.1f}KB ({mem_growth_kb * 1024 / total_evals:.2f} bytes/eval)")
    print(f"  Status: {'PASS' if abs(drift_pct) < 10 else 'DEGRADATION DETECTED'}")

    return {"total_evals": total_evals, "first_quarter_us": round(q1, 2),
            "last_quarter_us": round(q4, 2), "drift_pct": round(drift_pct, 2),
            "memory_growth_kb": round(mem_growth_kb, 1)}


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE 7: THROUGHPUT SATURATION
# ═══════════════════════════════════════════════════════════════════════════════

def run_throughput():
    from aiwarden.policies.builtin.pii import PIIPolicy
    from aiwarden.policies.builtin.budget import BudgetPolicy
    from aiwarden.policies.custom.policy import CustomPolicy
    from aiwarden.policies.engine import PolicyEngine
    from aiwarden import config
    config.ENABLED = False

    print("\n" + "=" * 70)
    print(" PHASE 7: THROUGHPUT SATURATION")
    print("=" * 70)

    engine = PolicyEngine()
    engine._policies = sorted([
        BudgetPolicy({"limit": 999999.0}),
        CustomPolicy({"name": "c", "rules": make_rules(20)}),
        PIIPolicy({}),
    ], key=lambda p: p.priority)
    req = make_request(content="user@example.com please help")

    # 5 independent throughput measurements
    throughputs = []
    count = 50_000 if not QUICK_MODE else 20_000
    for _ in range(5):
        gc.collect(); gc.disable()
        start = time.perf_counter()
        for _ in range(count):
            engine.run_pre(dict(req))
        elapsed = time.perf_counter() - start
        gc.enable()
        throughputs.append(count / elapsed)

    mean_tp = statistics.mean(throughputs)
    stdev_tp = statistics.stdev(throughputs)
    t_crit = _t_critical(5)
    se = stdev_tp / math.sqrt(5)
    ci_low = mean_tp - t_crit * se
    ci_high = mean_tp + t_crit * se

    print(f"\n  Single-thread max throughput (5 runs × {count:,} evals):")
    print(f"    Mean: {mean_tp:,.0f} evals/sec")
    print(f"    95% CI: [{ci_low:,.0f}, {ci_high:,.0f}] (t-dist, df=4)")
    print(f"    CV: {stdev_tp/mean_tp*100:.1f}%")
    print(f"    Per-call: {1_000_000/mean_tp:.2f}μs")

    return {"mean_throughput": round(mean_tp), "ci_95": [round(ci_low), round(ci_high)],
            "cv_pct": round(stdev_tp / mean_tp * 100, 2),
            "per_call_us": round(1_000_000 / mean_tp, 2)}


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    env = get_environment()
    print("=" * 70)
    print(" AI-WARDEN PERFORMANCE VALIDATION")
    print(f" Mode: {'QUICK' if QUICK_MODE else 'FULL'} | Runs: {NUM_RUNS} | Iters: {INNER_ITERS}")
    print(f" Python: {env['python_version'].split()[0]} | {env['platform']}")
    print(f" CPU: {env['processor']} ({env['cpu_count']} cores)")
    print(f" Commit: {env['commit_sha']}")
    print("=" * 70)

    all_results = {"environment": env}

    core = run_core_benchmarks()
    all_results["core"] = [r.to_dict() for r in core]

    e2e = run_e2e_benchmarks()
    all_results["end_to_end"] = [r.to_dict() for r in e2e]

    async_results = run_async_benchmarks()
    all_results["async"] = async_results

    scalability = run_scalability()
    all_results["scalability"] = scalability

    concurrency = run_concurrency()
    all_results["concurrency"] = concurrency

    soak = run_soak()
    all_results["soak"] = soak

    throughput = run_throughput()
    all_results["throughput"] = throughput

    # ── Summary ────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print(" SUMMARY")
    print("=" * 70)

    engine_lat = core[5]  # engine_pre_4policies
    e2e_lat = e2e[1]  # full_interception_path
    print(f"\n  Policy engine only (4 policies): {engine_lat.mean:.2f}μs (CI: [{engine_lat.ci_95[0]:.2f}, {engine_lat.ci_95[1]:.2f}])")
    print(f"  Full interception path:           {e2e_lat.mean:.2f}μs (CI: [{e2e_lat.ci_95[0]:.2f}, {e2e_lat.ci_95[1]:.2f}])")
    print(f"  Overhead ratio (full/engine):     {e2e_lat.mean / engine_lat.mean:.1f}x")
    print(f"  Max throughput:                   {throughput['mean_throughput']:,}/s (CI: [{throughput['ci_95'][0]:,}, {throughput['ci_95'][1]:,}])")
    print(f"  Soak drift ({soak['total_evals']:,} evals):    {soak['drift_pct']:+.2f}%")
    print(f"  Correctness:                      {concurrency['correctness']['status']} ({concurrency['correctness']['total_evals']:,} evals)")
    overhead_vs_2s = e2e_lat.mean / 2_000_000 * 100
    print(f"  Full overhead vs 2s LLM call:     {overhead_vs_2s:.4f}%")

    # Save
    output_path = "benchmarks/perf_validation_results.json"
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\n  Results saved: {output_path}")


if __name__ == "__main__":
    main()

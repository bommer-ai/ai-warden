#!/usr/bin/env python3
"""
Benchmark regression detection for CI.

Compares current benchmark results against a committed baseline.
Fails (exit 1) if any benchmark exceeds threshold.

Usage:
    python benchmarks/check_regression.py <results.json> <baseline.json>
    python benchmarks/check_regression.py <results.json> <baseline.json> --strict

Exit codes:
    0 — no regression detected
    1 — regression detected
    2 — usage error
    3 — new benchmarks detected (update baseline)
"""
import json
import sys

MEAN_FACTOR = 1.3   # allow 30% degradation
P99_FACTOR = 1.5    # allow 50% P99 degradation

STRICT_MEAN_FACTOR = 1.15
STRICT_P99_FACTOR = 1.3


def load(path):
    with open(path) as f:
        return json.load(f)


def check_regressions(results, baseline, strict=False):
    mean_factor = STRICT_MEAN_FACTOR if strict else MEAN_FACTOR
    p99_factor = STRICT_P99_FACTOR if strict else P99_FACTOR

    failures = []
    passes = []
    new_benchmarks = []

    # Build baseline lookup from the new format
    baseline_map = {}
    for entry in baseline.get("core", []):
        baseline_map[entry["name"]] = entry

    # Check results against baseline
    for entry in results.get("core", []):
        name = entry["name"]
        b = baseline_map.get(name)
        if b is None:
            new_benchmarks.append(name)
            continue

        mean_thresh = b["mean_threshold_us"] * mean_factor
        p99_thresh = b["p99_threshold_us"] * p99_factor

        current_mean = entry.get("mean_us", 0)
        current_p99 = entry.get("p99_us", 0)

        mean_ok = current_mean <= mean_thresh
        p99_ok = current_p99 <= p99_thresh

        record = {
            "name": name,
            "mean_us": current_mean,
            "mean_thresh": mean_thresh,
            "p99_us": current_p99,
            "p99_thresh": p99_thresh,
            "mean_ok": mean_ok,
            "p99_ok": p99_ok,
        }

        if not mean_ok or not p99_ok:
            failures.append(record)
        else:
            passes.append(record)

    return failures, passes, new_benchmarks


def print_report(failures, passes, new_benchmarks, strict):
    total = len(failures) + len(passes)
    mode = "STRICT" if strict else "STANDARD"
    print("=" * 70)
    print(f" BENCHMARK REGRESSION CHECK ({mode})")
    print("=" * 70)
    print(f"\n  Checked: {total} benchmarks")
    print(f"  Passed:  {len(passes)}")
    print(f"  Failed:  {len(failures)}")
    if new_benchmarks:
        print(f"  New (no baseline): {len(new_benchmarks)}")

    print(f"\n  {'Benchmark':<35} {'Mean(μs)':<12} {'Thresh':<12} {'Status'}")
    print(f"  {'-'*35} {'-'*12} {'-'*12} {'-'*8}")
    for r in passes:
        print(f"  {r['name']:<35} {r['mean_us']:<12.3f} {r['mean_thresh']:<12.1f} PASS")
    for r in failures:
        print(f"  {r['name']:<35} {r['mean_us']:<12.3f} {r['mean_thresh']:<12.1f} FAIL")

    if new_benchmarks:
        print(f"\n  New benchmarks (update baseline):")
        for name in new_benchmarks:
            print(f"    {name}")

    if failures:
        print(f"\n  REGRESSIONS:")
        for r in failures:
            if not r["mean_ok"]:
                print(f"    {r['name']}: mean {r['mean_us']:.3f}μs > {r['mean_thresh']:.1f}μs")
            if not r["p99_ok"]:
                print(f"    {r['name']}: P99 {r['p99_us']:.3f}μs > {r['p99_thresh']:.1f}μs")

    print()


def main():
    if len(sys.argv) < 3:
        print("Usage: check_regression.py <results.json> <baseline.json> [--strict]")
        sys.exit(2)

    results_path = sys.argv[1]
    baseline_path = sys.argv[2]
    strict = "--strict" in sys.argv

    try:
        results = load(results_path)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading results: {e}")
        sys.exit(2)

    try:
        baseline = load(baseline_path)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading baseline: {e}")
        sys.exit(2)

    failures, passes, new_benchmarks = check_regressions(results, baseline, strict)
    print_report(failures, passes, new_benchmarks, strict)

    if failures:
        print("  Result: FAIL — performance regression detected")
        sys.exit(1)
    elif new_benchmarks:
        print("  Result: NEW BENCHMARKS — update baseline")
        sys.exit(3)
    else:
        print("  Result: PASS — no regressions")
        sys.exit(0)


if __name__ == "__main__":
    main()

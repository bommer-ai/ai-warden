# AI-Warden Performance Benchmarks

## Run Details

| Field | Value |
|-------|-------|
| Date | 2026-06-22T17:58:18+0530 |
| Commit | `c59df80` |
| Mode | full (30 runs × 2000 iters = 60,000 measurements/benchmark) |
| Python | 3.14.6 |
| Platform | macOS-26.3-arm64-arm-64bit-Mach-O |
| CPU | arm (12 cores) |

---

## Core Latency (policy engine, capture disabled)

| Benchmark | Mean (μs) | P50 | P95 | P99 | P99.9 | Throughput |
|-----------|-----------|-----|-----|-----|-------|------------|
| custom_1rule_miss | 0.544 | 0.54 | 0.58 | 0.71 | 0.88 | 1,838,148/s |
| custom_1rule_match | 0.796 | 0.79 | 0.83 | 1.00 | 1.67 | 1,255,926/s |
| pii_1kb_5pat | 85.944 | 85.00 | 91.08 | 97.00 | 107.50 | 11,636/s |
| budget_cycle | 4.728 | 4.67 | 4.92 | 6.00 | 10.12 | 211,500/s |
| tools_builtin_match | 4.767 | 4.71 | 4.92 | 6.04 | 8.29 | 209,767/s |
| engine_pre_4policies | 11.467 | 11.33 | 11.83 | 14.46 | 19.79 | 87,204/s |
| extract_caller | 10.701 | 10.58 | 11.08 | 13.50 | 20.71 | 93,447/s |

## End-to-End (full production path, capture enabled)

| Benchmark | Mean (μs) | P50 | P95 | P99 | P99.9 | Throughput |
|-----------|-----------|-----|-----|-----|-------|------------|
| build_and_capture | 68.598 | 62.54 | 102.46 | 128.04 | 169.71 | 14,578/s |
| full_interception_path | 95.621 | 90.46 | 128.50 | 153.75 | 197.58 | 10,458/s |
| multi_message_20msg_pre | 77.278 | 76.12 | 82.46 | 98.33 | 143.96 | 12,940/s |

## Async Pathway

| Metric | Value |
|--------|-------|
| ContextVar isolation (100 tasks) | 100/100 correct |
| Mean eval latency | 4.57μs |
| P99 eval latency | 5.58μs |

---

## Scalability — Rule Count

| Rules | Mean (μs) | 95% CI | Per-rule (ns) | Throughput |
|-------|-----------|--------|---------------|------------|
| 1 | 0.55 | [0.55, 0.56] | 554.0 | 1,805,223/s |
| 10 | 4.06 | [4.03, 4.09] | 406.3 | 246,152/s |
| 100 | 39.05 | [38.91, 39.18] | 390.5 | 25,610/s |
| 500 | 195.43 | [194.75, 196.10] | 390.9 | 5,117/s |
| 1,000 | 391.70 | [390.57, 392.82] | 391.7 | 2,553/s |
| 2,500 | 966.08 | [963.57, 968.59] | 386.4 | 1,035/s |
| 5,000 | 1941.95 | [1932.87, 1951.03] | 388.4 | 515/s |
| 10,000 | 3856.59 | [3842.68, 3870.51] | 385.7 | 259/s |

## Scalability — Payload Size (PII, 5 patterns)

| Size | Mean (μs) | 95% CI | Per-KB (μs) | Throughput |
|------|-----------|--------|-------------|------------|
| 0.1 KB | 9.84 | [9.74, 9.93] | 98.4 | 101,666/s |
| 1 KB | 86.71 | [86.50, 86.93] | 86.7 | 11,532/s |
| 10 KB | 842.34 | [840.91, 843.78] | 84.2 | 1,187/s |
| 100 KB | 8337.10 | [8307.57, 8366.62] | 83.4 | 120/s |
| 500 KB | 41962.65 | [40850.00, 43075.31] | 83.9 | 24/s |

---

## Concurrency Scaling

| Threads | Throughput | Scaling | Errors |
|---------|------------|---------|--------|
| 1 | 71,193/s | 1.00x | 0 |
| 2 | 73,977/s | 1.04x | 0 |
| 4 | 73,187/s | 1.03x | 0 |
| 8 | 73,684/s | 1.03x | 0 |
| 16 | 73,722/s | 1.04x | 0 |
| 32 | 73,016/s | 1.03x | 0 |
| 64 | 70,456/s | 0.99x | 0 |
| 128 | 44,886/s | 0.63x | 0 |
| 256 | 42,793/s | 0.60x | 0 |
| 500 | 31,447/s | 0.44x | 0 |

**Correctness under load:** PASS — 50,000 evaluations, 0 false blocks, 0 missed blocks

---

## Soak Test

| Metric | Value |
|--------|-------|
| Total evaluations | 1,000,000 |
| First quarter mean | 55.91μs |
| Last quarter mean | 56.30μs |
| Drift | +0.71% |
| Memory growth | 20.3 KB |
| Memory per eval | 0.02 bytes |

---

## Throughput Saturation

| Metric | Value |
|--------|-------|
| Max single-thread throughput | **73,078 evals/sec** |
| 95% CI | [72,650, 73,507] |
| CV | 0.47% |
| Per-call latency | 13.68μs |

---

## Summary

- **Full interception overhead:** 95.62μs per LLM call
- **Policy engine only:** 11.47μs
- **Overhead vs 2s LLM call:** 0.0048%
- **Max throughput:** 73,078 evals/sec
- **Scalability:** O(N) linear, ~369 ns/rule
- **Soak stability:** +0.71% drift over 1,000,000 evals
- **Correctness:** PASS (50,000 evals, 0 errors)
- **Async isolation:** 100/100 tasks isolated


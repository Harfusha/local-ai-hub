# Performance Profiling & Regression Budget (HUB-072)

## 1. Overview & Workload Baseline

This document defines performance budgets and baseline benchmark results for Local AI Hub core operations. Benchmarks are evaluated on Windows 11 / Python 3.13 with SQLite backend, designed for developer workstations with single 16GB VRAM GPUs and multiple concurrent coding agent sessions.

---

## 2. Measured Baselines & Performance Budgets

| Operation | Metric | Measured Baseline | Regression Budget Ceiling | Tool / Benchmark Target |
|---|---|---|---|---|
| **Exact FTS / Code Search** | Cold latency | ~290.4 ms | < 500 ms | `tools/benchmark_exact_search.py` |
| **Exact FTS / Code Search** | Warm query latency | ~12.5 ms | < 50 ms | `tools/benchmark_exact_search.py` |
| **Pending RAG Scan** | Median duration (10k items) | 9.20 ms | < 20 ms | `tools/benchmark_preprocess_pending.py` |
| **Pending RAG Scan (Legacy)**| Median duration | 12.54 ms | - | -26.6% improvement in current architecture |
| **Code Index Inventory** | Bounded batch median | 171.47 ms | < 250 ms | `tools/benchmark_code_index_inventory.py` |
| **Code Index Inventory** | Bounded batch p95 | 194.18 ms | < 300 ms | `tools/benchmark_code_index_inventory.py` |
| **Code Index Peak Memory** | Peak Python heap | 7.79 MB | < 12 MB | Bounded batch vs 15.15 MB full materialization (-48.5%) |
| **Storage Admission** | Physical bytes released | 7.05 MB | Within max | `tools/benchmark_code_index_budget.py` (evicted 6 stale files) |
| **Response Token Economy** | Serialized envelope | <= 8192 tokens | <= 8192 tokens | Automatic envelope budget clamp (`TokenEconomyPolicy`) |

---

## 3. Concurrency & Resource Isolation Contracts

1. **SQLite Lock Wait Budget**:
   - Write lock acquisition timeout: <= 5.0 seconds.
   - Read lock contention wait: 0ms with WAL mode enabled.
2. **GPU & Accelerator Budget (16GB VRAM Target)**:
   - Foreground inference target: max 9GB allocated for `qwen2.5-coder:7b` / `qwen3.5:9b`.
   - Preprocessing target: max 2.2GB for `qwen2.5-coder:1.5b`.
   - VRAM headroom: >= 4.5GB reserved for OS display and agent context buffers.
3. **Async Backpressure**:
   - Queue depth ceiling: 50 concurrent tasks per worker pool.
   - Cooperative timeouts: all background commands drain child stdout/stderr and terminate process trees on deadline expiration.

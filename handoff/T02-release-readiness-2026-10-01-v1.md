# T02 Release Readiness — 2026-10-01 v1

## Decision

**T02 is open; its acceptance is not complete.** The current consolidated plan at `C:\Users\Adam\.local-ai-hub\docs\superpowers\plans\2026-10-01-hub-consolidated-completion.md:154` still marks T02 `active` and requires confirmation of the admission-flake RCA plus a plan-grade quality/tail baseline. This report is T02-specific; it is not a Hub release approval. No tests, benchmarks, load runs, root edits, or T20 slot use occurred while preparing it.

## Acceptance status

| Acceptance area | Status | Evidence and remaining gap |
|---|---|---|
| Admission/cancel correctness | **Partial** | The historical receipt records `cancel()` observing `running` instead of `cancelled`. Attempt-1 diagnostics retained live worker `async-job-fe63de95` after manager close; reaper failures then repeated with the same ID. Attempt 3 records the same chain with `async-job-b6bb8fe2`. This confirms a queue-cancel/worker-retention cascade in those attempts. The original `2/25` target selector/order manifest is still missing. |
| Two historical `ERROR` nodes | **Partial; allocation cause unconfirmed** | Attempt 1 lists `test_run_benchmark_is_isolated_and_preserves_existing_scratch_data` and `test_component_baselines_measure_graph_rag_batch_parent_seed_and_serena` as errors. Saved output includes `ResourceWarning: unclosed database` / `PytestUnraisableExceptionWarning`, but no SQLite allocation traceback. The live worker and cleanup cascade are evidenced; exact ownership of those unclosed connections is not. |
| Original `2/25` report | **Unverified** | Receipt `C:\Users\Adam\AppData\Local\Temp\codex-t02-flake-20260930T201729-b78b0be9.json` (SHA-256 `F602295B4B953034F4DADACE78AF297E448FD4AA8DA28343BCB7C091B4D07FE2`) stores a whole-file command, `attempts_target=25`, three attempt records, and `reverse_control=null`. It has no 25-node manifest. The first attempt's 16,000-character failure excerpt starts mid-trace; there are no separate original stdout/stderr logs. Its `tests/test_surface_benchmarks.py` file hash is `A2A577EE95BB7FA9057F1C03BDB1A61957F6E6E45DD5EBE5C4ECA1C43014F4B`, not the inspected worktree hash `F4E0D299384B3B3C9443390EC1001ED6B6F38D5606C0B45D8D774DED816DCF00`. The two JSON-capture failures in the separate 90-node order-control receipt are instrumentation contamination, not proof of the original report. |
| Candidate selector batch | **Partial** | A saved candidate prerequisite batch records 12 passed; the handoff still lists the four pinned selectors as pending for acceptance on one pinned snapshot. T20's individual root selector receipts do not establish the combined T02 gate or recover the missing original list. |
| Repeatability gate | **Incomplete** | The separate 90-test whole-file study completed ordered attempts 1–19 successfully; attempt 20 failed in `hub_queue_admission`, attempt 21 was terminated before a receipt, and attempts 22–25 did not run. Its reverse control passed, but it is not the original 25-node suite or a completed 25-attempt acceptance run. |
| Six-case performance matrix | **Partial; not plan-grade** | The manifest defines files `{100, 10000, 100000}` × RAG chunks `{10000, 100000}`. Two model-free per-case records exist; four 100k-heavy cases remain deferred to T20's exclusive slot. Current receipt says 2/6, `matrix_acceptance=unavailable`, `plan_grade=false`, inference skipped. |
| Paired baseline/candidate performance | **Unavailable** | Contract requires two complete six-case records, each with 1000 light samples, 30 comparison samples, concurrency `{1,4,16,32}`, emitted path/hash, and matching workload/config/hardware fingerprints. No valid pair exists. Paired comparison uses a 10% regression tolerance; no plan-grade cold/warm p95/p99 result is established. |
| Golden and configured inference quality | **Unavailable** | All eight matrix operations must be true in summaries, rows, and nested cases: symbols, graph, affected tests, retrieval relevance, code generation, vision, speech, and `context_pack`. Code generation, vision, and speech require configured Hub inference; speech also needs verified audio bytes and exact transcript. Required configured Hub TOML/state and those receipts are missing. |
| Master-plan latency targets | **Unverified** | No accepted receipt establishes warm health p95 ≤50 ms; cached metadata/status/artifact/lease reads ≤150 ms; warm symbol/search/code-index p95 ≤300 ms on 10k files; deterministic-only context pack p95 ≤750 ms; warm RAG search p95 ≤750 ms on 100k chunks; or queue admission p95 ≤150 ms. |

## Historical flake finding

The original receipt is a bounded but incomplete record, not a 25-selector manifest. In attempt 2 the queue selector failed at `tests/test_surface_benchmarks.py:133` because state was `running`, not `cancelled`. Attempt 1 records a live `async-job-fe63de95` across manager close/teardown; subsequent benchmark calls fail closed because scratch cleanup remains pending. Attempt 3 again records a queue failure and cleanup pending for `async-job-b6bb8fe2`. This is concrete evidence of the admission-to-worker cleanup cascade.

The two `ERROR` node IDs above have SQLite `ResourceWarning` evidence, but their connection allocation traceback is absent (`tracemalloc` was not enabled). The saved data does not prove those unclosed connections were caused by the same worker. Keep that link **unconfirmed**.

Separate later order-control evidence shows two JSON tests failing when `T02_TRACE` precedes JSON on captured stdout. Both failed in ordered and reverse order. That immediate instrumentation issue is distinct from the original admission/cleanup record and cannot replace its missing selector list.

## T20 handoff

Proposed bounded ordered/reverse selector set is in [T02-admission-reproduction-manifest-2026-10-01-v1.json](T02-admission-reproduction-manifest-2026-10-01-v1.json). It is explicitly a surrogate, not the original list. Run only after T13 is GREEN and T20 grants a correctness-test slot; pin root revision and all input hashes. No performance benchmark is part of that manifest.

The four-selector candidate batch, saved per-case baselines, and instrumentation correction remain useful partial evidence. They do not satisfy root integration, the original RCA, the 25-attempt gate, the paired six-case matrix, or model-quality acceptance. Keep T02 open until those applicable receipts exist.

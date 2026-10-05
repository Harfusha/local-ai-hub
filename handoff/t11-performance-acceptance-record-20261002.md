# T11 100k performance acceptance record — 2026-10-02

Status: **REVIEW / OPEN**. The planned benchmark already ran twice on 2026-10-01; no new run was started. Both runs failed, so no GREEN performance receipt exists.

## Run 1 — fingerprinted resumed candidate

- Root: `C:\Users\Adam\.codex\worktrees\f678\.local-ai-hub`
- Command: `python -B -m pytest -q -s --tb=short -p no:cacheprovider tests/test_rag_quality_contract.py::test_retrieval_latency_and_peak_memory_baseline`
- Environment: `PYTHONDONTWRITEBYTECODE=1`, `RAG_BENCHMARK=1`.
- Result: `1 failed in 46.40s`; 100k p95 `972.658 ms` at configured batch `4096`; limit `750 ms`.
- Source SHA-256: `db181093f53f0d6666a890413bfea5f52359890ce8236def0160df744cf0c6ff`.
- Harness SHA-256: `81c17571143a4256cf9d9a9017137b82cfd564cd4f45b21e48e5f3fbecba7a3c`.
- The test asserted before writing its normal JSON receipt; result is preserved in the run log/checkpoint.

## Run 2 — one-slot diagnostic, temporary batch-cap experiment

- Command: same selector and flags as Run 1.
- Environment additionally set `RAG_BENCHMARK_RECEIPT=C:\Users\Adam\.codex\worktrees\f678\.local-ai-hub\handoff\t11-rag-100k-green-20261001.json`.
- Result: `1 failed in 57.47s`; 100k p95 `1698.727 ms` at configured batch `512`; limit `750 ms`.
- At run time, candidate `rag.py` SHA-256 was `CB4362E19E316B22C020A7AF3706E55DF278BE95C508750EBBB9469C5C97FFA9`; harness SHA-256 was `B7DC4FC939E63152C7904B10DCDA666FC5916E5FC6DE3707FEE718D4E18B6825`. This version had a temporary 12 MiB batch cap; the edit was reverted. Batch 512 was below that cap.
- The normal GREEN receipt was not written because assertion preceded serialization. Manual failure receipt: `handoff/t11-rag-100k-red-20261001.json`, SHA-256 `B068FAB8FE1B5E29F874D5B7B0930CBA3659E08E2EC0A4FEBF2C2F91CB160D0D`.

## Current candidate and changed files

- Current RAG source includes the warm-search metadata-lock fix (SHA-256 `231ca7c6ba2af653eae20af1bc64bea949a028abbcee68cbff32838a42608c19`). It was not covered by either 100k run. Current offline T11 suite is `176 passed, 3 skipped in 39.49s`; benchmark, live Ollama, and ingestion benchmark were skipped.
- T11 changes from this work: `src/local_ai_hub/rag.py`, `tests/test_rag_hybrid.py`, and handoff/checkpoint files under `handoff/`. Benchmark commands themselves changed no workspace files. Other dirty source/test files were inherited and remain preserved.
- Do not rerun the 100k selector without an explicitly assigned benchmark slot. Root and `/api/context/pack` remain untouched; root integration stays T20-owned.

## Follow-up — warm-search snapshot optimization, 2026-10-02

- Candidate-only delta reads workspace `embedding_space` metadata inside the existing vector-scan snapshot. It takes `BEGIN IMMEDIATE` only when the read fails or metadata differs, then rechecks under lock before writing. Exact vector `embedding_space` filtering is unchanged.
- TDD: new regression first failed against pre-change code because metadata access observed `connection.in_transaction=False`; after the implementation it passed.
- Targeted command: `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_rag_hybrid.py::test_warm_search_reads_embedding_space_from_vector_snapshot tests/test_rag_hybrid.py::test_warm_search_skips_embedding_space_write_lock tests/test_rag_hybrid.py::test_search_reports_pending_rebuild_for_partial_embedding_space tests/test_rag_hybrid.py::test_search_cache_key_tracks_runtime_embedding_space`
- Result: `4 passed in 0.79s`. `git diff --check -- src/local_ai_hub/rag.py tests/test_rag_hybrid.py` passed.
- Candidate patch: `handoff/t11-warm-search-snapshot-20261002.patch`, SHA-256 `bfaaf0a9b66d7b3e6c742a049e19553583a2cfc6dd43a6d6a7dcc9f817b5af11`. Its two applied files match candidate postimages after LF normalization; raw hashes differ because of CRLF/LF conversion.
- T20 received the patch and evidence. It is review/adaptation only: current T20 root omits the metadata read/write path already, so source hunk is not directly applicable. No root files were modified.
- This delta has no benchmark result. The two earlier 100k RED measurements above remain the blocker; the user explicitly directed not to repeat that benchmark. No performance improvement is claimed.

## Follow-up — offline RAG/embedding/reranker/ingestion suite, 2026-10-02

- Command: `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_rag_read_bounds.py tests/test_rag_fragment_cache.py tests/test_rag_hybrid.py tests/test_rag_quality_contract.py tests/test_rag_dedup.py tests/test_t11_project_policy_consumers.py tests/test_t11_rag_ingestion_contract.py tests/test_t11_rag_seed_integrity.py tests/test_reranker_cache_identity.py tests/test_embedding_cache.py tests/test_embedding_batch_deduplication.py tests/test_model_release_lifecycle.py`
- Result: `177 passed, 3 skipped in 52.47s`. Skips: 100k retrieval benchmark, live Ollama verification, ingestion benchmark. This is offline contract coverage, not latency/live-model acceptance.

## Follow-up — bounded vector scan diagnosis, 2026-10-02

- Static diagnosis: retrieval exhaustively scans every compatible vector, computes row norms and query dots, and issues one keyset SELECT per batch. This points to full-scan scoring/page overhead; no profiler ran.
- Rejected experiment: one long-lived cursor would avoid repeated keyset SELECTs, but failed existing contract `test_vector_cursor_closes_before_scoring_and_after_search` (`cursor_open_during_dot` became true). Reverted; statement VM stays idle during scoring.
- Candidate optimization removes redundant per-batch candidate `lexsort` and path/chunk/hash arrays before heap offers. `offer()` applies a total deterministic order. Explicit cutoff-tie ordering remains. Candidate patch and pins are in `handoff/t11-vector-scan-ordering-opt-20261002.json`.
- TDD: regression RED before source edit (unexpected `np.lexsort` call); focused GREEN: `4 passed in 0.63s`. `tests/test_rag_quality_contract.py tests/test_rag_hybrid.py`: `35 passed, 1 skipped in 4.60s`; only skip is the gated 100k benchmark.
- No profile or benchmark ran because T02 holds exclusive CPU benchmark slot. Existing p95 REDs remain 972.658 ms (batch 4096) and 1698.727 ms (batch 512), 750 ms limit. Candidate has no measured speedup claim.

## Root integration checkpoint — 2026-10-02

- T20 reports root-current patch integration after exact patch/source/test SHA checks and `git apply --check`. Postimage pins match scratch patch output: `rag.py` `88836fe1782a3d01ed3606bc8dd2fccc40168ac4411c7cfb73b67da802933c27`; `test_rag_quality_contract.py` `273c1eea3645f78596009340096d2c381fd8749fe71ce8f2ecb7a8aece723572`. This is T20 integration evidence; T11 did not write root.
- Three root ranking selectors remain pending. T02 owns exclusive slot; T20 reports its gate at 10 passed / 2 failed with fixes in progress. Do not start pytest until T02 explicitly releases slot.
- Verification manifest: `handoff/t11-root-current-ranking-20261002.json`. Benchmark/profile remain prohibited until slot release. Latency acceptance remains RED; no gain claimed.

## Acceptance status checkpoint — 2026-10-02

- Status remains **REVIEW / OPEN**, not done. T20 has integrated ranking patch. Three exact root selectors and expected postimage hashes remain in `handoff/t11-root-current-ranking-20261002.json`.
- Wait for an explicit T20 test-slot assignment after T15/T02. Run no tests before assignment. Do not repeat or duplicate benchmark.
- Latency gate remains RED / OPEN; existing measurements are unchanged and no new performance claim is made.

## Follow-up — in-place vector score buffers, 2026-10-02

- Candidate T11 worktree change reuses NumPy dot output as score output, divides in-place, zeros invalid rows in-place, and sanitizes non-finite values in-place. This removes a separate zero score vector plus boolean-indexed dot/norm/division temporaries per batch.
- TDD: `test_vector_search_reuses_norm_buffer_for_scores` failed before source edit because scoring allocated `np.zeros(len(batch))`; passed after the change.
- Non-benchmark command: `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_rag_quality_contract.py tests/test_rag_hybrid.py` — `36 passed, 1 skipped in 4.25s`. Skip is gated 100k benchmark.
- Candidate patch: `handoff/t11-score-buffer-opt-20261002.patch`; exact pre/post hashes and scratch apply-check are in `handoff/t11-score-buffer-opt-20261002.json`. No root files changed.
- No paired benchmark/profile ran. Earlier p95 REDs (972.658 ms / 1698.727 ms against 750 ms) remain. Treat this as an unmeasured candidate; do not claim speedup or alter threshold.

## Slot checkpoint — 2026-10-02

- One current T20/T02 snapshot shows T02 owns exclusive slot 04. T02 is preparing the fresh hash-bound manifest; measurement receipt is pending. No T11 test or benchmark run while this slot is active.
- Candidate score-buffer patch remains hash-pinned and its last targeted receipt remains `36 passed, 1 skipped in 4.25s`. Root ranking selectors remain pending explicit T20 assignment after T02/T15.
- Acceptance remains **REVIEW / OPEN**. Existing 100k p95 RED measurements stay 972.658 ms and 1698.727 ms versus 750 ms; no speedup claimed.

## Read-only ingestion, privacy, filtering, and T21 consumer review — 2026-10-02

- Static T21 reconciliation: `project_policy_adapter.py` lazy-loads `local_ai_hub.project_config` and delegates resolver, phase, extension, path, and descent checks to matching exported APIs. Existing consumer tests cover hard-deny, project filters, worktree config inheritance, local config change, and cache invalidation. `project_config.py` remains T21-owned and untouched.
- Ingestion/filter review: source checks raw and metadata-expanded document bytes, embeds bounded batches, atomically replaces a document snapshot, bounds SVG reads, and preserves exact embedding-space filtering. Prior T11 offline receipt covers ingestion/project-policy/seed suites: `177 passed, 3 skipped in 52.47s`, before latest score-buffer delta.
- Privacy boundary: `PathHintUsage.telemetry_metadata()` is path-free; generic telemetry redaction selector exists but was not run in recorded receipts. Explicit diagram ingestion stores/returns `image_path` as RAG document metadata/content; this is outside telemetry. If policy forbids paths in persisted RAG payloads too, that condition remains unresolved.
- New targeted test requested from T20: `tests/test_telemetry_contract.py::test_telemetry_metadata_redacts_absolute_paths_and_payload_like_fields`. No test/benchmark ran during this review. Await explicit serial slot after T02.
- Hash-bound review: `handoff/t11-ingestion-privacy-config-review-20261002.json`.

## Score-buffer static review and privacy slot plan — 2026-10-02

- Independent static review finds element-wise score semantics preserved: finite nonzero rows divide dot scores by norms; invalid rows become zero; zero-query/all-invalid batches remain zero; non-finite outputs become zero. New path reuses dot output and sanitizes in-place. No speed or memory reduction measured.
- Pending genuinely new privacy selector: `tests/test_telemetry_contract.py::test_telemetry_metadata_redacts_absolute_paths_and_payload_like_fields`. Requested a serial T20 slot after T02; no test run until explicit assignment.
- Review pins and limits are in `handoff/t11-score-buffer-opt-20261002.json` and `handoff/t11-ingestion-privacy-config-review-20261002.json`. T21/T03-owned source remains untouched.

## Validation queue update — 2026-10-02

- T02 receives exclusive paired benchmark slot after T03 releases. T11 telemetry privacy selector is next after T02, before T15; remaining T04/T12 focused root checks follow.
- T11 holds until explicit T02 release/T20 assignment. No test or benchmark run.

## End-to-end checkpoint: T21 project-config handoff — 2026-10-02

- Existing T21 checkout verified: `C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub`, HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`. No new worktree.
- T21 `project_config.py` SHA-256 `ffd425b1260b285f25b1d121a7c6bcd585c618b5c7e26415e2ad0a7014196b0b`; T11 untracked candidate SHA-256 `f51cd2bd05ac993139c388ca553ff816c4b39d572182afd433e3fa7430a766d5`. They differ (T11-to-T21 comparison: 4 insertions, 12 deletions); API names match, so source reconciliation remains required.
- T21 test SHA-256 `76c928be383bb262995101ad358cc908015d94efb2957a97edd78de7039ac681`. T11 adapter/consumer test hashes recorded in `handoff/t11-project-config-integration-20261002.json`.
- No tests, benchmarks, or T21 source edits. T02 exclusive validation slot remains blocker; wait for explicit T02 release/T20 assignment.
- Next: T20/T21 reconcile T21-owned source into f678, then assigned project-config/consumer checks, telemetry privacy selector, final offline suite and 100k performance matrix. Acceptance stays OPEN; prior p95 REDs remain 972.658/1698.727 ms vs 750 ms.
- Hash-bound handoff manifest: `handoff/t11-project-config-integration-20261002.json`.

## T21 source integration — 2026-10-02

- Copied T21-owned `src/local_ai_hub/project_config.py` to f678 after verifying both source preimage hashes. T11 postimage now matches T21 SHA-256 `ffd425b1260b285f25b1d121a7c6bcd585c618b5c7e26415e2ad0a7014196b0b`. Reversible source diff: `t11-project-config-source-reconcile-20261002.patch`, SHA-256 `715be0f9390d2d1d81ee8342911f8d445ae778ef3dd25e2bc3755fc4174bee59` (34 lines).
- Added exact T21 test file `tests/test_project_config.py`, SHA-256 `76c928be383bb262995101ad358cc908015d94efb2957a97edd78de7039ac681`; destination was absent. T21 checkout unchanged.
- No tests/benchmarks run. T02 slot remains exclusive. Next: T20 assigns slot, then run transferred project-config and T11 consumer/privacy acceptance plus full 100k matrix; prior p95 remains RED vs 750 ms.

## Static integration check — 2026-10-02

- AST parse passed for six T11 project-config/RAG source and test files. All nine `project_config` symbols imported by the transferred T21 test resolve to top-level definitions; test module contains 66 test cases. This is syntax/import-surface evidence only, not a test receipt.
- `git diff --check` passed for tracked RAG changes and acceptance record. T21 source/test destination hashes still exact. No tests/benchmarks run.

## Master-plan acceptance map — 2026-10-02

- Mapped all six T11 criteria from `docs/superpowers/plans/2026-09-22-hub-quality-performance-master-plan.md:252-263` into the JSON manifest. Criteria 2, 3, 5, and 6 have prior receipts that are stale after current changes; criterion 4 has latest targeted 36/1 receipt but lacks integrated T21 verification; criterion 1/performance remains RED against 750 ms.
- No test/benchmark started. Last live snapshot showed T02 active and no slot release. After release, run project-config/consumer + privacy selectors, full T11 offline contract suite, then 100k matrix. Acceptance remains OPEN.

## Reranker measurement gap — 2026-10-02

- Existing live receipt `t11-transformer-reranker-live-receipt.json` SHA-256 `c052f732251d1306af142cd7c9bc6734cb78ce8961cd3cc7c5a0da01a8f21ea8` proves `embedded=true`, `reranked=true`, `degraded=false`, `fallback=null` with `sentence_transformers.CrossEncoder` / `BAAI/bge-reranker-base` (1 passed in 23.47s). It does not measure p50/p95 latency or peak memory.
- T11 acceptance therefore needs a separate warm reranker latency/resource measurement under T02/T20 slot, alongside but distinct from 100k no-reranker retrieval matrix. No threshold invented; report measured budget for T20.
- No tests/benchmarks run; T02 slot remains active.

## Shared validation slot snapshot — 2026-10-02

- Fresh `wait_threads` snapshot: T02 remains active; first baseline worker builds isolated 100k fixture, CPU 325 seconds, no explicit release. T20 remains active on T08/T09 integration. T11 test/benchmark gate still closed.
- T11 acceptance manifest updated with this observation; no test/benchmark run.

## Reranker budget probe prepared — 2026-10-02

- Extended existing opt-in T11 live acceptance selector with separate 16-candidate reranker measurement: two warmups, 20 timed calls, unique query per call, require 16 computed pairs, emit p50/p95/min/max and model/backend/device. Test SHA-256 `fe56afcd729bc3b591a9b557bce7a6d3fbb616caa6dd0d9697eaea103addc77d`.
- Run only after T02/T20 slot release using the exact command in the integration manifest with `-s`. This is harness preparation only: no live model call, tests, benchmark, or metric receipt occurred. Peak memory remains unmeasured; plan defines no latency threshold, so report measurement without inventing one.

- Probe follow-up: stable backend/device sorting handles null fallback identities. Current test SHA-256 `c4e9a80373a3964e1ef9cb7b1f07114d5dd09bf7a68bdd308d167613dbcb8ee1` (supersedes prior prepared-probe hash). AST parse and `git diff --check` pass; no tests/models executed.

## Slot and reranker probe checkpoint — 2026-10-02

- Reranker probe current source hash `c4e9a80373a3964e1ef9cb7b1f07114d5dd09bf7a68bdd308d167613dbcb8ee1`; output is opt-in within live T11 selector and captures p50/p95 for 16 candidates with unique queries. No model/test invocation.
- Fresh T02 snapshot: one baseline child active, CPU about 374 s, no completed record, no release. T20 completed T08 static inventory but still holds validation for T02.

- Current status refresh: final reranker probe hash remains `c4e9a80373a3964e1ef9cb7b1f07114d5dd09bf7a68bdd308d167613dbcb8ee1`; AST parse and diff-check passed after the last edit. T02 worker remains active after about 18 minutes; T20 is comparing project-config artifacts. No release/assignment observed.

## T21 test refresh — 2026-10-02

- T21 updated `tests/test_project_config.py` after prior handoff. Replaced only f678 T21-owned copy after hash guards; latest T21 and T11 postimage SHA-256 `0196d8fa417dd2b56bfc0d143217d25e2986e1b1b1df6ceffadd3c0eeb9fbcea`. Added selector: `test_project_config_precedence_covers_primary_linked_common_and_worktree_layers`.
- Preserved prior test version in reversible diff `t11-project-config-test-reconcile-20261002.patch`, SHA-256 `25f60f400917db1151b74e1df3a237e6d31a949332ca416915b0a5b0094a9a8f` (3131 lines). AST parse passed; 67 selectors. No tests run; T02 slot active.

## Pre-validation inventory — 2026-10-02

- Hash-bound snapshot covers 5 source files and 14 test files (238 selectors); AST parse passed for all test files. Inventory SHA-256 `dca36e199ed44f367a9cecc0ba81d3a33ef409c8ce31685101c65d184d52d116`. Static presence only, no tests/benchmarks.
- Future receipts must refer to this exact inventory; any source/test hash drift requires refreshing affected evidence. T02/T20 slot still required.

## T20 slot 05: project-config and consumers — 2026-10-02

- Exact command returned **93 passed in 6.63s** (exit 0). Output SHA-256 `ed6219422a2d0ac42e58469fca0816d0f83893908dbb5c80fa3a6672f3acc840`; receipt `handoff\T11-CPU-SLOT-20261002-05\01-project-config-consumers.receipt.json` SHA-256 `46d53337f90d48193495f8d260cef1b3b2992ba692c1ce122098c363f7107138`. Inputs matched pre-validation inventory.
- Per coordinator direction, no further tests or benchmarks started; slot released to T20. Privacy selector, offline suite, retrieval benchmark and reranker probe remain queued.

## Static RAG source and receipt review — 2026-10-02

- Hash-bound read-only review receipt: `handoff\t11-static-review-receipt-20261002.json`, SHA-256 `80b4f0fdcec336ad44f623377d6415f709330d6e45a35c29fe6878ce45e054c8`. No tests or benchmarks run.
- Source review: exact tenant/workspace/embedding-space query filter; cache key contains runtime identity and index generation; ingestion bounded by bytes/batches and publishes replacement atomically with busy retry; SVG read bounded. Project-policy consumer review includes hard-deny/pruning checks.
- Privacy scope resolved in `handoff/t11-privacy-scope-resolution-20261002.json` (SHA-256 `9B3C2EA2FE49584D6AED0C3237FB50F85D5E31B55543229A9430A7D9B6BD7D9A`): written rule covers telemetry paths; RAG `image_path` payload/API is outside current rule. Privacy selector passed in slot 11.
- Next serial queue: privacy selector (1 test), offline T11 suite (12 files), 100k retrieval matrix (12 pairs), live reranker-only latency probe. Require new T20 slot; preserve T02 partial output `-04`.

## T20 validation queue update — 2026-10-02

- T20 order: T07 slot 06, T04 slot 07, T15 correctness slot 08, then T11 privacy/offline in a new exclusive slot; benchmark probe requires separate slot. Queue order is not assignment.
- Pinned all 13 planned T11 selector input hashes to prevalidation inventory in manifest. All match current inventory; no source/test edits or validation run.
- Next T11 action: wait for explicit slot assignment, run privacy selector then offline suite serially, hash receipts, release slot. Benchmark only in separate explicit slot.

## Updated T20 CPU queue — 2026-10-02

- Latest coordinator queue: T07 06, T04 07, T15 correctness 08, T19 release hygiene 09, T13 operational-mode selector 10, T11 privacy/offline 11, T05 tenant selectors 12. T11 slot 11 is queued, not released.
- T07 reports command broker `outcome_unknown` for request `req_c2d855eb1d6f`; do not repeat. T07 remains active while observing runner. T11 rechecked all 13 planned input pins; no drift. No T11 tests/benchmark run.

## CPU queue progress — 2026-10-02

- T07 completed and released slot 06. Two broker selectors remain `outcome_unknown` (`req_c2d855eb1d6f`); no retries and no pass claim.
- T04 is active, has exact root-current pre-run inventory, and requests slot 07 for one import assertion plus two transport files. No T04 run/slot allocation observed yet.
- T11 remains queued slot 11 after T04/T15/T19/T13. All 13 T11 input pins still match; no T11 tests/benchmarks run.

## T11 slot 11 result and remaining gates — 2026-10-02

- T20 assigned and acknowledged exclusive slot `T20-CPU-SLOT-20261002-11`; closeout receipt `handoff/T11-CPU-SLOT-20261002-11/03-slot-closeout.receipt.json`, SHA-256 `9DA5806FA7763D8788FE06BC5E4A1AA20E55D59ED7C35D8D9E1572BE6609E1AB`.
- Immediately before execution, 18 source/test hashes matched inventory SHA-256 `DCA36E199ED44F367A9CECC0BA81D3A33EF409C8CE31685101C65D184D52D116`; post-run check reported 18 matches, 0 mismatches.
- Privacy selector: 1 passed in 0.22s. Offline RAG suite: 179 passed, 3 skipped in 48.76s. Both ran natively under direct user instruction to ignore the broken Local AI Hub. Receipts and output-log hashes are in `handoff/T11-CPU-SLOT-20261002-11/`.
- Skips were gated 100k retrieval benchmark, live Ollama reranker probe, and synthetic seed benchmark. No benchmark ran.
- Slot11 T11-2 through T11-6 offline contracts passed on their then-current pins. Later RAG edits changed `rag.py` and `test_rag_hybrid.py`; those broad results no longer bind the latest hashes. T11-1 and completion-performance remain open.
- Exact remaining project-config test delta and owner-release request are in `handoff/t11-remaining-gaps-owner-release-20261002.json`; no unapproved root test or production hunk transferred.
- Next action: wait for a separate explicit T02/T20 benchmark slot. Do not reuse partial T02 `-04` or infer a slot from queue order.

## Release-priority update — 2026-10-02

- Current priority: functional release first. T11 100k performance and live reranker benchmarks are deferred until post-release; no T20 benchmark slot is requested in this phase.
- Current T11 hash-bound receipts show the privacy selector passed and the offline suite passed 179 tests with 3 skips. The skipped checks include the 100k benchmark and live Ollama/reranker probe.
- No current-hash T11 release-blocking correctness defect is demonstrated by these receipts. Historical 100k REDs (972.658 ms and 1698.727 ms against a 750 ms limit) use older source/test pins; they do not establish a failure on the current candidate.
- Performance acceptance remains OPEN and UNVERIFIED for the current candidate. Revisit the 100k matrix and separate live reranker after functional release.
- No T11 source/test files changed for this priority update; no benchmark or test ran.

## Acceptance audit correction — 2026-10-02

- The transferred T21 tests/test_project_config.py contains 66 cases and its SHA-256 matches the approved T21 checkout, but the file was not included in the f678 slot11 offline command. verification.tests_run=false remains accurate for the transfer itself.
- Add python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_project_config.py to the post-release acceptance slot. Do not infer this suite passed from the 179-test offline RAG suite.
- Current-hash 100k and live reranker acceptance remain unverified and post-release deferred. Preserve the exact commands in the manifest.
- Current T20 release evidence is not green: 10 focused tests passed, while the direct MemoryStore.find selector fails and the broader test_agent_context.py run has 2 setup errors and 1 failure. T02 has no T11 slot assignment.
- Overall T11 acceptance stays OPEN.

## Slot G — T21 project_config selector UNKNOWN — 2026-10-02

- T20 assigned exclusive slot T20-SERIAL-20261002-G for the exact selector: python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_project_config.py.
- The one local_ai_command invocation stayed in progress for more than four minutes and returned no request ID, terminal/retryable fields, exit code, summary, or test log. The outer wait was terminated; whether pytest stopped is NOT confirmed.
- Outcome is UNKNOWN, not PASS or FAIL. No retry and no native fallback. The later read-only process query found no matching runner; T20 released G as UNKNOWN, never PASS.
- Hash-bound invocation receipt: handoff/t11-slot-g-project-config-unknown-20261002.json, SHA-256 0863B224674469780E77FB1F07CB663E62598CC09DF80CF4F781E16E19F085FB.

## T21 checkout transfer authorization — 2026-10-02

- User approved using existing checkout `C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub` to transfer `project_config` into T11 f678. No new worktree created.
- Source and destination hashes match: `src/local_ai_hub/project_config.py` SHA-256 `FFD425B1260B285F25B1D121A7C6BCD585C618B5C7E26415E2AD0A7014196B0B`; `tests/test_project_config.py` SHA-256 `0196D8FA417DD2B56BFC0D143217D25E2986E1B1B1DF6CEFFADD3C0EEB9FBCEA`.
- T21-owned files remain modified in the source checkout; this step only read and hash-checked them. No tests run; slot G is released as UNKNOWN.
- Overall T11 acceptance stays OPEN; current-hash performance and live reranker remain post-release.

## T20 slot-ledger update — 2026-10-02

- T20 release-acceptance thread `01a0d322-b3bd-7930-b552-14e9b7020fec` records G released as UNKNOWN, never PASS. No retry authorized.
- Current queue: I=T07, J=T05, K=T14. T11 project_config has no new slot assignment; wait for explicit T20 GO before another acceptance run.

## Bounded path-policy review — 2026-10-02

- Read-only review covered `path_is_allowed`, pinned-context/entry-point resolution, `may_descend`, and safe glob matching in the hash-pinned T21 source.
- P2 candidate: `.local-ai.toml` and `.local-ai.worktree.toml` exclusions compare raw basenames with lowercase constants. On Windows, case variants may address the same case-insensitive file but miss the exact checks at lines 1035, 1045, 1190, and 1200. Bounded test-name search found lowercase fixtures only; runtime behavior remains unverified.
- T21 owns the transferred source/test; no edits made. Owner should normalize basename comparison and add Windows coverage for both `path_is_allowed` and `may_descend`.
- Receipt: `handoff/t11-path-policy-static-review-20261002.json`, SHA-256 `E635765CF8920C5C9093651FAA3C264C52F9E8651913146786B2F0FDE7DF8494`. T11 acceptance stays OPEN.
- Candidate owner patch: `handoff/t11-t21-casefold-proposed.patch`, SHA-256 `C39142863C86CFB39CB641F3D33E101E9D706E10BCFA005DFBEED3A6A9FAA6EE`. It changes only T21-owned source/test in the patch artifact; it is not applied or apply-checked. Proposed selector: `tests/test_project_config.py::test_shared_path_policy_excludes_case_variant_local_config_names`.

## Benchmark harness readiness review — 2026-10-02

- Retrieval harness statically confirms a 3-corpus × 4-batch matrix, 20 timed 100k samples after two warmups, latency before a separate memory sample, p95 <= 750 ms per 100k batch, and bounded-scoring/memory assertions.
- Live reranker probe uses two warmups and 20 unique-query measurements over 16 candidates; it reports model/backend/device and p50/p95. Plan specifies no latency threshold; memory is explicitly unmeasured.
- Future 100k command now sets `RAG_BENCHMARK_RECEIPT` to `handoff/t11-rag-benchmark-receipt-20261002.json` so structured metrics survive pytest temp cleanup. Command prepared only; not run without T20 assignment.
- Receipt: `handoff/t11-benchmark-harness-static-review-20261002.json`, SHA-256 `045519DBAB52E8BA2FB8BFCB217BC76540AF6A0149E46C67DE4976F0869156CC`.

## Master-plan acceptance refresh — 2026-10-02

Source: `docs/superpowers/plans/2026-09-22-hub-quality-performance-master-plan.md:252-263`.

- **T11-1 vector performance:** OPEN. Current-hash 100k latency/peak-memory matrix remains unrun; explicit performance slot required.
- **T11-2 atomic publish/cancel:** prior slot11 offline receipt was 179 passed/3 skipped, but its RAG source pin predates the latest lock retry change. Current-hash broad publish/cancel refresh pending.
- **T11-3 embedding identity:** prior offline suite passed; broad current-hash refresh pending because `rag.py` and `test_rag_hybrid.py` changed after its pins.
- **T11-4 backend truthfulness:** prior offline contracts passed; current hybrid refresh and live reranker backend/latency acceptance remain open.
- **T11-5 ingestion contracts:** prior offline receipt passed explicit ingestion/docset/raster checks; current RAG source refresh pending. Live Ollama was skipped.
- **T11-6 relevance/retry/publish edges:** project-policy identity retry selector passed 1 test in 0.62s at prior RAG/hash pins. New uncertain-only retry selector is unrun; prior golden relevance, dedup, disk-full, concurrent-publish and no-duplicate-embedding suite is not latest-hash proof.
- **Overall T11:** OPEN. T07 replay-safety evidence, benchmark results, broad current-hash offline refresh and live reranker budget remain missing.
- Since slot11 offline receipt, only two prevalidation pins drifted among its 19 planned files: `src/local_ai_hub/rag.py` (`f47259…4992` to `8BF256…59C8`) and `tests/test_rag_hybrid.py` (`03d527…23e1` to `90AD65…A0CF`). Exact current values and crosswalk are in the integration manifest.
- T20 currently active on T14 handoff; no T11 GO observed. Exact 12-file offline refresh command and changed pins requested from T20 and recorded in the integration manifest; no tests run pending GO.

## RAG SQLite lock incident — 2026-10-02

- Reported preprocess request `req_37b89f459e7a`: HTTP 500 `database is locked`, `retryable=true`, `terminal=false`; browser showed Vector RAG at 405/702 files. No retry, DB read, or reset.
- Source review found `_sync_workspace_project_policy_identity` writes via `BEGIN IMMEDIATE` and commit without `retry_busy`, on the incremental RAG indexing path. Other RAG publication writes already use bounded `retry_busy`; this identity transaction was the uncovered lock boundary. Exact request-to-function stack attribution remains unavailable.
- T11-owned fix wraps the whole identity write transaction in five bounded busy retries, each with a fresh connection. Targeted regression added; no test run.
- Exact selector: `tests/test_rag_hybrid.py::test_project_policy_identity_retries_transient_publish_lock`.
- Source SHA-256 `8BF2567DAF4F3D71DF9B4B135A82E54D78CA203CC25A9E069304D314B49959C8`; test SHA-256 `E5E9FA85A6E5DA5365FB8E91B86E0478BD54827FE225000578CD2B6CDB49CFCF`.
- Receipt: `handoff/t11-rag-sqlite-lock-fix-20261002.json`. Exact test command required explicit T20 serial GO.
- T20 then granted one-selector GO. Fresh preflight matched HEAD and both pins; matching runner count was zero. Broker `git diff --check -- src/local_ai_hub/rag.py tests/test_rag_hybrid.py` returned `Transport closed`; no structured receipt. Test command was not sent; a follow-up process query still found zero matching runners. No retry or native fallback; T20 ledger needs to resolve the held slot.
- Second T20 GO submitted the exact selector once through `local_ai_command`; broker returned `Transport closed` without request ID, exit code, or log. Outcome UNKNOWN. Post-attempt HEAD and hashes still matched; matching runner count was zero. No retry/native fallback; T20 was asked to close the slot as UNKNOWN.
- Parent later authorized one bounded native offline selector while explicitly disabling Local AI Hub. First run failed only in the new test assertion (`TypeError`: default SQLite row was a tuple); fixed test to use `row[0]`. Second run: `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_rag_hybrid.py::test_project_policy_identity_retries_transient_publish_lock` — **1 passed in 0.62s, exit 0** at then-current source SHA `8BF2567D…4959C8` and test SHA `90AD6594…D0ACA0CF`. Follow-up RAG/test edits changed both hashes; this PASS is historical for the previous version. Earlier broker attempt remains UNKNOWN.

## Uncertain-only ingestion lock follow-up — 2026-10-02

- Static call-flow review found `index_paths_step` republished `read_uncertain_paths` through a raw `BEGIN IMMEDIATE` after `_publish_workspace_read_uncertainty` had already published the same state via bounded retry. The follow-up preserves reassertion semantics but reuses the retry helper.
- Added selector `tests/test_rag_hybrid.py::test_index_paths_step_retries_uncertain_only_publish_lock`. It injects a lock on the third transaction begin, then expects the fourth fresh attempt to persist uncertainty. Test not run.
- Current source SHA-256 `C70C385CE679D9B4A84037BBCD6C352598FE265F95617311228D75096EECEA8A`; test SHA-256 `DEC8B30CE2A5DE797B2B552E1F6B00A62A99B7FFADEE89DFCE6314322EF90314`.
- New selector included in requested 12-file offline refresh; T20 serial GO not received. No test run for this follow-up.


## T20 serial GO #14 — current-hash offline acceptance — 2026-10-02

- Exact command: `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_rag_read_bounds.py tests/test_rag_fragment_cache.py tests/test_rag_hybrid.py tests/test_rag_quality_contract.py tests/test_rag_dedup.py tests/test_t11_project_policy_consumers.py tests/test_t11_rag_ingestion_contract.py tests/test_t11_rag_seed_integrity.py tests/test_reranker_cache_identity.py tests/test_embedding_cache.py tests/test_embedding_batch_deduplication.py tests/test_model_release_lifecycle.py`.
- Ran once through `local_ai_command`; request `req_bb59b6696466`, execution `75ce538a3a584f4fa00efe17066b712d`. Exit 0, 181 passed, 3 skipped, 0 failed, duration 48.8884 s.
- Candidate HEAD stayed `3c7da92aa6a267c2a18af0555d927f0e67d4c476`. All 19 source/test/receipt input SHA-256 pins matched before and after. No pytest process remained.
- Skips: 100k retrieval benchmark (`RAG_BENCHMARK=1`), live Ollama/reranker (`T11_REAL_OLLAMA=1`), synthetic seed benchmark (`T11_RAG_BENCHMARK=1`). All remain UNVERIFIED.
- T11-2 through T11-6 offline evidence refreshed at current hashes. T11-1 performance, live reranker, T21 project-config UNKNOWN, T07 replay, and root hunk integration remain open.
- Candidate patch fails root `git apply --check` because all 11 T11 paths already contain root dirty/untracked state. No patch applied. See `handoff/t11-root-hunk-reconciliation-20261002.json`; preserve both worktrees.


## T20 queue check — 2026-10-03

- T20 has not granted a separate T11 100k benchmark slot or live-reranker slot. T20 reports release remains NO-GO. The prepared commands remain unrun.
- GO #14 remains limited to the 12-file offline batch: 181 passed, 3 skipped. The project-config contract test was outside that command. Prior G result remains UNKNOWN and is not retried.
- Root integration remains blocked by dirty hunks on all 11 T11 paths. No root edit or patch apply. See `handoff/t11-root-hunk-reconciliation-20261002.json`.


## Root ownership recheck — 2026-10-03

- Root HEAD advanced to `276ecabdec84e5a76dfb155090c5f0641fa8a9f2`. All 11 T11-scoped root file hashes and statuses match the prior review.
- Fresh read-only `git apply --check` still exits 1; no patch applied. Root hunk report records exact stderr and current hashes. `tests/test_t11_rag_seed_integrity.py` did not report an apply-check conflict in this run; no inference of full clean integration.


## T21 owner-pin correction — 2026-10-03

- T21 thread metadata showed stale cwd `C:\Users\Adam\.codex\worktrees\4294\.local-ai-hub`; its latest actual command cwd is `C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub`, HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`.
- T21 owns dirty `src/local_ai_hub/project_config.py` SHA-256 `FFD425B1260B285F25B1D121A7C6BCD585C618B5C7E26415E2AD0A7014196B0B` and `tests/test_project_config.py` SHA-256 `0196D8FA417DD2B56BFC0D143217D25E2986E1B1B1DF6CEFFADD3C0EEB9FBCEA`. Both match T11 candidate. T21 scoped `git diff --check` exited 0; no T21 test ran.
- T20 remains NO-GO. Previous `test_project_config.py` slot G remains UNKNOWN; no retry. T11 benchmark/live slots remain unassigned.
- T20 message handoff failed because its thread has no active turn; no retry. Manifest records this owner check.


## Project-config slot G resolution status — 2026-10-03

- Exact selector: `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_project_config.py`. Recorded outcome is UNKNOWN; T20 slot `T20-SERIAL-20261002-G` remains held because dispatch process stop was not confirmed. Receipt `handoff/t11-slot-g-project-config-unknown-20261002.json`, SHA-256 `0863B224674469780E77FB1F07CB663E62598CC09DF80CF4F781E16E19F085FB`.
- Current process snapshot found zero `python.exe`/`pythonw.exe` command lines matching the selector on 2026-10-03. This does not prove the historical dispatch completed or release slot G. No retry/native fallback.
- Separate 100k benchmark requires T20 GO and `RAG_BENCHMARK=1`; live reranker requires distinct T20 GO and `T11_REAL_OLLAMA=1`, `T11_REAL_RERANKER=1`. Neither ran.

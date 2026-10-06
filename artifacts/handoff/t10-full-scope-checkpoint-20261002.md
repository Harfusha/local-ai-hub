# T10 full-scope checkpoint — 2026-10-02

## Current state

Existing T10 goal was already `blocked` when resumed. Goal state is unchanged; acceptance is not complete. HUB was not called. `/api/context/pack` was not edited.

Candidate worktree: `C:\Users\Adam\.codex\worktrees\t10-path-hints\.local-ai-hub`, HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`, 18 dirty entries at latest check (includes handoff artifacts). Existing T10/T21 changes preserved. Candidate defaults files are byte-identical (SHA-256 `418B62992343D074C33BB6DF7D2E8139F2B0DDCD6B47CDB1A4E94971A502D57B`). Root is at T20 commit `01df56605ccf484ebfe2808ac60d696c4e81dffc`; T10 did not edit root. Root dirty `retrieval.py` and other owner paths were preserved. Full path inventory and hashes are in the JSON checkpoint.

## Verified acceptance evidence

- Request/config path hints cannot restore `secret/**`, `hard_denied`, or outside-root results: focused candidate command passed **20/20 in 1.42s**.
- T20-integrated AST/retrieval fixture slice: candidate **26/26 in 3.28s**; T20 reported root **26/26 in 6.57s**. Latest broader candidate AST/retrieval selection passed **48/48 in 4.19s**; [receipt](t10-ast-retrieval-acceptance-20261002.md).
- Candidate/root path-hint test SHA-256 values are recorded in JSON; root copy remains untracked.

## Blocking acceptance

T02 owns 100k benchmark. T02 completed diagnostic review: outputs `-02` and `-03` each contain 128 files, with no paired receipt or valid case results; `-03` overlapped pytest and timing is contaminated. T10 did not run benchmark. Full acceptance needs a clean owner-authorized pair, exact candidate/baseline pins, source hashes and coverage, latency p95, and separately measured memory.

Root/candidate deny-exclude test bodies match (AST segment SHA-256 `FF23E80AF25D33A54583B7BBB581CBF44BE9E744689F03234BA1492C2C65B4CE`). Root copy adds one default-scope fixture. Candidate targeted test passed `1 passed, 3 deselected in 0.37s`. No root-current patch is needed: root already contains required fixture and the additional positive case. Root file remains untracked; its current SHA differs from the candidate copy and the candidate 20-pass receipt does not validate root bytes. T20 must review the exact root copy. Do not overwrite it with stale candidate. Existing root dirty state and T21-owned source were preserved. AST/retrieval selection now passes 48/48; full T10 still waits on T02/T19-owned gates.


## Search budget design

Accepted design keeps `python_fallback_max_files` and `python_fallback_files_scanned` separate from `ripgrep_timeout_seconds`. Candidate defaults files match byte-for-byte. `tests/test_t10_python_fallback_budget.py` asserts fallback scan cap and independent ripgrep timeout setting.


## Latest T10-only validation

In candidate worktree only, checked for active pytest first (zero found), then ran `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t10_repo_search_path_hints.py::test_repo_search_hints_cannot_restore_excluded_or_outside_results`: **1 passed in 0.38s**. It rejects excluded `secret/**`, hard-denied results and outside-root paths despite path hints. Candidate dirty count remains `17`; root HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc` was not changed.

Latest T02 receipt: completed diagnostic review; `-02` and `-03` each contain 128 files, no valid paired/case receipt, and `-03` timing is contaminated. T10 did not run the T02-owned benchmark. Full acceptance remains open for a clean paired 100k receipt, exact pins, source hash/coverage, p95, and separate memory measurement.


## T10 AST/callgraph candidate acceptance

T10 candidate acceptance command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t10_ast_impact_acceptance.py tests/test_t10_fallback_callgraph_parity.py tests/test_t10_python_fallback_budget.py tests/test_t10_repo_search_path_hints.py tests/test_t10_retrieval_fixture_matrix.py tests/test_adaptive_retrieval.py tests/test_repo_topology.py tests/test_affected_tests.py tests/test_cross_repo_federation.py` — **48 passed in 4.19s**. No root tests or merge ran. Exact test/source hashes are in [receipt](t10-ast-retrieval-acceptance-20261002.json).

CodeGraph dependency removal remains intact: candidate packaging metadata declares no CodeGraph dependency; optional source hooks were left unchanged. T19 reports standalone CodeGraph runtime and clean-host release checks still open.

Performance remains T02-owned. Latest T02 thread snapshot showed active runner recovery after one invocation exited 1; no successful paired receipt was available. T10 ran no benchmark. Next action remains owner-issued validated command and paired 100k receipt with separate p95 and memory evidence. CodeGraph standalone checks remain T19-owned/open.


## Current owner receipts — 2026-10-02

User confirmed the split search budget: Python fallback has its own `python_fallback_max_files` cap and `python_fallback_files_scanned` metric; ripgrep uses `ripgrep_timeout_seconds`. Existing candidate code and its focused test already prove this, so no source edit was needed.

The schema guard focused selector passed **2/2 in 0.37s** in the candidate worktree after explicitly verifying the candidate import root. T20 reports the corresponding root schema selectors passed **2/2**. T10 made no root changes. The root release selector remains open after a failure in T16 `leases.py` concurrent table migration; T16's isolated candidate selector passed 2/2, but T20 has not integrated that fix.

Latest T02 snapshot: its one paired run is still active. Root pytest overlapped the first ~39 seconds, so T02 will keep output `-03`, label timing contaminated, and will not rerun or overwrite it. No clean performance receipt exists. T19 reports 70 passed/1 skipped, prompt/CodeGraph 7 passed, docs static exit 0, package smoke 2 passed; clean-host install/release and integrated T20 gate remain open. T10 acceptance is therefore still incomplete.


## Final T10 handoff snapshot — 2026-10-02

Candidate source review is complete. `git diff --check` passed; AST parsing passed for 9 T10-owned Python source/test files; both defaults TOML files parse and are byte-identical at SHA-256 `418B62992343D074C33BB6DF7D2E8139F2B0DDCD6B47CDB1A4E94971A502D57B`. No source edit was made in this review. Candidate and root source hashes intentionally differ for `code_index.py`, `repo_tools.py`, `preprocess.py`, and T10 test files; exact pairs are in the JSON manifest. Root schema source/test hashes are `73BE2A44…361BC00B` and `718FC258…F3C1CC52`. T10 did not edit root.

Historical candidate receipts: path-hint suite **20 passed in 1.42s**; AST/retrieval selection **48 passed in 4.19s** against pre-schema source hash `BE2EA33A…0755101`; schema rebuild guard **2 passed in 0.37s** against the later schema-guard source. After T12 releases the active test slot, the exact six-module T10-only follow-up command is recorded in the JSON manifest. Root T20 earlier reported schema selectors **2/2** and AST/retrieval fixture slice **26/26**. Receipts are candidate/root-specific; hash differences mean one does not substitute for the other.

T02 completed only diagnostic review: outputs `-02` and `-03` each contain 128 files, no valid paired receipt or case results; `-03` timing is contaminated. No clean 100k quality/performance evidence exists. T12 still owns the active selector slot; T10 ran no test during it. T19 clean-host install/release and the integrated T20 release gate remain open. Overall T10 acceptance is not verified.


## T10 current-source follow-up — 2026-10-02

After T12 released the serial test slot and an active pytest-process check returned zero, T10 ran the six T10-owned candidate modules with `PYTHONPATH` pinned to the candidate `src` and asserted the imported package path: **30 passed in 4.81s**, exit 0. Exact command, six test hashes, and current source hashes are in the JSON handoff. This is the current-source T10 test receipt after the CodeIndex schema guard; the older 48-pass receipt remains pre-guard/historical. Root was not tested or modified by this run.

Overall acceptance remains open: T02 has no valid paired 100k receipt (both diagnostic outputs were 128 files; `-03` timing contaminated), T19 clean-host install/release remains open, and T20 integrated release gate has not yet reported final acceptance.


Root-current acceptance handoff for T20: [report](t10-root-acceptance-handoff-20261002.md), [hash manifest](t10-root-acceptance-handoff-20261002.json), JSON SHA-256 `FB8E338D8A041C248CCE5C59605CA6588B46F48CFBADB328572D1584E6C3A3F4`. No test ran in this handoff.


## Current end-to-end gate — 2026-10-02

Goal remains at its pre-existing blocked status; no completion/status claim was made. T02 currently holds the sole test/benchmark slot with its first baseline matrix running (~5 min; 3600s timeout). T10 launched no tests. Next: wait for T02's explicit release, rehash the 16 root paths in [the root acceptance manifest](t10-root-acceptance-handoff-20261002.json), then let T20 run the exact root selector exclusively. T02 paired benchmark and T19 clean-host/release remain open.


Root AST recheck: 14 pinned Python source/test files parsed; defaults TOML parsed and byte-identical. Root handoff preimages at recheck: 0 drift across 16 pinned paths. T02 still owns the sole slot; no T10 tests ran.


Root contract review confirms schema guard, freshness reindex, separate Python fallback cap/metric, and preprocess snapshot invalidation. No source patch indicated. T02 slot remains exclusive.


T02 update: baseline matrix remains active after ~19 minutes with CPU growth and no phase change; one-hour timeout still active. T10 did not run tests.


## Impact/performance handoff — 2026-10-02

Read-only root delta review and exact acceptance recipe: [report](t10-impact-performance-review-20261002.md), [hash manifest](t10-impact-performance-review-20261002.json), SHA-256 `529498EAF140365AAC897A60515661E7380271B0A490AFDD51139161AE7CDB20`. Root HEAD and all listed T10 source/test hashes rechecked with 0 mismatches. Root `git diff --check` passed. T10/T21 ownership boundaries recorded; no source patch, test, or benchmark. T02 says slot `-05` transferred to T11; T20 has not granted T10 a slot. Acceptance remains open.


T02 follow-up: -04 matrix incomplete, -05 proposal awaiting T20 approval. T11 requests slot 11; T20 idle does not grant T10 a slot. T10 asked T02 to coordinate impact latency stage and awaits answer. No tests/benchmarks ran.


T20 queue update: T11 11, T05 12, T03 13, T08 at/after 14, then T10 pending prioritization. T02 owns planned impact latency stage; T10 will not modify its harness. No tests/benchmark run.


Current queue update: T11 slot 11 awaits broker/fresh pins; T05 next pending; T03 slot 13; T08 slot 14+; T10 after queue/prioritization. Root hashes remain stable. Candidate receipt 30/30 remains candidate-only. No T10 test/benchmark ran.


Latest slot note: T11 reports an off-route native pass and incomplete/UNKNOWN stopped suite. T20 requested receipt and immediate release; T10 slot remains unassigned. No T10 tests or benchmarks ran.


T10 candidate source diff/static review artifact: [report](t10-source-acceptance-diff-20261002.md), [patch](t10-source-acceptance-diff-20261002.patch), [manifest](t10-source-acceptance-diff-20261002.json). Patch SHA-256 `61BF1FEF1B820B0296638F3B65A48890661348B7A39CA06C330E4C6FC6874922`. T20 tentative slot18 only; no explicit grant, no test/benchmark.


Latest source-patch recheck: regenerated candidate diff is byte-identical to saved patch; `/api/context/pack` and `context_pack_paths` absent. No root write, test, or benchmark.

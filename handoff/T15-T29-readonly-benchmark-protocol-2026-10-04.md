# T15/T29 paired benchmark protocol and candidate contract tests

**Prepared:** 2026-10-04  
**Scope:** read-only preparation. No source edit, test run, or benchmark run.

## Gate and ownership

- T06 owns the full `commands.py::run` method and all rollback/write-set safety.
- T15 owns only paired benchmark harness and acceptance reporting, after T06 provides a clean pinned candidate.
- T20 owns sequencing. Run nothing until T20 grants one serial slot with an explicit GO and slot ID.
- Current coordination state (2026-10-04): T06 released its unusable checkout/source ownership to the orchestrator; no clean candidate or lease receipt exists. T20 has not granted a T15 slot. No benchmark or root tests authorized.
- Keep rollback preflight, snapshot, restore, patch verification, timeout/cancel process cleanup, and their tests outside T15 edits.

## Last verified source baseline

Repository: `C:\Users\Adam\.codex\worktrees\fefe\.local-ai-hub`  
HEAD: `17d9f93f9d5eded85eee3a19dc7cb62dc554fd97`  
Repository fingerprint: `6f17102301948e6b28293716b3331757c307426fa894af00adecbf213416900a`

`src/local_ai_hub/commands.py` is dirty and cannot serve as a clean candidate:

- HEAD Git blob: `a9e927362f21fd3b381c30d771dd0059a124937f`
- Worktree Git blob: `5fc5c1144574b74523816c4bba76ec8b751907b2`
- HEAD SHA-256: `58506607592a614026011df47d7a3c553552c52c6a1927c7304ff32f1f9b18d1`
- Worktree SHA-256: `ed97e7220030b4fc181bca02e5281d677e683d6038c5ce6748101a3e37ccea17`
- Diff: 3 insertions, 4 deletions in `_snapshot_patch_targets`; T06 rollback scope.

Other pre-existing dirty paths at last check: `handoff/T15-T29-command-run-paired-benchmark.py`, `handoff/T15-T29-commands-run-paired-methodology-2026-10-03.md`, and `handoff/t15-patch-snapshot-stat-20261003.patch`. Recheck status and all pins immediately before any future run.

## Exact root-current pin preconditions for T29

Last `repo_state` check of the T15 root reported HEAD `17d9f93f9d5eded85eee3a19dc7cb62dc554fd97`, fingerprint `fd9f1818ddb5a272679c4f53177a6ea99a5e7bd138e262dd2a7e8f206e7f05dc`, and five dirty paths total listed above, including `commands.py`. This is a dirty worktree snapshot, not a usable benchmark root.

Before T20 may pin a pair:

1. **Baseline:** create/identify a clean root-current checkout at the exact full baseline commit. Confirm `git status --porcelain` is empty for the whole checkout; record `git rev-parse HEAD`, `git rev-parse HEAD:src/local_ai_hub/commands.py`, and SHA-256 for `commands.py` plus every measured test file. Do not use the dirty T15 worktree as baseline.
2. **Candidate:** T06 supplies its authorized clean checkout and handoff. Record its exact full HEAD, declared base commit, `commands.py` blob and SHA-256, and SHA-256 of every candidate test file. No unstated inherited hunks, dirty measured paths, or untracked generated files. T06 classifies all inherited/owned `commands.py` hunks and owns the whole `commands.py::run` surface.
3. **Pair integrity:** baseline and candidate must use the same harness/methodology revision and runtime/config. Record both source/test hash manifests. Report output path must be outside both roots. T20 must bind the exact pair and grant one serial slot ID/GO after T06 handoff.
4. **Stop conditions:** any HEAD, source hash, test hash, relevant config, or dirty status mismatch invalidates the pin; resolve and re-pin rather than benchmark. No T15 source edits or duplicate rollback/concurrency tests.

## Paired run design

Use clean, immutable baseline and candidate roots. Record full commit IDs, `commands.py` SHA-256 values, runtime/host details, and T20 slot ID. Run pairs sequentially, with balanced shuffled AB/BA order and seed `7341`.

| Workload | Modes | Pairs per block |
|---|---|---:|
| `noop` | forced, cache_hit | 60 |
| `read4096` | forced, cache_hit | 60 |
| `write4096` | forced | 30 |

Three blocks yield 450 baseline/candidate pairs, 900 observations total. Measure `total_ms`, `planning_ms`, `execution_ms`, and `result_recovery_ms`. Report p50/p95 and 10,000 paired bootstrap draws using seed `7341`. Preserve the runner's existing correctness checks for output, cache, and scratch state; do not invent or loosen acceptance thresholds.

Phase definitions: planning is `run()` entry through `_execute` entry; execution wraps `_execute`; result recovery is `_execute` return through successful `run()` return. Cache hits bypass `_execute`; include lookup time in planning.

## Candidate contract-test matrix

These are proposals only; no test files changed.

1. **Forced result parity:** compare stdout, stderr, exit code, and public result shape between pinned baseline and candidate for `noop` and `read4096`.
2. **Cache-hit contract:** prove hit returns equivalent result without `_execute`; verify expected cache state and no extra subprocess execution.
3. **Write workload parity:** compare `write4096` bytes and scratch cleanup under forced mode. Do not add a write cache-hit case.
4. **Selector isolation:** verify forced/cache-hit selection maps to intended cases and each case reports its own result; reject missing or mismatched pins before launch.
5. **Concurrency contract:** retain existing single-flight and independent-key expectations; execute only in T20's serial slot.
6. **Safety boundary:** T06 alone owns rollback, snapshot/restore, patch preflight, timeout/cancel cleanup, and fault-injection tests. T15 candidate tests must not rewrite those contracts.

Attach fresh receipts to the exact candidate commit and SHA-256. A successful harness exit without parity evidence is not acceptance.

## Exact future command

Run only after clean pins, T06 handoff, and T20 GO with a granted slot ID. Report path must be outside both source roots.

```text
python -B handoff/T15-T29-command-run-paired-benchmark.py --baseline-root <clean-baseline-root> --candidate-root <clean-candidate-root> --baseline-commit <full-sha> --candidate-commit <full-sha> --baseline-commands-sha256 <sha256> --candidate-commands-sha256 <sha256> --t20-slot-id <granted-slot-id> --report <fresh-path-outside-both-roots.json> --seed 7341
```

**Current measurements:** none. Benchmark and root tests remain stopped pending gates above.

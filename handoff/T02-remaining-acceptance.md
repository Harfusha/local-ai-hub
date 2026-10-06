# T02 Remaining Acceptance

## Candidate ownership

- Worktree: C:\Users\Adam\.codex\worktrees\t02-quality-baseline-resume\.local-ai-hub
- Verified before this documentation/harness edit: clean detached HEAD ad974c54e150d5f2c9bdada8179bc02457147549.
- Candidate source ancestry includes async fix f8024d8ebb51c9bca68e9d8fdaf68c2491b0b1f9 over root baseline 7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf.
- Other temp worktree for branch task_2d1d72257ea5 is outside this worktree; it was not modified.
- No root checkout writes.

## Accepted evidence already recorded

- Checkpoint resume selector: 1 passed in 0.19s.
- Scratch isolation selector: 1 passed in 19.51s.
- Plan-grade and cold/warm comparison selectors: 2 passed in 0.14s.
- Async recovery/reopen/eviction selectors: each 1 passed.
- Delayed-dispatch cancellation regression: passed once plus 25 serial fresh-basetemp repetitions. Receipt JSON SHA-256: A7E789B2EAFEF82645AEC6797794A8EC652FA893D2E456399D3040B55519BE37.
- Earlier entries are prior candidate receipts. Current authorized isolated harness command: python -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short tests/test_t02_repeat_pytest.py
- Result: exit 0, 3 passed in 0.09s. Selectors: bounded repeat count, external output directory, and fixed allowlisted pytest command.
- This was the only test invocation in this edit. No 25-run replay, broad suite, benchmark, GPU inference, or root test was run.

## Benchmark status

Earlier synthetic run was interrupted after more than ten minutes:

- Command: python tools/benchmark_surfaces.py --state-dir <fresh> --scratch-dir <fresh> --files 100 --rag-chunks 1000 --repetitions 3 --light-repetitions 1000 --paired-repetitions 30 --concurrency 1 4
- Result: exit 1 after Ctrl+C; 4,756/5,000 queue rows (95.12%), all cancelled; 30 evidence rows; no persisted timing samples or stage summary.
- This is incomplete progress, not an accepted performance result.

Open receipts:

1. Complete six-workload by four-concurrency CPU/index-only matrix (24 cells; four concurrency series per workload): (files, RAG chunks) = (100, 10,000), (100, 100,000), (10,000, 10,000), (10,000, 100,000), (100,000, 10,000), (100,000, 100,000).
2. Concurrency 1/4/16/32 with 1,000 light and 30 paired samples per accepted run.
3. Smoke receipt before Phase 2, followed by one owned matrix case per T20 window, max 900 seconds each.
4. Completed matrix aggregation; current benchmark emits matrix_aggregation=not_performed_single_case_record and baseline_readiness=per_case.
5. Paired plan-grade baseline/candidate comparison.
6. Real-input retrieval/quality receipt per docs/T02-real-input-quality-evidence-plan.md. Current packet is synthetic-only; no real-input quality is established.
7. Root-current test receipt.
8. GPU inference and live VRAM receipts; separate explicit T20 scope required.

## Root-current integration packet

Existing candidate artifacts:

- Patch: artifacts/t02-root-current-async.patch
- Patch SHA-256: 9BF1C38E0A0C7E4CD6CCDAA13640525883A0C0859DDA676BA5BF5FE5E50ADA3E
- Receipt: artifacts/t02-root-current-async-receipt.json
- Receipt SHA-256: E633C37C8732E78004FF531375B8BC1F6D9B0BF061361AB4801631569AD64CB0
- Receipt root HEAD: 7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf
- Receipt git_apply_check: pending

This packet preserves candidate hunks only. Apply-check and root-current tests remain pending; no integration is claimed or authorized. Compare receipt preimage hashes with the then-current root before any future application.

## Repeat-runner

tools/repeat_t02_pytest.py allows only the delayed-dispatch cancellation selector, runs serially with fresh basetemp per attempt, writes logs and JSON receipt outside the repository, and caps the run at 50 attempts/900 seconds. Its unit selectors were run only under explicit narrow authorization; no 25-run reproduction was started by this edit.

## Preserved historical candidate snapshot (not current acceptance)

The following pre-merge candidate text is retained for provenance. Its commands, hashes, paths and results describe historical work, not verification of this merged checkout. The current master contract above governs execution.

# T02 Remaining Acceptance Handoff

Date: 2026-10-01 (Europe/Prague)

## Candidate snapshot

- Worktree: `C:\Users\Adam\.codex\worktrees\hub-audit-repairs\.local-ai-hub`
- Branch: `codex/hub-audit-repairs-20260924`
- HEAD: `a7b0868ac964fd14e160001024e6e0ecaaf4e9db`
- `src/local_ai_hub/async_jobs.py`: `6C245F4A52C4D1FD2A0D5AC50DFA6CE3E018B9CD2A400F27241690CC8BC97F0A`
- `tools/benchmark_surfaces.py`: `D00810615257B654B894A0B9ECB4E4C36E9B130031AC3F1C8A37D5D87873B413`
- `tests/test_surface_benchmarks.py`: `5AA53B487B91E42B185853EBA2F06502A43D37A9DD78EE7BC4D5A74DDA122FAC`

## Evidence

- Delayed-dispatch regression selector passed once in T02 candidate: `1 passed in 0.21s`. This run predates the T12 helper addition to `tools/benchmark_surfaces.py`; it is not a same-snapshot receipt for the current candidate. Rerun it with the remaining selectors after T20 releases the shared test slot.
- T12 selector `test_t12_profile_matrix_uses_runner_timing_and_flat_deadline_metrics` passed once in the T02 candidate: `1 passed in 0.27s`, run ID `t12-2e569f949f50442d8222c824edc54051`. The test uses a synthetic `Runner`; reported values (42.5 ms E2E, 4 ms TTFT, 20 tokens/s, 1 ms queue wait, 1024/512/700 B VRAM, 100% quality) are fixture values, not live hardware evidence. Its report had a `scenarios` field but no top-level receipt.
- T12 helper patch `handoff/T12-to-T02-benchmark-surface.patch`, SHA-256 `989A639440E8DD1FEB65F80472ABF909DC9286DE14CC7FB89FFBA16B9FF54B93`, passed `git apply --check` and was applied in this candidate only.
- `git diff --check` and Python AST parsing passed for the candidate benchmark source after that patch.
- An earlier combined T12 pytest invocation was interrupted after it expanded into a broader run; it has no usable result and must not be counted.
- T02 made no root edits. T20 briefly applied the separate delayed-dispatch overlay to root, then reversed it; root `async_jobs.py` returned to SHA `A524078F716D4915F6ABFFB27347C4625FDBB9C34A1373F5F8442D7102AEF935`.

## Acceptance still pending

The contract at `docs/T02-quality-performance-baseline-contract.md` requires one pinned source snapshot and this sequence:

1. `tests/test_surface_benchmarks.py::test_queue_admission_probe_cancels_before_delayed_dispatch_registration_race`
2. `tests/test_t02_repeat_pytest.py`
3. `tests/test_surface_benchmarks.py::test_run_benchmark_is_isolated_and_preserves_existing_scratch_data`
4. `tests/test_surface_benchmarks.py::test_full_matrix_persists_cases_and_compares_each_size_pair`
5. Recover the original combined 25-node command/list and its two failed-node tracebacks, then run that exact list in the original and reverse order once. The saved repeat utility is a separate 25-attempt study over both whole files (90 collected tests); it does not identify or reproduce the original 25-node set.

The earlier slot note and selector status below are historical. The current candidate replay ran after T20 released the shared test slot. No root files were edited by T02.

The live baseline contract also requires the real configured Hub TOML, matching Hub state directory, an opt-in configured Hub, a verified local audio fixture and exact transcript, and two six-case plan-grade matrix records with their emitted paths and SHA-256 values. Those inputs and receipts were not supplied or verified in this task. Do not substitute synthetic T12 metrics, mock outputs, guessed transcripts, or zero-valued telemetry for these gates.

## Post-restart and current replay (2026-10-01)

- Fixed the non-finite-timeout test argv to pass `-inf` as `--timeout-seconds=-inf`. Candidate selector command: `C:\Python313\python.exe -B -m pytest -q -p no:cacheprovider --tb=short -c pyproject.toml 'tests/test_t02_repeat_pytest.py::test_main_rejects_nonfinite_timeout[-inf]'`; result: `1 passed in 0.10s`.
- Candidate test SHA-256: `9CE9AC74AA61B4F9048A9550B9528E08F26BAC4A55D39BDDCAA172F6A080B88B`. Root test text matched after CRLF/LF normalization in the earlier comparison; no root work was done during this replay.
- Prerequisite selector batch: 12 passed in 25.18s; log SHA-256 `51FAFF9117D2DD70B1C0D121B0E2D27BC8DC827509513B53170F84B04F7656E8`.
- Combined replay attempted 25 ordered runs with reverse control. Runs 1–19 passed 90/90 each. Ordered run 20 failed 89/90 after 109.43s at `tests/test_surface_benchmarks.py::test_run_benchmark_retains_busy_scratch_without_cleanup_watcher`; assertion was `result["success"] is True`, with diagnostic `failed_stages=['hub_queue_admission']`. This fails at line 888 before lines 889–908 assert scratch existence, absent cleanup watcher, retention count, and second-run refusal. It does not show that scratch-retention acceptance itself failed.
- Harness spawned ordered run 21, then killed it before output or receipt. Mark run 21 aborted and unscored. Runs 22–25 did not run. The required 25-attempt acceptance gate therefore remains incomplete.
- Controls: isolated benchmark suite 9 passed; isolated surface suite 80 passed/1 failed at the same scratch-retention selector; reverse-order combined control passed 90/90. The queue-cancel regression selector passed in all 20 completed ordered runs and the reverse control.
- Confirmed: current failure is the benchmark success precondition inside the scratch-retention test; only `hub_queue_admission` failed. The assertion stops before scratch-retention behavior is tested. Close trace recorded `shutdown=true`, no worker or delayed-dispatch threads, nine cancelled probe rows, and one `outcome_unknown` row consistent with the fixture sentinel. Eight captured cancel responses were `success=true,state=cancelled`. Unconfirmed: the exact failing sample and its queue error reason; pytest locals elide the stage details. Timing/order interaction remains a hypothesis. Historical delayed-dispatch race does not establish this cause.
- Evidence summary: `C:\Users\Adam\AppData\Local\Temp\t02-25-7117a0910dab4182b039eb030be65540\evidence-summary.json`, SHA-256 `6A5659520243E887A5003ED53017C3EC4C16C241267A4FA19F8A6BEF36268905`. Partial receipt SHA-256 `F0089AD94BB75A5FC8879E81523798E53C06FA467D528CCD5EAD3967C73CB5F4`; environment manifest SHA-256 `4FCC3EEE4C61C077D55192DA7FF75DC0EA88CB83D65095909D9B3C2808A84250`.
- Agent OS receipt attachment is pending. One `task_list` request was not sent (`outcome_unknown=false`, `request_not_sent=true`); bounded health check returned `success=false`. No task ID or successful Agent OS attachment is available. Local fallback receipt is `handoff/T02-agent-os-receipt-2026-10-01.md`.

## Next owner action

Keep all four pinned selectors and their assertions unchanged. T20's root scratch-retention selector passed 1/1 in 15.50s without diagnostic samples. A candidate lifecycle slice passed 11/11 in 15.58s and found no open managers after teardown in that reduced prefix. The original combined 25-node list/command remains unrecovered. A separate saved 90-node order-control receipt failed two CLI JSON-capture tests because a temporary tracer printed `T02_TRACE` to stdout; both affected selectors passed 2/2 with the current stderr-only lifecycle plugin. Do not attribute that instrumentation failure to the original report. Dataset definitions and measured/unavailable phase labels are in `handoff/T02-cross-task-dataset-manifest.json`; paired T10/T11/T15 outputs and real Hub/audio inputs remain incomplete. Live baseline acceptance stays open until the original 25-node case is recovered, the remaining pinned selectors pass on the same snapshot, and required paired records exist.

Repeat utility artifacts:

- `tools/repeat_t02_pytest.py`: `D68A6D761C7A3B80D44B5B8F9BF6B268521D30D04E9D77609C34C0B2B91017CE`
- `tests/test_t02_repeat_pytest.py`: `AC635C38E257C159359B2CA5B5B2F73B3B690CE97B583C0303208F5C948CFF0F`
- `tools/schemas/t02-pytest-repeat-v1.schema.json`: `8CE440C901AEB3049D912EC3463A75AA4A0541E84ECBD73461243D751E26F01D`
## T12 helper boundary review

Read-only inspection of `handoff/T02-T12-benchmark-surface-dependency.patch` (SHA-256 `C0560910A2A62E48B5822B6335588D88AC8174E0A2446FE981B1F8480EDD1A1B`) shows only `_T12_PROFILE_CORPUS`, `_t12_*` helpers, `_t12_scenario_report`, and `_run_t12_matrix` additions. Root apply-check passed when created, but this was a T02-generated projection, not a minimal T12 owner handoff. It does not add or change T02 `run_benchmark` / `run_benchmark_matrix`, and does not cover the three T02 lifecycle/compare selectors above. Keep it as projection evidence only; await T12 owner patch for separate review. No root patch was applied by T02.

## Artifact-backed model-free matrix preflight (2026-10-01)

- Prepared a deterministic root/candidate workload identity and six-case execution plan; no benchmark workload or 100k corpus was generated during preflight.
- Exact preflight command: `C:\Python313\python.exe -B tools\prepare_t02_artifact_matrix.py --root C:\Users\Adam\.local-ai-hub --candidate C:\Users\Adam\.codex\worktrees\hub-audit-repairs\.local-ai-hub`. Result: `status=ready_for_t20_slot`; root HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`; candidate HEAD `a7b0868ac964fd14e160001024e6e0ecaaf4e9db`; shared generator SHA-256 `0BDD678A79C06C96192FC8207B3A6FD385E0CC1FC469BEFFC0BFBF67DDEB0C96`; all six case IDs match the frozen plan.
- Root/candidate `benchmark_surfaces.py` SHA-256 differ as expected: root `363FFAF81BFD2BE8567A4EC6EE76461E05756620EC924D5C48F71A4A6A520C96`, candidate `E93F2BBDA52B62018D8F2AE4C4F148F0CCB7E24C37F3A3C3F1EBEEB0D7412457`. Generator function identity matches across both.
- Root and candidate implementation fingerprints are pinned as `4622979dec2abacdd6e9f372b03643d5d8644a366592e0edf66d8ec25937c882` and `2aff5d58ba7bdf933ea9bbb3f26049f529665e7dc2e64b9193a8b985c32741a7`; preflight records each underlying runtime file SHA-256. Those fingerprints must match the eventual benchmark records.
- Frozen input IDs, source revisions/fingerprints, model-free `embedding_identity=not_applicable`, artifact checks, two-arm `--full-matrix` commands, and expected model-free comparison gate are recorded in `handoff/T02-artifact-matrix-preflight-2026-10-01.json` (SHA-256 `F9A39E237DCB492276009FA3DB0A7A9FAC2226EBB19BEFE9ABD3D639958A9600`) and `handoff/T02-artifact-backed-matrix-runbook-2026-10-01.md` (SHA-256 `A95CFE643363EFC739875B36D7D6FB2CD333C2948D88D8665F14864A0ED7146C`). Preflight tool SHA-256 `274A638193864558FE4D038F9547F7745AFB9F7525CF2AF17DD20CE602D333A9`.
- Runbook PowerShell parses successfully. It reruns all six cases per arm at 1000 light / 30 comparison samples and concurrency `[1,4,16,32]`; two earlier smoke cases cannot be substituted. T20 owns actual execution after slot grant. Model-free output remains non-plan-grade; `compare_matrix_records` will mark comparison inconclusive until model-dependent goldens are supplied.
- Original `2/25` node list/cause remains unresolved. No root integration or source edit performed for this preflight.

## Resumed bounded model-free baseline (2026-10-01)

- Candidate revision remained `a7b0868ac964fd14e160001024e6e0ecaaf4e9db`. No root, GPU, or T20 100k CPU-slot run occurred.
- Added `tools/validate_t02_model_free_receipt.py` to avoid fragile inline quoting and validate manifest structure, external record hashes, per-case readiness, skipped inference, and lifecycle plugin stderr routing. Exact command: `C:\Python313\python.exe -B tools\validate_t02_model_free_receipt.py`. Result: `PASS: manifest=3 cross-task datasets; T02_cases=6; model_free_records=2; lifecycle_plugin=stderr; receipt_sha256=4DAD5A523F7F2084C369DFFB2D25DE5C6B9781752BD3AC49FFB4F0CB1E968553`.
- Lifecycle/CLI stdout regression command: `C:\Python313\python.exe -B -m pytest -q -s --tb=short -p no:cacheprovider -p tools.t02_lifecycle_pytest_plugin -c pyproject.toml tests/test_surface_benchmarks.py::test_cli_persists_and_reports_baseline_comparison tests/test_surface_benchmarks.py::test_cli_worker_enforces_wall_timeout_against_real_hung_child`. Result: `2 passed in 24.48s`; both teardown lines went to stderr and reported `open_managers=[]`.
- Model-free six-case orchestration test: `C:\Python313\python.exe -B -m pytest -q -s --tb=short -p no:cacheprovider -p tools.t02_lifecycle_pytest_plugin -c pyproject.toml tests/test_surface_benchmarks.py::test_full_matrix_persists_cases_and_compares_each_size_pair`. Result: `5 passed in 11.79s`. This parametrized fixture test validates matrix persistence/comparison behavior; it does not measure the six real workload pairs.
- Actual model-free per-case records, both from revision `a7b0868ac964fd14e160001024e6e0ecaaf4e9db`, were emitted outside the repository: `(files=100, chunks=10000)` record SHA-256 `7B05E439D374C0F6654F3BFD67F01E4F85EEADF0C0036D1CCEC525BF98B5F0C3`, 30.595 s, peak RSS 196874240 bytes; `(files=10000, chunks=10000)` record SHA-256 `9B142B7533AE7F31F119A966AC82646A39BFA3727B3DFB7AD939E6F01A319EFB`, 47.438 s, peak RSS 225116160 bytes. Both had exit 0, no failed stages, 3 light/comparison repetitions, concurrency `[1,4]`, `baseline_readiness=per_case`, and `inference=skipped_not_requested`.
- First 100×10000 invocation omitted `--full`, exited 2 with `large sizes require full benchmark opt-in`; it emitted no benchmark record. Corrected invocation used `--full` and a fresh external state/scratch directory. Failed-attempt identity and details are preserved in the receipt.
- Machine receipt: `handoff/T02-model-free-baseline-receipt-2026-10-01.json`, SHA-256 `BFEEE4E979BED91D8BA131346834DC8CB4E12202C25ABDD7E23A2D597E591EF0`. The dataset manifest points to it. Matrix measurement remains partial: 2/6 cases; four 100k-heavy cases are deferred outside the T20 slot. Records are smoke/per-case evidence, not plan-grade acceptance. Synthetic fixture score is not semantic retrieval or model quality.
- `git diff --check` passed on the changed T02 manifest, receipt, handoff, and validation/plugin files. The original historical combined `2/25` cause remains unknown; this work does not resolve it.

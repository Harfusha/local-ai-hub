# hub-audit-repairs committed synchronization — 2026-10-06

Scope: local hub-audit-repairs worktree only.
Branch: codex/sync-hub-audit-repairs-20261006.
Native fallback explicitly authorized after the prior terminal Hub failure; no Hub retry, polling, new worktree/chat, stash, push, root-checkout edit or master-ref write.

## Pinned history and preservation

- Original checkout HEAD: 91b73fc9bd20ae0f6bcf81fff20157cf62d2ce06.
- Original checkpoint: refs/checkpoints/hub-audit-repairs-original-20261006.
- Existing dirty checkpoint branch: codex/checkpoint-hub-audit-repairs-dirty-20261006 at 91b73fc9.
- Remaining ordinary untracked source/tests/docs and historical handoff markdown/patches: committed as 69604c5fed96ca721716c654b548488c8ec13d45 before merging (42 files).
- Complete preservation checkpoint: refs/checkpoints/hub-audit-repairs-preserved-20261006 at 69604c5f.
- Master pinned once after central T10 integration: 80a9cbb6765ed1f2d129bf16a0e7bc6651f8b406, subject "merge(sync): reconcile T10 indexes and preserve benchmark evidence".
- Master pin: refs/checkpoints/hub-audit-repairs-pinned-master-20261006. Later master movement is outside this synchronization.
- Merge uses that exact SHA. The merge commit containing this note is the handoff; obtain it with git rev-parse HEAD rather than embedding a circular commit hash here.
- 312 ordinary untracked historical benchmark scratch files and 45 historical JSON/log/evidence files remain physically preserved, uncommitted. No cleanup. Newly generated .sync-checks test state is uncommitted. No new runtime/cache files were added to the index; inherited tracked snapshots from master were preserved.

## Manual behavioral reconciliation

Nine conflicting paths were reviewed as individual conflict hunks. Independent read-only review covered all 35 benchmark-tool and eight benchmark-test hunks; final edits/integration remained with the main agent.

Async jobs retain master's transaction-protected, non-destructive schema refusal, caller request-id semantics, operational-mode transition lock, resource-release coordination, delayed callback rescheduling, replay eligibility and worker ownership. Historical dispatch-time clearing survives cancel, recovery/expiry and retry reconciliation. Due-time comparison remains inclusive. Historical unkeyed-running test fixture now sets attempts=1, matching an already executed attempt; master's zero-attempt replay rules are unchanged. Trace fixture uses the current request id.

Benchmark reconciliation retains current source precedence and loaded-runtime origin guard, runtime_source_root, imported-dependency implementation fingerprint, T12 opt-in and explicit-runner checks, watchdog/debug-trace suppression, queue failure codes and current T12 tests. Historical deterministic input seed/provenance, bounded queue diagnostics, scratch ownership, cancellation/timeout receipts and rejection of misleading worker success survive. Exactly one T12 helper block remains. Results are compared/persisted after cleanup; cleanup errors invalidate success.

Historical queue tests use current comparison_repetitions and bounded failed_samples/error_types/error_reasons fields. Timeout tests assert the stronger structured receipts including record_complete=False, return code and stream hashes. Secret-exclusion assertions remain.

The current allowlisted repeat runner and its tests remain identical to pinned master. Historical whole-suite runner/test source and schema are recoverable in 69604c5f; the preserved v1 schema is not the schema of the current runner. No deprecated CLI alias was introduced. Historical candidate acceptance text is explicitly labeled historical beneath the current master contract.

All src/local_ai_hub files except async_jobs.py are identical to pinned master, including preprocessing and T14-owned /api/context/pack implementation. defaults.toml and both INSTALL_PROMPT/UPDATE_PROMPT remain identical to pinned master. No CodeGraph integration was restored.

## Actual targeted checks

All pytest commands used python -B, -q, -p no:cacheprovider, --tb=short and distinct --basetemp paths under .sync-checks in the assigned checkout. No full release suite, live model inference, large benchmark or deployment.

- Async: tests/test_async_jobs.py -k 'recovery or recovered or delayed or cancel or schema', --basetemp .sync-checks/async-fixed: 14 passed, 15 deselected.
- Benchmark units: tests/test_surface_benchmarks.py -k 'implementation_fingerprint or t12_ or cli_wall_timeout or cli_worker_enforces or cli_worker_cancellation or cli_rejects_nonfinite', --basetemp .sync-checks/benchmark-final: 10 passed, 82 deselected.
- T10/current guards: tests/test_t10_preprocessor_index_version.py tests/test_t02_acceptance_claims.py tests/test_t02_repeat_pytest.py, --basetemp .sync-checks/t10-final: 9 passed.
- Policy batch: tests/test_t02_repeat_pytest.py tests/test_codegraph_package_policy.py tests/test_t19_codegraph_removal.py, --basetemp .sync-checks/policies: 11 passed, 3 failed. Failures detailed below.
- AST parse of all 14 changed Python files under src/tests/tools: passed; no duplicate top-level function/class names.
- Imported async module and benchmark source root verified inside this assigned checkout's src.
- git diff --check against pinned master for src/tests/tools/docs: exit 0.
- git ls-files -u: zero entries after staging resolution.
- Final pinned-master ancestry and clean tracked state are checked after committing this note.

Earlier attempts are not counted as passes: missing basetemp parent caused 13 setup errors; after creating the parent, the old zero-attempt recovery fixture failed once and was reconciled. Benchmark timeout tests initially failed twice because the reconciliation omitted hashlib import; corrected before the final passing batch. A broad staged diff whitespace check exposed inherited master snapshot/CRLF whitespace; the bounded changed-source check against pinned master passes. Inherited artifacts were not reformatted.

## Outstanding / incomplete behavior

Three policy failures are inherited unchanged from pinned master (generator.py, README and both policy test files verified identical):
1. test_runtime_has_no_managed_codegraph_or_kuzu_references flags generator.py's explanatory standalone CodeGraph text.
2. test_codegraph_is_absent_from_hub_runtime_configuration_and_telemetry also flags that explanatory text.
3. test_optional_codegraph_docs_use_current_gcf_extra_without_hub_integration expects README wording "not Hub dependencies or backends" absent from current text.
These checks are not green; their text-policy mismatch was not redesigned during synchronization.

Queue-label allowlists from master are retained but currently disconnected from diagnostic string fields. Hostile state/reason/exception-class labels are not proven sanitized. This needs a separately scoped safety repair; preservation is not privacy acceptance.

No real full-matrix, paired baseline/candidate, live audio/GPU/VRAM or historical 25-node/order-race acceptance is claimed. Historical receipts and patches are provenance only; unchanged old timestamps/hashes do not validate this merge. Preserved paired-matrix/admission-repro/cleanup tools/tests are committed even though not all were executed and may require follow-up reconciliation.

Real run_benchmark lifecycle/redaction integration selectors were not executed: their runtime state must be outside the repository, while this task permits writes only inside the assigned checkout. Pure/helper and mocked-worker tests above stayed within scope. Gemini configuration/source preservation is verified; live Gemini inference is not.

## Files changed against pinned master

Status/name inventory below excludes this newly added integration note, which is also an added file.

```text
M	docs/T02-quality-performance-baseline-contract.md
M	docs/superpowers/plans/2026-09-22-hub-quality-performance-master-plan.md
A	docs/superpowers/plans/2026-10-02-t02-paired-baseline-runner.md
A	handoff/T02-T12-benchmark-surface-dependency.patch
A	handoff/T02-admission-diagnostic-protocol.md
A	handoff/T02-admission-diagnostic.patch
A	handoff/T02-admission-flake-forensics-2026-10-01-v1.md
A	handoff/T02-agent-os-receipt-2026-10-01.md
A	handoff/T02-artifact-backed-matrix-runbook-2026-10-01.md
A	handoff/T02-cancel-cleanup-reproducer-2026-10-01-v1/handoff.md
A	handoff/T02-combined-flake-cause-2026-10-01-v1.md
A	handoff/T02-combined-flake-cause-2026-10-01-v2.md
A	handoff/T02-combined-suite-flake-evidence.md
A	handoff/T02-current-root-dispatch-claim.patch
A	handoff/T02-delayed-dispatch.patch
A	handoff/T02-dispatch-claim-root-overlay.patch
A	handoff/T02-incomplete-claim-guard-v1.patch
A	handoff/T02-matrix-execution-blocker-2026-10-01-v1.md
A	handoff/T02-nonfinite-timeout-argv.patch
A	handoff/T02-original-2of25-forensics-2026-10-01-v2.md
A	handoff/T02-owned-current-root.patch
A	handoff/T02-release-readiness-2026-10-01-v1.md
M	handoff/T02-remaining-acceptance.md
A	handoff/T02-root-current-acceptance-2026-10-01-v1/handoff.md
A	handoff/T02-root-current-overlay-2026-10-01-v1/handoff.md
A	handoff/T02-root-current-race-20261002-v1/t02-queue-row-diagnostic-root-current.patch
A	handoff/T02-sqlite-warning-diagnostic-2026-10-01-v3/diagnosis.md
A	handoff/T02-sqlite-warning-runner-2026-10-01-v1/diagnosis.md
A	handoff/T02-timeout-attribution-2026-10-01-v1.md
M	src/local_ai_hub/async_jobs.py
M	tests/test_async_jobs.py
M	tests/test_surface_benchmarks.py
A	tests/test_t02_acceptance_claims.py
A	tests/test_t02_admission_race_repro.py
A	tests/test_t02_paired_matrix.py
A	tests/test_t02_repeated_benchmark_cleanup.py
M	tools/benchmark_surfaces.py
A	tools/prepare_t02_artifact_matrix.py
A	tools/run_t02_paired_matrix.py
A	tools/run_t02_sqlite_warning_diagnostic.py
A	tools/schemas/t02-pytest-repeat-v1.schema.json
A	tools/t02_lifecycle_pytest_plugin.py
A	tools/validate_t02_acceptance_claims.py
A	tools/validate_t02_model_free_receipt.py
```

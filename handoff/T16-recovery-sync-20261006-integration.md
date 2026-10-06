# T16 recovery checkout synchronization — 2026-10-06

Committed integration handoff; functional acceptance remains PARTIAL.

Scope: C:/Users/Adam/.codex/worktrees/t16-orchestration-recovery/.local-ai-hub only.
Branch: codex/sync-t16-orchestration-recovery-20261006.
Merge target pinned once: 1fa8c6f1655e58c79bc002f11778ef07a919488f.
No root checkout or master ref writes; no push, stash, reset, clean, new worktree or chat.
T14 /api/context/pack ownership preserved: no endpoint redesign.

## Committed merge receipt

Merge commit: 847afd3f6b0fd74f71dd6a18990c218cdb144c30.
Parents: 49ced58f (all original work preserved), 1fa8c6f1 (pinned master).
git merge-base --is-ancestor refs/checkpoints/t16-recovery-sync-20261006-master HEAD:
exit 0. git ls-files -u: zero entries. git status --porcelain=v1
--untracked-files=all: empty after merge. Integration delta whitespace check passed.
Delta versus pinned master: 84 paths, 29503 insertions / 3 deletions at merge commit.

Concurrent master drift: shared master was 1fa8c6f1 at initial pin, but observed
fcbb1d6fa7347e9b918d030f4f99d058d9846a6c after merge commit. Moving master ancestry
check returned exit 1. No command in this task wrote master. User explicitly
specified pin 1fa8c6f1 once: no retargeting or merge of concurrent changes.
Synchronization is complete against requested pinned target; it is not claimed
against the subsequently advanced shared master. Final handoff commit updates only
this note. Its actual HEAD is reported in the chat; no self-referential commit hash.

## Preservation

- Observed initial HEAD: c6c38c5efe69a1f79cad9ddfbdb86d091f275ae3.
  This existing checkpoint already commits six tracked dirty files, 1456 insertions / 152 deletions.
- Its pre-dirty parent: 824c9eb9, also retained under refs/checkpoints/t16-recovery-sync-20261006-pre-dirty.
- refs/checkpoints/t16-recovery-sync-20261006-original retains initial HEAD c6c38c5e.
- refs/checkpoints/t16-recovery-sync-20261006-master retains pinned target 1fa8c6f1.
- refs/checkpoints/t16-recovery-sync-20261006-preserved retains 49ced58f:
  all 87 ordinary untracked files committed before merge, 32933 inserted lines.
  The previously supplied estimate of 65 untracked files was stale.
- All 76 original handoff / root-manifest / patch files checked against preserved
  Git blob IDs: zero changed originals. Source/tests reconcile with newer master;
  their original bytes remain recoverable from the preserved checkpoint.
- Existing ignored .pytest_cache, .serena and __pycache__ directories preserved.
  Validation scratch, SQLite databases and temporary repositories live under
  ignored .pytest_cache/t16-sync-20261006; none added by this synchronization.

## Manual reconciliation

Reviewed every conflict hunk across six source and six test files before resolving.
No whole-file ours/theirs selection.

- leases.py: retained master durable backup/schema validation imports, namespaced
  wait-table migration and agent_state_schema_versions version checks.
- project_config.py: retained server-derived coordination_id, fail-closed config resolution.
- work_fencing.py: retained master work_id schema handling and concurrent column
  initialization behavior; scope_id and physical-root fencing retained.
- work_orchestrator.py: retained master safe journal target validation, all-target
  rollback preflight, postimage hashes, hardlink/reparse rejection and relocated
  attempt guard. Strict trusted receipts, mutation-generation freshness and
  current command/lease policy retained. Only import layout differs from master.
- http_server.py: retained master's project identity import and lease routes;
  removed an automatically duplicated _lease_coordination_id helper. Final file
  equals pinned master. No /api/context/pack modifications.
- services.py: master policy and fence/receipt forwarding retained; only blank-line layout differs.
- tests: retained master live-old-lease lifecycle scenario and strict symlink
  privilege checks; preserved independent-namespace coverage, real Windows junction
  coverage and the local partial-apply regression. Junction rollback assertion
  reconciled to master's ValueError / reparse contract.
- Structural verification found three silently duplicated test definitions from
  automatic merging. Bodies were AST-identical to master's copies; removed only
  earlier duplicate copies. Original definitions retained in checkpoint history.

preprocess.py, defaults.toml, leases.py, project_config.py and work_fencing.py
remain byte-equivalent to pinned master. CodeGraph runtime implementation was not
reintroduced; historical handoff copies and scan-ignore strings remain historical.

Gemini limitation: pinned master INSTALL_PROMPT.md and UPDATE_PROMPT.md explicitly
state no Gemini preprocessing provider implementation was found. This merge
preserves preprocessing from master exactly; it cannot claim a newly implemented
Gemini provider or runtime availability. No new provider feature was invented.

## Actual validation

Hub native fallback: user explicitly reports prior terminal Hub failure and
authorizes native work without retry/poll. Original Hub evidence IDs and terminal
response were not supplied in this turn; no new Hub evidence claimed.

Token-economizer setup: attempted ensure-tools.ps1 -PlanOnly; script missing in
both installed skill locations. No installation or User PATH changes.
Native sidecar delegation unavailable: agent thread limit reached; review done here.

Python: C:/Python313/python.exe. PYTHONDONTWRITEBYTECODE=1,
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1, source root bound to this checkout and overlay
environment unset for test process. TEMP/TMP constrained to ignored checkout scratch.

Command (executed once, no full release suite):

```text
python -B -m pytest -q --tb=short -p no:cacheprovider --basetemp=<checkout>/.pytest_cache/t16-sync-20261006/pytest-first tests/test_work_fencing.py tests/test_work_handoff_acceptance.py tests/test_work_orchestrator.py tests/test_t16_explicit_write_set_lifecycle.py tests/test_t16_terminal_rollback_preflight.py tests/test_t16_lease_wait_namespace_isolation.py tests/test_t16_project_namespace_leases.py::test_shared_namespace_keeps_physical_root_containment
```

Result: exit 1; 70 passed, 5 failed, 2 skipped in 38.61 seconds.
Suite ran before removing AST-identical duplicate test definitions. Post-removal
AST/duplicate checks passed; no changed test behavior inferred from deduplication.
AST syntax parse: all 12 reconciled files passed.
Post-reconciliation duplicate-definition/syntax check: six test modules passed.
Source AST equivalence to pinned master: all six reconciled source modules passed.
git diff --check 1fa8c6f1 -- src tests: passed.

Index comparison against original pre-merge branch also exposes inherited master
CRLF/trailing-whitespace warnings in unrelated dashboard/tests. No broad formatting
rewrite performed; validation of this integration's delta uses pinned master.

## Outstanding issues and limits

1. test_partial_git_apply_failure_restores_all_preimages_and_clears_journal:
   actual error "rollback refused: postimage changed for first.txt".
   Restoration/journal-clear expectation not satisfied in this Windows fixture.
   Root cause not fully established; postimage safety check was not weakened.
2. test_real_command_broker_accepts_forwarded_work_attempt_fence:
   rejected with "auxiliary action policy engine unavailable". Fixture constructs
   services without current policy engine; standalone broker acceptance unverified.
3. test_local_service_forwards_receipt_opt_out_and_keeps_work_id:
   same uninitialized-policy fixture family; success assertion failed.
   Current policy remained fail-closed.
4. test_legacy_wait_edges_migrate_to_namespace_inclusive_primary_key:
   "legacy lease schema mismatch: leases". Fixture creates only lease_waits;
   master migration requires complete legacy lease schema.
5. test_concurrent_legacy_wait_migrations_do_not_rename_over_new_table:
   first migration never reached table rename within its five-second wait.
   Companion legacy-only fixture is incompatible with current durable migration;
   concurrency acceptance remains unverified.
6. Two symlink tests skipped for Windows WinError 1314. Real junction tests ran.
7. Linked-worktree namespace/recovery and T16 HTTP lease-route fixtures were not
   executed because they create new worktrees, prohibited by this task.
8. Inherited master test_recovery_retries_preimage_restore_after_crash_before_journal_clear
   ends after constructing recovered orchestrator, with no final assertions or close.
   Its green result is not evidence for post-restart recovery completion.
9. Historical receipts, manifests and patches are retained evidence snapshots,
   not fresh runtime acceptance. No live Gemini inference, installed Hub,
   deployment, full release suite or full repository correctness verified.

Merge completion is checkout synchronization plus preservation and committed
handoff, not functional acceptance. The above failures are intentionally committed
as unfinished work under explicit user authorization.

## Changed paths versus pinned master

83 existing result paths before adding this note; 84 including this integration note.
Source behavior equals pinned master; differences are source formatting, additional
test coverage and preserved T16 handoff artifacts.

```text
A	handoff/T16-acceptance-matrix-v1.md
A	handoff/T16-acceptance-restoration-v3.md
A	handoff/T16-cross-process-broker-root-worktree-overlay-v1.md
A	handoff/T16-cross-process-commit-race-v1.md
A	handoff/T16-cross-process-fence-receipt.patch
A	handoff/T16-cross-process-namespace-lease-recovery-v1.md
A	handoff/T16-cross-process-namespace-lease-recovery-v1.patch
A	handoff/T16-cross-process-namespace-lease-recovery-v2.patch
A	handoff/T16-end-to-end-acceptance-checkpoint-20261002.md
A	handoff/T16-exact-owner-handoff-20261002.md
A	handoff/T16-explicit-write-set-lifecycle-root-current-v1.md
A	handoff/T16-explicit-write-set-lifecycle-root-current-v1.patch
A	handoff/T16-explicit-write-set-lifecycle-root-current-v2.md
A	handoff/T16-explicit-write-set-lifecycle-root-current-v2.patch
A	handoff/T16-fencing-r2-core.patch
A	handoff/T16-fencing-r2-services.patch
A	handoff/T16-fencing-r3-core.patch
A	handoff/T16-fencing-r3-services.patch
A	handoff/T16-fencing-r4-core.patch
A	handoff/T16-fencing-r4-services.patch
A	handoff/T16-http-lease-routes-root-current-patch.md
A	handoff/T16-http-lease-routes-root-current-v2.md
A	handoff/T16-http-lease-routes-root-current-v2.patch
A	handoff/T16-http-lease-routes-root-current-v3.md
A	handoff/T16-http-lease-routes-root-current-v3.patch
A	handoff/T16-http-lease-routes-root-current.patch
A	handoff/T16-namespace-root-current-patch.md
A	handoff/T16-namespace-root-current-v2.md
A	handoff/T16-namespace-root-current-v2.patch
A	handoff/T16-namespace-root-current-v3.patch
A	handoff/T16-namespace-root-current-v4.md
A	handoff/T16-namespace-root-current-v4.patch
A	handoff/T16-namespace-root-current-v5.md
A	handoff/T16-namespace-root-current-v5.patch
A	handoff/T16-namespace-root-current.patch
A	handoff/T16-orchestration-broker-handoff-acceptance.py
A	handoff/T16-orchestration-broker-handoff-t06-compat-v2.md
A	handoff/T16-partial-apply-failure-root-current-v1.md
A	handoff/T16-partial-apply-failure-root-current-v1.patch
A	handoff/T16-project-namespace-consumer-proposal.md
A	handoff/T16-r2-root-current-core.patch
A	handoff/T16-r2-root-current-handoff.md
A	handoff/T16-r2-root-current-receipts.patch
A	handoff/T16-r2-root-current-services.patch
A	handoff/T16-recovery-fencing-regression-handoff-20261002.md
A	handoff/T16-recovery-fencing-root-review-v1.md
A	handoff/T16-root-current-crash-test-placement-v1.md
A	handoff/T16-root-current-crash-test-placement-v1.patch
A	handoff/T16-root-current-cross-process-atomic-lease-v1.patch
A	handoff/T16-root-current-cross-process-commit-race-v1.patch
A	handoff/T16-root-current-fencing-receipt-v1.md
A	handoff/T16-root-current-orchestration-manifest-v1.md
A	handoff/T16-root-current-partial-apply-junction-v1.json
A	handoff/T16-root-current-partial-apply-junction-v1.patch
A	handoff/T16-root-current-portable-overlay-v1.md
A	handoff/T16-root-current-portable-overlay-v2.md
A	handoff/T16-root-current-postimage-manifest-v1.md
A	handoff/T16-root-current.patch
A	handoff/T16-root-integration-acceptance-matrix-20261002.md
A	handoff/T16-root-recovery-candidate-diagnostic-v1.md
A	handoff/T16-root-recovery-candidate-diagnostic-v2.md
A	handoff/T16-root-scope-cross-process-root-current-v1.md
A	handoff/T16-root-scope-cross-process-root-current-v1.patch
A	handoff/T16-services-fence-forwarding.patch
A	handoff/T16-windows-junction-acceptance-root-current-v1.md
A	handoff/T16-windows-junction-acceptance-root-current-v1.patch
A	handoff/root-current-overlay/leases.py
A	handoff/root-current-overlay/src/local_ai_hub/work_fencing.py
A	handoff/root-current-overlay/test_t16_project_namespace_leases.py
A	handoff/root-current-overlay/test_work_handoff_acceptance.py
A	handoff/root-current-overlay/tests/test_t16_project_namespace_leases.py
A	handoff/root-current-overlay/tests/test_work_handoff_acceptance.py
A	handoff/root-current-overlay/work_fencing.py
A	handoff/root-current-overlay/work_orchestrator.py
M	src/local_ai_hub/services.py
M	src/local_ai_hub/work_orchestrator.py
A	t16_root_handoff_20261002.manifest.json
A	t16_root_handoff_20261002.patch
M	tests/test_t16_explicit_write_set_lifecycle.py
M	tests/test_t16_terminal_rollback_preflight.py
M	tests/test_work_fencing.py
M	tests/test_work_handoff_acceptance.py
M	tests/test_work_orchestrator.py
A	handoff/T16-recovery-sync-20261006-integration.md
```

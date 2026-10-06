# T08 completion validation adapter receipt — 2026-10-04

## Scope and ownership

- Candidate worktree: `C:\Users\Adam\.codex\worktrees\t08-agent-os\.local-ai-hub`
- Candidate HEAD: `2b33602adef0d030fea66cdcc04ca742c60b2e32`
- T08 baseline had 85 dirty status rows. This continuation adds the completion test as the 86th row; inherited paths remain untouched except the already-dirty `src/local_ai_hub/agent_tasks.py`, where this continuation adds one public adapter method.
- Root checkout: `C:\Users\Adam\.local-ai-hub`, HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`. Root source preimage SHA-256 `599812f8cd345ffa0087581cae60e073ae34c6914a344efd989baa937e3a1b0c`. Root checkout was not edited.
- `/api/context/pack`, T05-owned files, T09 files, and T13 files were not edited.

## Changes and hashes

| Path | Base | Post SHA-256 | Ownership |
|---|---|---|---|
| `src/local_ai_hub/agent_tasks.py` | `a86ff3b368c18eccead725cf30ed4bf793489324e209fe4a7ebf38820665c7ca` (inherited dirty baseline) | `544d7ab58f1be444d7ea4caae67c65e3519778d909264a39e8c1bbda431e7cbf` | One T08 method: `TaskStore.validate_completion` |
| `tests/test_agent_t08_completion_validation.py` | absent | `4a5115854559a7c630820c7c3ac99f97db70d65206d13164488dfb2d92e100f1` | New T08 focused tests |
| `handoff/t08-completion-validation-adapter-root-current-20261004.patch` | absent | `9a9406cafb7d44f472704ddce480e1a819a71e715c3f19b1184189c9839a8ab1` | Root-current overlay patch |
| `handoff/t08-completion-validation-adapter-root-current-20261004.md` | absent | recorded after write | This receipt |

Patch is pinned to the **root current working-tree** `agent_tasks.py` preimage SHA above, not clean root HEAD. Patch target source postimage SHA-256: `6ee041fc54ba05da18ddd542917423216a6010f50bcee2d49a271ee527a77b18`. Added test normalized-LF SHA-256: `3182fd409cc8968f9337061adaa8db8be8476a711b3c11422fdeed6112db09e1`.

## Public completion contract

- `TaskStore.validate_completion(self, task_id: str) -> TaskState`: loads persisted task; applies full completion gates, including checkpoint memory audit and persisted receipt/consistency state; read-only with respect to task/event state. Raises `KeyError` for missing task and propagates validation failure.
- `TaskStore.transition(task_id, TaskStatus.COMPLETED, ...)`: authoritative durable completion transition; revalidates before persistence.
- `VerificationStore.completion(self, task_id: str, now: float | None = None, *, include_consistency: bool = False, consistency_guard: Any | None = None, repository_revision: str = '', current_revision: str = '', warnings: Any = (), mappings: Any = (), records: Any = (), consistency: Mapping[str, Any] | None = None) -> CompletionResult`: receipt/consistency report only; does not validate checkpoint memory audit.
- `TaskStore.add_verification_receipt_in_transaction(self, con: sqlite3.Connection, task_id: str, criterion: str, receipt_id: str) -> tuple[TaskState | None, AgentEvent | None]`.
- `VerificationStore.record(self, receipt: VerificationReceipt) -> VerificationReceipt` and `VerificationStore.record_in_transaction(self, con: sqlite3.Connection, receipt: VerificationReceipt) -> tuple[VerificationReceipt, list[AgentEvent]]`.
- `TaskStore.resume(self, task_id: str, *, actor: str = 'agent', idempotency_key: str = '') -> TaskState`.

Contract and patch handoff sent to authorized T09 (`01a0d30c-4469-7ae2-b89e-1625fd3c7630`) and T13 (`01a0d8a1-7ce1-7470-8e18-ee0a2ac57a5d`). No files/tests in their worktrees changed or run.

## Verification receipts

Focused acceptance command, exit 0: `14 passed in 2.63s`.

```powershell
$env:PYTHONPATH=(Join-Path (Get-Location) 'src'); python -B -m pytest -q -p no:cacheprovider --tb=short -W error::ResourceWarning tests/test_agent_t08_completion_validation.py tests/test_agent_task_memory_adoption.py::test_create_and_resume_lookup_scoped_memory_without_unscoped_get tests/test_agent_task_memory_adoption.py::test_create_and_resume_attach_only_scoped_negative_knowledge tests/test_agent_task_memory_adoption.py::test_resume_refreshes_memory_and_checkpoint_keeps_audit_bundle tests/test_agent_task_memory_adoption.py::test_volatile_memory_requires_checkpoint_source_check_and_bundle_survives_checkpoint tests/test_agent_task_memory_adoption.py::test_transition_checkpoint_cannot_replace_server_memory_or_reuse_old_audit tests/test_agent_t08_durable_contract.py::test_task_transition_append_result_error_rolls_back_projection tests/test_agent_t08_durable_contract.py::test_verification_append_result_error_rolls_back_receipt_projection tests/test_agent_t08_durable_contract.py::test_verification_receipt_task_projection_and_events_rollback_together tests/test_agent_t08_receipt_transaction.py::test_receipt_projection_helper_is_caller_transaction_atomic tests/test_agent_tasks.py::test_completed_requires_all_criteria_to_have_fresh_receipts tests/test_agent_tasks.py::test_resume_abandoned_task
```

Owner suite, exit 0: `70 passed in 14.07s`.

```powershell
$env:PYTHONPATH=(Join-Path (Get-Location) 'src'); python -B -m pytest -q -p no:cacheprovider --tb=short -W error::ResourceWarning tests/test_agent_t08_completion_validation.py tests/test_agent_t08_cache_isolation.py tests/test_agent_t08_crash_after_commit.py tests/test_agent_t08_durable_contract.py tests/test_agent_t08_event_page_snapshot.py tests/test_agent_t08_live_order.py tests/test_agent_t08_migration_recovery.py tests/test_agent_t08_receipt_transaction.py tests/test_agent_incident_scope.py tests/test_lease_atomic_deadlock.py tests/test_agent_task_memory_adoption.py
```

Restart/crash acceptance, exit 0: `8 passed in 1.16s`.

```powershell
$env:PYTHONPATH=(Join-Path (Get-Location) 'src'); python -B -m pytest -q -p no:cacheprovider --tb=short -W error::ResourceWarning tests/test_agent_crash_recovery.py::test_committed_event_append_survives_restart_before_publish tests/test_agent_crash_recovery.py::test_committed_task_creation_survives_restart_before_publish tests/test_agent_crash_recovery.py::test_committed_task_transition_survives_restart_before_publish tests/test_agent_crash_recovery.py::test_crash_after_task_event_append_before_commit_rolls_back_projection_and_event tests/test_agent_crash_recovery.py::test_os_exit_after_task_event_insert_rolls_back_projection_and_event tests/test_agent_crash_recovery.py::test_committed_task_checkpoint_survives_restart_before_publish tests/test_agent_crash_recovery.py::test_committed_task_completion_survives_restart_before_publish tests/test_agent_crash_recovery.py::test_committed_task_failure_survives_restart_before_publish
```

Patch evidence: `git apply --check --whitespace=error` passed against root current worktree. Apply/reverse round trip passed against a temporary copy of the exact root source preimage; source restored to exact preimage SHA and added test removed. Root remained unchanged.

## Known excluded fixture failure

One pre-existing selector in inherited dirty `tests/test_agent_tasks.py`, `test_completed_succeeds_when_verified`, fails during setup: its fixture creates `repo-1`, then attempts to checkpoint server-managed `repo_root` / `worktree.repo_root`; `ValueError: Cannot checkpoint: repo_root is server-managed and cannot be modified`. File was not edited. The focused owner suite passes and the new dedicated valid-audit + persisted-receipt terminal-transition test covers the intended path.

T05 memory/SQLite migration fault matrix remains outside this receipt; this continuation does not claim that acceptance.

## Additional authorized blackboard trust selector

- Candidate `src/local_ai_hub/agent_context.py` SHA-256: `fee97b4d16388337d046d0c0c4d04f3ec34b087011eeee0363a6f0dbf7099317`.
- Root current `agent_context.py` SHA-256: `24781a491cafa5483b2dd09f7a233e9f3365152b4cddfca8f31cedb55655fa0b`; root already contains the same unverified-blackboard trust block, so no duplicate hunk was added to the root-current patch. T21 `coordination_id` left unchanged.
- Candidate selector `tests/test_agent_task_memory_adoption.py::test_unscoped_blackboard_is_unverified_and_cannot_bypass_task_memory_scope`: `1 passed in 1.69s`.
- Result sent to authorized T21; no T21 files/tests changed.

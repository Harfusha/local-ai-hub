# T08 current root-byte acceptance

Assigned HEAD: `2b33602adef0d030fea66cdcc04ca742c60b2e32`. Root HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`. Root dirty working bytes are captured; HEAD alone is not the source identity.

Command: `python -B -u run_end_to_end.py` in `C:\Users\Adam\.codex\worktrees\t08-agent-os\.local-ai-hub\handoff\t08-root-end-to-end-20261005`.

Actual output: **110 passed in 50.67s**. Exit `0`. Warnings fail as errors. Main process and child-process PYTHONPATH point to snapshot source.

[Exact selectors, output, per-path pre/post SHA256 and ownership receipt](end-to-end-receipt.json).

40 inherited tracked modifications retained byte-for-byte. No candidate source/test edits. Own writes only immutable handoff artifacts and isolated test state. Root untouched.

| Acceptance | Evidence |
|---|---|
| durable_state_and_cache_separation | PASS: `tests/test_agent_t08_cache_isolation.py`, `tests/test_agent_t08_durable_contract.py` |
| atomic_commit_replay_and_receipt_projection | PASS: `tests/test_agent_t08_crash_after_commit.py`, `tests/test_agent_t08_receipt_transaction.py`, `tests/test_agent_crash_recovery.py::test_committed_event_append_survives_restart_before_publish`, `tests/test_agent_crash_recovery.py::test_committed_task_creation_survives_restart_before_publish`, `tests/test_agent_crash_recovery.py::test_committed_task_transition_survives_restart_before_publish`, `tests/test_agent_crash_recovery.py::test_crash_after_task_event_append_before_commit_rolls_back_projection_and_event`, `tests/test_agent_crash_recovery.py::test_os_exit_after_task_event_insert_rolls_back_projection_and_event`, `tests/test_agent_crash_recovery.py::test_committed_task_checkpoint_survives_restart_before_publish`, `tests/test_agent_crash_recovery.py::test_committed_task_completion_survives_restart_before_publish`, `tests/test_agent_crash_recovery.py::test_committed_task_failure_survives_restart_before_publish` |
| ordered_publication_and_bounded_event_pages | PASS: `tests/test_agent_t08_event_page_snapshot.py`, `tests/test_agent_t08_live_order.py` |
| corruption_backup_preflight_ddl_failure_and_retry | PASS: `tests/test_agent_t08_migration_recovery.py`, `tests/test_t05_agent_state_migrations.py` |
| scoped_incident_and_lease_safety | PASS: `tests/test_agent_incident_scope.py`, `tests/test_lease_atomic_deadlock.py` |
| completion_validation_and_memory_audit | PASS: `tests/test_agent_t08_completion_validation.py`, `tests/test_project_memory_audit_completion.py` |
| memory_auto_create_resume | PASS: `tests/test_agent_task_memory_adoption.py`, `tests/test_agent_state_e2e.py::test_local_app_wires_scoped_memory_adoption_on_create_and_resume` |
| memory_use_nonuse_evidence_isolation_stale_corrupt_and_caps | PASS: `tests/test_agent_incident_scope.py`, `tests/test_agent_task_memory_adoption.py` |
| memory_privacy_correction_delete_origin_and_fts | PASS: `tests/test_agent_memory_t08_tombstones.py`, `tests/test_agent_memory_t08_rollback_masking.py`, `tests/test_memory_delete_identity_contract.py`, `tests/test_t05_memory_delete_artifacts.py`, `tests/test_t05_memory_fts_atomicity.py`, `tests/test_agent_memory.py::test_memory_write_redacts_private_fields_and_blocks_sensitive_records`, `tests/test_agent_memory.py::test_memory_correction_lineage_and_delete_survive_reopen` |

Root source/test drift at final check: `[]`. Candidate inherited path/hash drift: `[]`.

Task remains **review**. Agent OS completion is **NOT VERIFIED**: orchestrator reported gaming-mode retryable block; Hub remains ignored. No duplicate task, no retry/poll, no merge/root edits. Native acceptance receipts do not authorize a done claim for the live Agent OS task.

# T08 Acceptance Follow-up — 2026-10-01

Candidate: `C:\Users\Adam\.codex\worktrees\t08-agent-os\.local-ai-hub`  
HEAD: `2b33602adef0d030fea66cdcc04ca742c60b2e32`

## Ownership and scope

Started with a dirty T08 candidate. Current inventory: 37 modified tracked paths and 128 untracked paths (untracked artifacts/tests included individually). Preserved all existing state. This follow-up added only this receipt file; no production or test source changed during the follow-up. The user-approved blackboard trust implementation and selector were already present in the dirty T08 files, so the older root-current patch was not reapplied (`git apply --check` rejected its stale context).

## Receipts

- `python -B -m pytest -q --tb=short -W error::ResourceWarning tests/test_agent_task_memory_adoption.py::test_unscoped_blackboard_is_unverified_and_cannot_bypass_task_memory_scope` — **1 passed in 0.66s**.
- `python -B -m pytest -q --tb=short -W error::ResourceWarning tests/test_agent_crash_recovery.py::test_crash_after_task_event_append_before_commit_rolls_back_projection_and_event tests/test_agent_crash_recovery.py::test_os_exit_after_task_event_insert_rolls_back_projection_and_event tests/test_agent_crash_recovery.py::test_committed_receipt_and_task_projection_survive_restart_before_publish tests/test_agent_t08_crash_after_commit.py::test_process_exit_during_receipt_write_recovers_atomically` — **5 passed in 1.35s**.
- `python -B -m pytest -q --tb=short -W error::ResourceWarning tests/test_agent_t08_durable_contract.py tests/test_agent_t08_cache_isolation.py::test_disposable_cache_rebuild_preserves_live_agent_state tests/test_agent_t08_receipt_transaction.py::test_receipt_projection_helper_is_caller_transaction_atomic tests/test_agent_tasks.py::test_transition_idempotency_reuse_by_different_actor_is_rejected tests/test_agent_tasks.py::test_checkpoint_idempotency_replay_requires_same_actor tests/test_agent_tasks.py::test_same_status_transition_rejects_idempotency_key_owned_by_another_actor tests/test_agent_tasks.py::test_completed_uses_task_context_repo_root_without_worktree_checkpoint tests/test_agent_verification.py tests/test_lease_atomic_deadlock.py tests/test_agent_t08_live_order.py tests/test_agent_t08_event_page_snapshot.py tests/test_agent_state_e2e.py tests/test_agent_state_reliability.py tests/test_swarm_orchestrator.py tests/test_sse_events_stream.py tests/test_agent_t08_migration_recovery.py` — **85 passed, 2 failed in 56.46s**. Failures are `tests/test_agent_state_e2e.py::test_interrupted_task_resumes_with_fresh_evidence_and_no_duplicate_command` and `tests/test_agent_state_e2e.py::test_e2e_completion_gate_enforcement`; both fail closed because candidate `src/local_ai_hub/project_config.py` is absent (`ModuleNotFoundError`). This is the known T21/T09 integration seam, not an atomicity failure. No non-T08 dependency was added here.
- `git diff --check` — **exit 0** (Git emitted only existing LF-to-CRLF working-copy warnings).

## Source pins

SHA-256 at verification:

- `src/local_ai_hub/agent_context.py`: `752F22929ABD0A2A54B805E37BDF6A1723C5C53E84F6D41B1DEC29E09F1FF875`
- `src/local_ai_hub/agent_blackboard.py`: `9222A5084BBB0A937CADB79A091134CABD4CA3A73B7A1321F0035DB4DC78E2D1`
- `tests/test_agent_task_memory_adoption.py`: `41AC03E3121C4E307B303D638C9E624A38633C3E74D0D62BB6CE3807C2811AF0`
- `src/local_ai_hub/agent_events.py`: `B00AAF9A109B697CE7D3A8756EF3E88BD72772D2F36DEC30BF3ACDA76E6BABE3`
- `src/local_ai_hub/agent_tasks.py`: `1D59F3E1FA8A6082EAA439F4EC3D4C542BBAD47FA5F2664D76570462FB505D25`
- `src/local_ai_hub/agent_verification.py`: `6924D69A94EDFE8ADFB5C7F4FB5B94731855F7A956127CDAAF537B51133A357A`
- `tests/test_agent_crash_recovery.py`: `5D74703C2AB77D2C3B59412C3E7FB6BCDE505764BBF7F9BADB4FB85B44BC0FBF`
- `tests/test_agent_t08_crash_after_commit.py`: `AEE9E6B7A74E3E16C7985BF5C7843B0DDC420F26D748DA9881E33451C0BC8541`

No root checkout was modified. No blackboard trust hunk was added in this follow-up; the approved selector verified the already-present T08 implementation. HUB was intentionally not used.

## Additional recovery/state follow-up

- `python -B -m pytest -q --tb=short -W error::ResourceWarning tests/test_agent_t08_crash_after_commit.py::test_process_exit_after_commit_before_publish_recovers_event tests/test_agent_t08_crash_after_commit.py::test_process_exit_after_task_commit_before_publish_recovers_projection_and_cursor tests/test_agent_memory_t08_rollback_masking.py::test_delete_preserves_primary_fts_error_when_rollback_also_fails tests/test_agent_memory_t08_tombstones.py::test_deleted_memory_record_replay_is_tombstoned_after_reopen` — **3 passed, 2 failed in 1.08s**. All three after-commit event/task cases passed. Both memory deletion cases error before assertions because they pass `scope=`, `scope_id=`, `root=`, and `tenant=` to the current `MemoryStore.delete(record_id)` API (`TypeError: unexpected keyword argument 'scope'`). Existing T05 handoff identifies this as a T05-owned store API seam; no store or test changes made.
- `python -B -m pytest -q --tb=short -W error::ResourceWarning tests/test_agent_state_operations.py tests/test_agent_state_transport.py::test_http_coord_pubsub_poll_honors_sequence_cursor tests/test_agent_state_transport.py::test_coord_task_checkpoint_action_preserves_existing_memo_actions` — **17 passed, 1 error in 66.72s**. The only error is fixture setup for `test_coord_task_checkpoint_action_preserves_existing_memo_actions`: `MemoryStore.put` rejects a non-string tenant supplied through the old positional call (`ValueError: memo tenant label must be a string`). I did not alter the mixed transport fixture or T05 memory API.
- T01 receipt request was answered read-only in T01 thread `01a0d30b-fffc-7810-a1ca-9cdde7be9264`. Existing receipt command had 2 passes in 2.89s; result CSV SHA-256 `BB2C8C2B0AA429AA69B91D1328DEB5852F03510810F84A1F07BB1A9E92C7F49F`; selector source SHA-256 `6E63AA4324650F2AF8A6951284D8548EBC507FD393FED8409A31B797CC55F9A8`. No T01/root changes.

Additional source pins: `tests/test_agent_state_operations.py` `C1EF95C6ACDBF1AFFDB00F28901EDBD4F0DEB47C6A6A76A4F00DF2CAD05C2141`; `tests/test_agent_state_transport.py` `15C4E8F04A247D1F0E0BD8A5771812477616308E8E50CB60CEDBBF62F94C714F`; `tests/test_agent_memory_t08_rollback_masking.py` `555A16A3FA67E1244C75C6EE1289E46C95960131B251B5FA9821888547B5D726`; `tests/test_agent_memory_t08_tombstones.py` `60722CBD769CE6BD3704D9632BE1A1EA9FDC7ABE0C9F6EF4C3D97F041A7513EF`.

# T06 validation receipt candidate v2

Owner: T06. Worktree: `C:\Users\Adam\.codex\worktrees\t06-safe-commands\.local-ai-hub`.

Base: `94337de7309b66c63ff427cce8cd3a49e6414d73`.

- Patch: `handoff/T06-T09-validation-receipts-v2.patch`
- Patch SHA-256: `58EC1AE45611BA89DE79D38B95DF37BF7B1A3AF41FD826AE919D551765895F42`
- `commands.py` preimage SHA-256: `9C6DA1447DBC3EA32CCD85E13D4A52136F07B557A2FCCCCA47A769656BC3C68C`
- Changed paths: `src/local_ai_hub/commands.py`, `tests/test_t06_t09_validation_receipts.py`
- Handoff note and patch are immutable version `v2`.

The producer records actual configured command, SHA-256, T09 classification, tenant owner, revision, mutation generation, exit status, and full command result in a durable `work_command_verification` artifact. Receipt creation supplies typed T09 fields when supported. The new positive test runs configured `python -m pyflakes`, reads the persisted proof, then completes the task through HTTP.

Validation in T06 worktree:

```text
python -m pytest -q --tb=short tests/test_t06_t09_validation_receipts.py tests/test_agent_os_enhancements.py::test_command_broker_auto_registers_verification_receipt
2 passed, 3 skipped in 5.15s
```

The three skipped cases are substituted-command, stale receipt, and wrong owner. This T06 checkout lacks T09 `VerificationReceipt.owner`; skips are not acceptance evidence. T09 typed API and production gate integration remain required. In particular, run the substituted-command negative only after an isolated overlay imports current T09 typed API and gate; do not infer success from the T06 positive case.

Scoped rollback, uncertain outcome, journal retention, and daemon process-tree cleanup negatives:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_command_rollback.py::test_timeout_rollback_failure_is_unknown_invalidates_cache_and_records_write_set tests/test_command_rollback.py::test_run_does_not_restore_while_process_tree_cleanup_is_unconfirmed tests/test_command_rollback.py::test_rollback_aborts_when_hardlink_appears_after_postimage_check tests/test_command_transaction_snapshot.py::test_transaction_recovery_preserves_foreign_change_and_keeps_journal tests/test_daemon_lifecycle_hardening.py::test_stop_daemon_leaves_no_child_process_orphan tests/test_daemon_lifecycle_hardening.py::test_stop_daemon_does_not_kill_only_leader_when_tree_stop_fails
6 passed in 20.00s
```

Patch validation against the recorded preimage: `git apply --check` passed; patch applied in isolated temp tree; Python AST parsing passed for transformed source and test. `python -m pyflakes tests/test_t06_t09_validation_receipts.py` and `git diff --check` passed.

Live Docker transaction acceptance remains blocked by the unavailable Windows Docker Linux engine. T09/T16 durable recovery-lock/fencing integration remains unconfirmed. No root checkout was edited or tested.

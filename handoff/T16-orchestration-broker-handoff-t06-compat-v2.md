# T16 orchestration to broker handoff receipt

## Scope

Isolated compatibility overlay: `C:\Users\Adam\AppData\Local\Temp\t16-t06-broker-compat-overlay-20261001`. It combines current T16 orchestration/services/fencing modules with the exact T06 command and process utility sources used by T06's 13-test receipt. No root files were edited. This is not root integration.

## T16 end-to-end receipt

Command:

```powershell
$env:PYTHONPATH='C:\Users\Adam\AppData\Local\Temp\t16-t06-broker-compat-overlay-20261001\src'; python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t16_orchestration_broker_handoff.py::test_work_orchestrator_validation_reaches_real_broker_with_fence
```

Result: `1 passed in 2.26s`, exit 0.

`WorkOrchestrator` passed its fencing store to T06 `CommandBroker`. T16 `LocalAIServices.command` forwarded the writer fence. Real `git diff --check` succeeded through the broker. A stale fence on mutating `git add owned.txt` was rejected before Docker transaction spawn or index mutation. The fixture used a registered-task-store stub and stubbed Docker readiness; it did not run a live Docker mutation.

Fixture: `handoff/T16-orchestration-broker-handoff-acceptance.py`, SHA-256 `A5472294E010E15D3C3FEA4CD19A82C3070B8279A858C603DD5026892FFE60CF`.

## T06 13-test handoff receipt

Exact command from T06 handoff:

```powershell
python -m pytest -q --tb=short -p no:cacheprovider tests/test_t06_server_command_provenance.py tests/test_t06_worktree_subprocess_tracking.py tests/test_command_transaction_snapshot.py::test_mutating_run_requires_authoritative_fencing_before_spawn tests/test_command_transaction_snapshot.py::test_private_transaction_requires_work_attempt_even_when_store_is_available tests/test_command_transaction_snapshot.py::test_fenced_transaction_recovery_requires_current_work_attempt tests/test_command_transaction_snapshot.py::test_expired_transaction_lease_cannot_overwrite_newer_declared_path tests/test_command_transaction_snapshot.py::test_transaction_recovery_preserves_foreign_change_and_keeps_journal tests/test_command_transaction_snapshot.py::test_disjoint_private_transactions_commit_only_their_declared_paths tests/test_command_rollback.py::test_private_transaction_source_conflict_marks_outcome_unknown_and_invalidates_caches tests/test_command_rollback.py::test_run_does_not_restore_while_process_tree_cleanup_is_unconfirmed tests/test_command_rollback.py::test_execute_does_not_kill_or_reap_after_tree_cleanup_is_unconfirmed tests/test_process_utils.py::test_run_hidden_timeout_kills_real_windows_descendant_after_root_exit
```

Result: `13 passed in 20.79s`, exit 0. T06 log SHA-256 `4818FCB87FBF1CCBC1EB5A83D22A7E39438678F53EB3E8EBD450CDA453136B0A`.

T06 patch SHA-256: `82E554B57C31599744E2DA3014EE95C2B5DF3E85B98847FC6A2BE81EDA58392C` (`T06-provenance-worktree-hardening-v1.patch`).

T06 source pins in both receipts: `commands.py` SHA-256 `B31909175FC4D939AE0FF1EE24F998381ED4FC4C6C8FE0068F66CC424DB64AD9`; `process_utils.py` SHA-256 `766D5378CD8B838D50CFA2B36B0091D30B5BCFDB620C9D37934AA3CE76D914E2`.

T16 overlay pins: `services.py` SHA-256 `B1F1E117F49D566E067257E90868CD4134B736C1D3F49A783DC4EDE79BE9C97E`; `work_orchestrator.py` SHA-256 `70C5084F02D4D1202C5375194324A6E6754C5623C4389DED19846CF4CE9B3AD5`; `work_fencing.py` SHA-256 `214A91EF21B2A00B77DA3D15AA0ABB18452CC8C18B2242FC5CC58469BCD28B05`; T06 `command_transactions.py` SHA-256 `CFFC36198FD402754E9F4B2BAC4472351FC9313AB5EC65BB1D6A6FCC95CE86FA`.

## T20 integration blocker

Root-current `commands.py` SHA-256 is `A17C02E1A5C4CED5372D75090758A647898BAC2723D6AD3DF5346344224406E7`. T06 patch `handoff/T06-root-current-broker-fence.patch` SHA-256 `AE14F18930F58F4A708AF0882BBAD3FD0D8FAE22C8679D3F870E2B86F32B95E8` fails `git apply --check` on an isolated copy of that exact root file at the first hunk (`commands.py:3`); the root already contains the `contextmanager` import. Root also has the setter, T16 service forwarding, and orchestrator fence emission. T20 must reconcile patch hunks against current root instead of applying blindly, then produce root-owned acceptance against those exact root sources.

This overlay proves compatibility only. T20 still owns root reconciliation, real task-store wiring, live Docker mutation, and final root acceptance.

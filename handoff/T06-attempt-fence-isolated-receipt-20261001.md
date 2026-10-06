# T06 attempt-fence isolated acceptance receipt

Date: 2026-10-01
Candidate HEAD: `94337de7309b66c63ff427cce8cd3a49e6414d73`
Historical result: `10 passed, 17.68s, exit 0`; superseded for current source by `handoff/T06-targeted-security-receipt-20261001.md`.
Scope: narrow safety regression only; no performance claim.

## Isolation and import origin

Copied current candidate `src/local_ai_hub` and selected tests into:

`C:\Users\Adam\AppData\Local\Temp\t06-attempt-fence-overlay-20261001-379f2e783b264c07a03004e9098755ef`

Overlay `tests/conftest.py` adds an import-origin assertion. Preflight printed and verified:

`C:\Users\Adam\AppData\Local\Temp\t06-attempt-fence-overlay-20261001-379f2e783b264c07a03004e9098755ef\src\local_ai_hub\commands.py`

Candidate source hashes copied into the overlay:

- `src/local_ai_hub/commands.py`: `31785DD1C3858705B6553B51388D059573D0768BFDBD15F1E0F213D07F86AAD4`
- `src/local_ai_hub/command_transactions.py`: `CFFC36198FD402754E9F4B2BAC4472351FC9313AB5EC65BB1D6A6FCC95CE86FA`
- `tests/test_command_transaction_snapshot.py`: `1F1D9EBF17A86BB1A957C3EF2A73FED26780A982BB7A5888726ABC2F424A989E`
- `tests/test_command_rollback.py`: `F3F5D06C3AA3C8EC2A23E34E6BA3ABDB658981B4DF6437AA92363EB0C51D0CB6`
- `tests/test_process_utils.py`: `F83869A2B00624B4156696BD577BCEE144BBBB40ABE35EAFA172CCEEB073A957`
- `tests/fencing_lease_support.py`: `DDE8B5755E9639D7D267F7AB136C965889AAE3001925346F97561EB6A4691E7B`

All copied test files and helper matched task worktree hashes. Only overlay `conftest.py` differs, to assert import origin.

## Exact command

Run from the overlay in PowerShell:

```powershell
$overlay='C:\Users\Adam\AppData\Local\Temp\t06-attempt-fence-overlay-20261001-379f2e783b264c07a03004e9098755ef'; Set-Location $overlay; $env:PYTHONPATH=Join-Path $overlay 'src'; python -m pytest -q --tb=short -p no:cacheprovider tests/test_command_transaction_snapshot.py::test_mutating_run_requires_authoritative_fencing_before_spawn tests/test_command_transaction_snapshot.py::test_private_transaction_requires_work_attempt_even_when_store_is_available tests/test_command_transaction_snapshot.py::test_fenced_transaction_recovery_requires_current_work_attempt tests/test_command_transaction_snapshot.py::test_expired_transaction_lease_cannot_overwrite_newer_declared_path tests/test_command_transaction_snapshot.py::test_transaction_recovery_preserves_foreign_change_and_keeps_journal tests/test_command_transaction_snapshot.py::test_disjoint_private_transactions_commit_only_their_declared_paths tests/test_command_rollback.py::test_private_transaction_source_conflict_marks_outcome_unknown_and_invalidates_caches tests/test_command_rollback.py::test_run_does_not_restore_while_process_tree_cleanup_is_unconfirmed tests/test_command_rollback.py::test_execute_does_not_kill_or_reap_after_tree_cleanup_is_unconfirmed tests/test_process_utils.py::test_run_hidden_timeout_kills_real_windows_descendant_after_root_exit
```

Stdout log: `%TEMP%\local-ai-hub-t06-attempt-fence-isolated-20261001.log`; SHA-256 `F7377502FAD0481B0F863B2A1FEE190277CBF9C5AB4921E66D823005FA1989A5`.

## Results

- Mutations fail closed without authoritative fencing or a current task attempt.
- Recovery requires a newer current attempt and preserves its journal when a foreign edit blocks recovery.
- An expired owner cannot import over a newer owner; disjoint write sets commit independently.
- Source conflict returns unknown and invalidates command caches.
- Rollback does not restore while process-tree cleanup is unconfirmed.
- Windows descendant test confirmed child exit after timeout cleanup. Test asserted elapsed time below 8 seconds; this is a safety bound, not a performance benchmark.

Broker transaction tests use fake fencing and Docker-readiness seams. No live Docker engine or image was used. Receipt does not prove Docker isolation, full-suite status, or production T09/T16 transport integration.

## Patch binding

Related existing narrow patch: `handoff/T06-root-current-broker-fence.patch`, SHA-256 `AE14F18930F58F4A708AF0882BBAD3FD0D8FAE22C8679D3F870E2B86F32B95E8`. Patch was not rewritten. A read-only reverse-apply check against current candidate failed at `commands.py:3` because its import context differs. This receipt validates the exact current candidate source hashes above, not patch application. T20 must check patch applicability against its owned root base. No root file changed.


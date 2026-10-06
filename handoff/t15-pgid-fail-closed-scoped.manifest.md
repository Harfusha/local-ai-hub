# T15 scoped fail-closed POSIX handoff

## Scope and baseline

- Worktree: `C:\Users\Adam\.codex\worktrees\fefe\.local-ai-hub`
- Base HEAD: `3ac4d67ec26bcda6e3f55427441fd72258323e27`
- Patch includes only `src/local_ai_hub/process_utils.py` POSIX `terminate_tree` hunk and four focused tests in `tests/test_command_concurrency_contract.py`.
- `commands.py` is excluded from patch. T06 owner explicitly retains that path and released no write lease. A `local_ai_coord` lease lookup returned `outcome_unknown` (`req_f3ad168f90e7`); not retried. No source hunk copied, staged, overwritten, or integrated.
- No write to T06 worktree. No Docker/WSL/Linux engine started.

## Scoped patch

- Path: `handoff/t15-pgid-fail-closed-scoped.patch`
- SHA-256: `7D8AD3777BDD72B552DC83B7583998383A4222344E4015F2F80C99F0539CC064`
- `git apply --stat` parsed patch: 2 files, 104 insertions, 35 deletions. Patch was not applied; apply-check and reverse proof not run.

Baseline and scoped target blob hashes (Git blob SHA-1):

- `src/local_ai_hub/process_utils.py`: base `d0488b75c3fb5c589d6d79afe362c228c7a69ee5`; scoped target `4f1a5332f3cd5e60df9d7aa85af7b1d1cfb7ce8c`.
- `tests/test_command_concurrency_contract.py`: base `c1913c1e2ef9648e8602ca1a32f91b70fc22f8b5`; scoped target `282bd7ee64432c94c484f8a9efd2c7545f61ca80`.

## Test receipt

Windows host, POSIX behavior mocked. Exact bounded command:

```powershell
python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_command_concurrency_contract.py::test_linux_daemon_group_marker_requires_matching_group_and_digest tests/test_command_concurrency_contract.py::test_linux_group_marker_rejects_pgid_reuse_during_scan tests/test_command_concurrency_contract.py::test_recovered_daemon_rejects_reused_leader_even_when_group_is_alive tests/test_command_concurrency_contract.py::test_recovered_daemon_rejects_leaderless_group_without_ownership_proof tests/test_command_concurrency_contract.py::test_recovered_daemon_requests_leaderless_group_cleanup_without_claiming_success tests/test_command_concurrency_contract.py::test_posix_numeric_process_group_cleanup_fails_closed_without_signals tests/test_command_concurrency_contract.py::test_posix_terminate_tree_refuses_unowned_numeric_pid_and_group tests/test_command_concurrency_contract.py::test_explicit_process_group_reports_unknown_liveness_without_pid_fallback tests/test_command_concurrency_contract.py::test_posix_cleanup_does_not_report_success_when_signals_are_denied
```

Result: **9 passed in 0.35s**. Existing dirty-worktree receipt, not Linux runtime proof. The four POSIX termination tests are included in scoped patch; scan/recovery tests rely on surrounding T15 dirty state and are not part of this patch.

## Runtime blocker and safety boundary

Host is Windows. No Linux kernel/runtime was available for authoritative POSIX process-group execution; Docker, WSL, and Linux engine startup were prohibited. POSIX syscalls in these tests are mocks. No real orphan process was created or observed. Numeric PGID can be reused between an ownership check and `killpg`; no continuously held process-group signal capability is available in this path. Code therefore refuses the POSIX tree signal and returns `False`.

**Orphan-process termination remains unproven. Refusal can leave children running. Do not claim no-orphan cleanup PASS.**

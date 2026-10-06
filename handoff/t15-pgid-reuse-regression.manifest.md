# T15 PGID reuse regression evidence

## Scope

- Worktree: `C:\Users\Adam\.codex\worktrees\fefe\.local-ai-hub`
- HEAD: `3ac4d67ec26bcda6e3f55427441fd72258323e27`
- Added only `test_linux_group_marker_rejects_pgid_reuse_during_scan` to the already-dirty T15 file `tests/test_command_concurrency_contract.py`.
- Current test file SHA-256: `7B5B0BC5A21B3BE0EF04402742DB7E7BEE5632FA8A815880AC594DF8CE6D5B14`
- Current test file Git blob: `6aa1bbbed92c8689cbf046b9c563b7b2312c7285`
- No root checkout changes. No changes to `cache.py`, rollback ownership, or T15 performance hunks. No Docker/WSL/Linux engine started.

## Regression and receipt

The new host-safe test changes the mocked `/proc/<pid>/stat` process-group ID between the before/after reads around the ownership-token read. `_linux_group_member_owns_token` must reject that unstable identity. The test asserts rejection and exactly two stat reads.

Command:

```powershell
python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_command_concurrency_contract.py::test_linux_daemon_group_marker_requires_matching_group_and_digest tests/test_command_concurrency_contract.py::test_linux_group_marker_rejects_pgid_reuse_during_scan tests/test_command_concurrency_contract.py::test_recovered_daemon_rejects_reused_leader_even_when_group_is_alive tests/test_command_concurrency_contract.py::test_recovered_daemon_rejects_leaderless_group_without_ownership_proof tests/test_command_concurrency_contract.py::test_explicit_process_group_never_falls_back_to_leader_pid tests/test_command_concurrency_contract.py::test_explicit_process_group_reports_unknown_liveness_without_pid_fallback
```

Result: **6 passed in 0.47s** on the Windows host. POSIX behavior here is mocked; this is not Linux runtime proof.

## Limitation

This test covers PGID change during the ownership scan, and the existing tests cover leader PID reuse and no PID fallback for explicit groups. They do not close the TOCTOU window after `_daemon_process_group_owned` returns and before numeric `killpg` executes. `terminate_tree` still receives a numeric PGID, not an atomic stable group handle. Do not report no-orphan or PGID-reuse safety acceptance from this receipt. Linux leaderless stop/recovery remains unverified and requires a stable group-owner contract plus supported Linux runtime proof.

## Fail-closed signal-target follow-up

The initial receipt above is superseded for the renamed cleanup test. The ownership scan regression remains unchanged. POSIX `terminate_tree` now refuses numeric PID/PGID signaling unconditionally until callers can supply a continuously held owner capability; `_RecoveredDaemonProcess.kill()` returns that cleanup result instead of hiding refusal. This prevents signaling a reused group, but leaves cleanup unconfirmed.

Changed scoped files:
- `src/local_ai_hub/process_utils.py`: SHA-256 `B7D9E6A10A4B501DCBFEA13330A2157D987E87F34F023540C293C7B7730098F0`; Git blob `e5b7637975cf1a5d4300e9d5174063e014e09508`.
- `src/local_ai_hub/commands.py`: SHA-256 `0C801156B0A44D4A7062C2AAA99EBF4CF862E89ED87BD8424C19D5F55ECF20E3`; Git blob `a9e927362f21fd3b381c30d771dd0059a124937f`.
- `tests/test_command_concurrency_contract.py`: SHA-256 `E0C636A0FF11747E83E5D10C2E7A67DC2D28A7F6FED0F5C0C3461C20C49C222D`; Git blob `aac6218930c395dda18afd75a6613d47945ad0e3`.

The files already contain other T15-owned dirty hunks; these hashes identify whole working files, not standalone patches. No root checkout edits. No Docker, WSL, or Linux engine started.

Bounded regression command ran on Windows with POSIX OS behavior mocked: 9 passed in 0.35s. `git diff --check` exited 0; Git emitted only LF-to-CRLF normalization warnings for pre-existing dirty files.

No-orphan cleanup remains unproven. POSIX cleanup now fails closed and may leave descendants alive; no Linux runtime proof was performed.

Exact follow-up test command:

```powershell
python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_command_concurrency_contract.py::test_linux_daemon_group_marker_requires_matching_group_and_digest tests/test_command_concurrency_contract.py::test_linux_group_marker_rejects_pgid_reuse_during_scan tests/test_command_concurrency_contract.py::test_recovered_daemon_rejects_reused_leader_even_when_group_is_alive tests/test_command_concurrency_contract.py::test_recovered_daemon_rejects_leaderless_group_without_ownership_proof tests/test_command_concurrency_contract.py::test_recovered_daemon_requests_leaderless_group_cleanup_without_claiming_success tests/test_command_concurrency_contract.py::test_posix_numeric_process_group_cleanup_fails_closed_without_signals tests/test_command_concurrency_contract.py::test_posix_terminate_tree_refuses_unowned_numeric_pid_and_group tests/test_command_concurrency_contract.py::test_explicit_process_group_reports_unknown_liveness_without_pid_fallback tests/test_command_concurrency_contract.py::test_posix_cleanup_does_not_report_success_when_signals_are_denied
```


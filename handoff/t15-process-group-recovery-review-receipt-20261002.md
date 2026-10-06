# T15 Process-Group Recovery Review Receipt

Status: `TEST_PREPARED_WAITING_FOR_SERIAL_TEST_SLOT`

## Source pin

- Worktree: `C:\Users\Adam\.codex\worktrees\t15-command-config\.local-ai-hub`
- HEAD: `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`
- `src/local_ai_hub/commands.py` SHA-256: `8EE6ACA27FA1FF4EA4ADC2686A426EC469E9B35955D60E264027BAE735D5020A`
- `tests/test_command_concurrency_contract.py` SHA-256: `BD3457A1C04CF777512DDAEB6525545BBF69B5CA326E493EBE29405304780DFB`
- Tracked worktree diff for `commands.py` against HEAD: 852 insertions, 59 deletions; existing dirty changes preserved.

## Review

- Recovery registry v3 persists `process_group_id`. Current restore checks `process_identity(pid) is None`, `process_group_id == pid`, and group liveness, but `process_identity()` also returns `None` when identity cannot be proven and on non-Linux POSIX. That is not sufficient proof that leader exited.
- Prepared regression rejects restoration when group is live but leader absence is unverifiable. Intended fix: prove leader absence/zombie from Linux `/proc`; reject recovery on unsupported platforms or unreadable process state. Permission/OS errors during group checks remain unverifiable; cleanup does not claim success.
- Rollback snapshot/restore implementation and `tests/test_command_rollback.py` have no diff. The added `run_project_command` route defaults rollback off and forwards only explicit `rollback_paths`; an empty path list is rejected by the existing snapshot gate.
- `git diff --check` passed; Git emitted only its existing LF-to-CRLF working-copy warning.

## Targeted commands, not yet run

```powershell
python -B -m pytest -q tests/test_command_concurrency_contract.py::test_daemon_registry_rejects_unverifiable_leader_with_live_group
python -B -m pytest -q tests/test_command_concurrency_contract.py::test_daemon_registry_recovers_live_group_after_leader_exit tests/test_command_concurrency_contract.py::test_recovered_daemon_accepts_dead_leader_only_for_verified_group tests/test_command_concurrency_contract.py::test_recovered_daemon_rejects_reused_leader_pid tests/test_command_concurrency_contract.py::test_process_group_permission_denied_is_not_verified tests/test_command_concurrency_contract.py::test_daemon_registry_rejects_unverifiable_leader_with_live_group
```

The first command is the RED check; the second is the targeted GREEN/regression run after the source fix. No T15 tests have run in this continuation. T02 ended its slot-05 matrix interrupted with no paired receipt. T11 used slot `T20-CPU-SLOT-20261002-05` for 93 passing checks and released it to T20. T15 remains queued; run only after T20 explicitly assigns a slot to T15. Update this receipt with exact output, exit code, and final hashes after the assigned run.

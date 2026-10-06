# T06 safe mutation remaining ownership and acceptance

Date: 2026-10-01
Status: cache fix appears integrated in root; safe-mutation architecture goal remains open.

## Ownership

- T06 candidate owns cache coordination/fail-closed implementation in `src/local_ai_hub/cache.py`, broker cache-read integration in `src/local_ai_hub/commands.py`, and transaction/rollback implementation in `src/local_ai_hub/command_transactions.py` and the bounded rollback helpers/call sites in `commands.py`.
- T20 owns root integration and current-root acceptance. T20 reports cache source postimages already present; no duplicate patch should be applied.
- T09 owns `agent_verification.py` receipt consumer. T06 has not edited it.
- Preserve T06's inherited dirty files and worktree ownership; no root writes by T06.

## Remaining acceptance

1. POSIX rollback still has a postimage check followed by `os.replace`; existing comment acknowledges check-to-replace TOCTOU. Reproduce race and mitigate within owned broker scope, or report exact residual and platform evidence to T20.
2. Current overlay is Windows. The Windows leaf-created-after-absence test is skipped here; POSIX TOCTOU race is unverified.
3. T20 current-root focused cache/rollback receipts remain authoritative; cache integration alone does not close rollback/write-set acceptance.

## Root-current rollback overlay receipt — 2026-10-01

- Root remained read-only. Overlay: `C:\Users\Adam\AppData\Local\Temp\t06-rollback-root-overlay-20261001`.
- Patch: `handoff/T06-rollback-proof-and-fence-root-current.patch`; SHA256 `228DBA5304AE7A7FE57E3A41C7EFB67F6EE18F8660B6C5B73926DB21CDBAEB9F`. `git apply --check` passed against fresh copies of root source and tests.
- Initial focused batch: 14 passed, 1 skipped. Root-snapshot rollback tests covered declared write set, concurrent write conflict/outcome-unknown, postimage identity mismatch, missing postimages, symlink and hardlink rejection, and hardlink-at-restore check. Transaction snapshot tests in this first batch came from the T06 candidate snapshot, not the root snapshot.
- After refreshing transaction tests from root snapshot, current-root focused transaction batch: 5 passed. Covered declared output, undeclared output rejection, patch import, recovery completion, and recovery preserving foreign edits.
- Fence-specific patch rollback and symlink batch: 2 passed.
- T09 contract check: `test_structured_project_validation_binds_args_and_private_environment` passed (1 passed, 13.38 s). Generic proof stores command digest; raw command retained for project-bound proof. No T09 source or consumer expectations changed.
- Existing `test_successful_short_command_creates_auditable_verification_evidence` passed in the 14-test batch after producer redaction. Earlier failure was diagnosed: generic proof included raw `command`, while test expected digest-only evidence.
- One later mixed pytest invocation exceeded its output wait window; partial dots only, so it is not counted as a receipt.
- Still open: POSIX check-to-replace TOCTOU reproduction and fix or accepted residual. Cache implementation remains integrated by T20; T06 did not duplicate it.

## Root-current test fence adapter — 2026-10-01

- Test-only patch: `handoff/T06-root-test-fence-adapter.patch`; SHA256 `8276E55FC68EBA4ADF52399CAB5A6A7F3581B162D0E36F5A41676C9774429642`.
- Scope: `tests/conftest.py` and `tests/fencing_lease_support.py`; 33 insertions, 2 deletions. No production source change. Adapter supplies typed current `WorkAttemptFence` only to task-owned mutating/rollback calls in rollback and transaction test modules. Read-only commands and production fail-closed behavior remain unchanged.
- `git apply --check` passed on fresh root preimage copies and current root.
- Exact root snapshot copied to `C:\Users\Adam\AppData\Local\Temp\t06-test-fence-adapter-root-snapshot-20261001`; focused command `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_command_rollback.py tests/test_command_transaction_snapshot.py tests/test_t06_project_validation_receipts.py` returned 77 passed, 4 skipped in 97.10 s.
- Four skips: symlink creation privilege unavailable on Windows; three POSIX symlink/identity/pinned-root race tests are platform-gated. POSIX postimage-check/`os.replace` race remains open.
- Skip details from exact-root receipt:
  - `test_rollback_snapshot_rejects_symlink_swapped_before_handle_open`: Windows could not create file symlink (`WinError 1314`, required privilege unavailable).
  - `test_rollback_snapshot_rejects_parent_symlink_swapped_after_resolve`: POSIX root-parent symlink race; skipped on Windows.
  - `test_rollback_restore_rejects_replaced_root_path`: POSIX root identity replacement; skipped on Windows.
  - `test_rollback_restore_stays_inside_pinned_root_if_path_moves_after_check`: POSIX pinned-root restore race; skipped on Windows.
- POSIX postimage-check/replace race has candidate mitigation and T20 integration receipt below. Native Linux/macOS syscall and race proof still required before acceptance.
- No additional T15 edits are authorized in `commands.py`; `_record_command_verification` and persistence symbols/call sites remain outside this write set.

## POSIX rollback TOCTOU candidate — 2026-10-01

- Root cause: `_restore_rollback_scope` checked the current postimage, then used unconditional `os.replace(temp_name, leaf)`. A concurrent writer could replace the leaf after the final fingerprint check and lose its edit.
- TDD: `test_posix_rollback_exchange_restores_concurrent_write_between_check_and_replace` failed before the implementation (`_rename_exchange_at` missing), then passed after fix. The regression injects a concurrent edit at the exchange seam and verifies that rollback restores the concurrent entry and returns an unknown outcome.
- Candidate uses atomic entry exchange (`renameat2(RENAME_EXCHANGE)` on Linux; `renameatx_np(RENAME_SWAP)` on macOS), inspects the displaced entry, reverses exchange when it detects the race, and preserves the displaced entry if safe reversal cannot be proven. Unsupported POSIX exchange fails closed; there is no `os.replace` fallback.
- Targeted post-fix command: `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_command_rollback.py::test_posix_rollback_exchange_restores_concurrent_write_between_check_and_replace tests/test_command_rollback.py::test_rollback_exchange_primitive_swaps_entries_atomically tests/test_command_rollback.py::test_command_rollback_restores_only_declared_write_set tests/test_command_rollback.py::test_command_rollback_preserves_concurrent_edit_to_declared_path tests/test_command_rollback.py::test_patch_rollback_conflict_is_outcome_unknown_and_preserves_foreign_state tests/test_command_rollback.py::test_rollback_aborts_when_hardlink_appears_after_postimage_check tests/test_command_rollback.py::test_rollback_restore_fails_closed_without_captured_postimages` — 6 passed, 1 skipped on Windows. The real POSIX primitive test is platform-gated; Linux/macOS syscall execution remains unverified on this Windows host.
- Candidate patch: `handoff/T06-posix-rollback-atomic-exchange-root-current.patch`; SHA256 `6E74C7DDBFCDFA940CB4959418ADA0E564F1571139B2EF8B24F5060A688BD6D9`; strict `git apply --check` passed on fresh current-root copies.
- Exact write set: `src/local_ai_hub/commands.py` (`_RollbackPostimageChanged`, `_rename_exchange_at`, `_restore_existing_rollback_leaf`, and `_restore_rollback_scope` POSIX restore branch) plus `tests/test_command_rollback.py` (two exchange regressions). Root preimages: commands.py `8A045D05924ACDBD11166D4E19C8CC25C7963A315AD22F05F1784F25D535E537`; rollback test `9E78D2E98B5E95A2772778A4982980FBA3B099EE791FDD62CB2BFED2DD3FD7D3`. Overlay postimages: commands.py `A17C02E1A5C4CED5372D75090758A647898BAC2723D6AD3DF5346344224406E7`; rollback test `9A8F7038F73A699CB22FA8AC361A306BE4C86681D9E500D18A6CB98CB9772269`.
- T20 reports integration after strict root preimage checks. Root focused selectors returned 1 passed, 1 skipped in 0.43 s; skipped real POSIX exchange on Windows. `git diff --check` passed. No rerun by T06.
- Acceptance still requires Linux/macOS execution of the real exchange primitive and race regression. Windows mocked-seam test proves decision logic only, not kernel syscall behavior.

## T06 worktree TDD receipt — 2026-10-01

- Applied same owned race hunk to T06 worktree only. T15 received exact symbol/test ownership boundary; no wait for review and no edits outside this allocation.
- RED command: `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_command_rollback.py::test_posix_rollback_exchange_restores_concurrent_write_between_check_and_replace` — failed before fix because `_rename_exchange_at` was absent.
- GREEN command: `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_command_rollback.py::test_posix_rollback_exchange_restores_concurrent_write_between_check_and_replace tests/test_command_rollback.py::test_rollback_exchange_primitive_swaps_entries_atomically tests/test_command_rollback.py::test_command_rollback_restores_only_declared_write_set tests/test_command_rollback.py::test_command_rollback_preserves_concurrent_edit_to_declared_path tests/test_command_rollback.py::test_patch_rollback_conflict_is_outcome_unknown_and_preserves_foreign_state tests/test_command_rollback.py::test_rollback_aborts_when_hardlink_appears_after_postimage_check tests/test_command_rollback.py::test_rollback_restore_fails_closed_without_captured_postimages` — 6 passed, 1 skipped in 8.36 s. Skip: real POSIX syscall is platform-gated on Windows.
- T06 worktree preimages at this turn start: `commands.py` `CDE99298E82D32C7C6F3663AB89FC5994533665435E227050A1E3AC367430156`; rollback tests `F3F5D06C3AA3C8EC2A23E34E6BA3ABDB658981B4DF6437AA92363EB0C51D0CB6`. Current worktree file hashes after process-test addition: `commands.py` `4873464D94F5310D867BAFA109A2CE9125B7FCF6B2654A77581FB04ACC6C9594`; rollback tests `6AB22F48C8846A2D85208C80B8D007BBE17BEFD3F2BFBA35D1F0818B3F9684C6`.
- Root-current patch remains `handoff/T06-posix-rollback-atomic-exchange-root-current.patch`, SHA256 `6E74C7DDBFCDFA940CB4959418ADA0E564F1571139B2EF8B24F5060A688BD6D9`. T20 has integrated it; do not reapply. Linux/macOS runtime proof remains open.

## Process-race and write-set evidence — 2026-10-01

- Added `test_posix_rollback_exchange_preserves_concurrent_process_edit`; child process writes during the final-check/exchange seam. Added helper `_write_concurrent_rollback_edit` and `multiprocessing` import.
- Current-platform command: `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_command_rollback.py::test_posix_rollback_exchange_preserves_concurrent_process_edit tests/test_command_rollback.py::test_command_rollback_restores_only_declared_write_set tests/test_command_rollback.py::test_command_rollback_preserves_concurrent_edit_to_declared_path tests/test_command_rollback.py::test_rollback_aborts_when_hardlink_appears_after_postimage_check` — 4 passed, 5.41 s. Write-set test proves declared `owned.txt` restores; pre-existing untracked `user-untracked.txt` remains; undeclared private output is not imported.
- WSL availability check found Ubuntu, but Linux test launch failed: `wsl.exe -d Ubuntu --exec python3 -m pytest --version` returned `Catastrophic failure`, `Wsl/Service/E_UNEXPECTED`. No retry. Alternative evidence is the passing Windows child-process schedule test plus Linux kernel-exchange logic test seam. This does not prove real `renameat2`/`renameatx_np` execution.
- Root-current test-only patch for the process test: `handoff/T06-posix-concurrent-process-root-current.patch`; SHA256 `AD00446E8D273C1279A008A27FC7F75EFD3FFDC71E9D5A0882929B2E88438B78`; strict apply-check passed on a fresh current-root copy. Preimage test hash `9A8F7038F73A699CB22FA8AC361A306BE4C86681D9E500D18A6CB98CB9772269`; patch postimage `7AD42A6741AA690114C73D92C5D00C5F53A6AA116892326813A5596D898352A3`.
- Full race acceptance remains open until an actual Linux/macOS run validates the kernel exchange primitive and process race under POSIX dirfd semantics.

## Latest cache integration observation

Read-only root hashes: `cache.py` `D26939199536E018E9A77D7D3761A674D0B3662F9052B37407C3CFBA21798A48`; `commands.py` `3E348A6A955AA72E0ADBCCEAA94DC19ABED75B0F64B60FAAC701B741B81CED9F`; `test_t06_command_cache_read_fail_closed.py` `C3C1B2FBFD3C0A76A0243909683E78B6588F59C1A22488FB4B789E623554103E`. Root `test_cache_invalidation.py` is a differing hash but contains the cross-process atomic-replace regression. T20 is testing current root; do not reapply T06 cache patch.

## Daemon process-group recovery — 2026-10-01

- T06 worktree only: `src/local_ai_hub/commands.py` and `tests/test_daemon_lifecycle_hardening.py`. Registry v3 writes `process_group_id`; v2 live rows remain loadable and derive the group id from the process id because v2 daemons were launched in a new session/process group.
- A dead leader is recoverable only when its recorded identity no longer matches, POSIX `kill(pid, 0)` proves leader absence, the recorded group id equals the original process id, and `killpg(pgid, 0)` independently proves group liveness. Dead group and indeterminate/permission errors fail closed. PID reuse mismatch rejected. Windows group state remains indeterminate and cannot recover an exited leader. Recovered process facade never gains a kill/signal capability.
- GREEN command: `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_daemon_lifecycle_hardening.py::test_daemon_registry_persists_process_group_id tests/test_daemon_lifecycle_hardening.py::test_recovery_accepts_exited_leader_only_when_group_is_verified_alive tests/test_daemon_lifecycle_hardening.py::test_recovery_accepts_live_version_two_registry_row tests/test_daemon_lifecycle_hardening.py::test_recovery_rejects_exited_leader_when_group_is_gone_or_indeterminate tests/test_daemon_lifecycle_hardening.py::test_recovery_rejects_pid_reuse_even_when_group_is_alive tests/test_daemon_lifecycle_hardening.py::test_process_group_liveness_is_tristate tests/test_daemon_lifecycle_hardening.py::test_recovered_daemon_fails_closed_without_live_kernel_handle tests/test_daemon_lifecycle_hardening.py::test_live_posix_daemon_tree_fails_closed_without_stable_group_handle tests/test_daemon_lifecycle_hardening.py::test_recovered_daemon_fails_closed_on_windows_without_job_handle` — 13 passed in 2.23 s on Windows.
- Verification broker was unavailable: repo, command, and coordination requests failed before write; focused native fallback used after that failure. Initial RED exposed missing v3/PGID behavior; two bounded GREEN invocations returned 10 passed and 13 passed. Real POSIX orphan-group syscall remains unverified. WSL attempt already returned `Wsl/Service/E_UNEXPECTED`; no retry.
- Current T06 SHA256: commands.py `E848199664E75A6B499263A94D2E9C92AE005D80FD570C8011DC7F1B85D735FC`; daemon tests `8A3FC31A79309E2EFB2C7138896DB67B4CFDB76774ADA87BE1D92C438BE68256`.
- Root remained read-only. T20 integrated root-current patch `handoff/T06-process-group-recovery-root-current.patch`, SHA256 `D7899FA493C90D1CA8540F11862435105CAA00A941173D5D1C4D86CC8BDFB20A`; strict apply-check passed before integration. Root postimages matched manifest.

## T20 recovered-daemon stop blocker — 2026-10-01

- T20 root suite: 34 passed, 1 failed. Failing selector: `test_live_daemon_is_reconciled_after_broker_restart`; `second.stop_daemon()` fails because recovered process has no stable OS process-tree handle.
- Do not change test expectation per latest user instruction. Current fail-closed stop behavior is intentional: `process_group_id` is a reusable numeric identifier, not a kernel handle. Identity check followed by `terminate_tree(pid)` has a check/use race; POSIX `terminate_tree` signals `killpg(pid, SIGTERM/SIGKILL)`, Windows fallback reacquires via `taskkill /PID /T /F`. Numeric signaling can hit a reused PID/PGID.
- Exact blocker: success after broker restart requires persisted/reacquired stable OS process-tree ownership or a safe handle-based termination protocol. Existing registry identity plus PGID cannot safely satisfy it. No root edits, no contract-test edits. T05 shared pytest slot active; no further test commands until released.
- Green evidence before slot hold: T06 14 focused daemon tests passed in 2.53 s; current T06 test-only clarification makes fail-closed selector explicitly model missing leader identity, but has not been rerun because T05 owns test slot. T20's 34/1 report is the RED evidence.
- Separate outcome-unknown selector diagnosis: `test_repair_loop_stops_after_timed_out_command_outcome_is_unknown` fails before its mocked `run` because its `_broker` fixture registers no task-owned worktree. Actual return is `mutation_worktree_required`; no `outcome_unknown` field is appropriate because the command did not start. Other selected cache/policy/timeout tests: 27 passed. This is test-fixture drift, not the T20 recovered-daemon stop blocker or an outcome-unknown propagation regression. No test expectation changed.

## Handle-reacquisition hypothesis review — 2026-10-01

- Windows helper `process_utils._windows_process_identity` opens `PROCESS_QUERY_LIMITED_INFORMATION`, reads creation time/image via that handle, then closes it. Safe single-process signaling needs a retained `OpenProcess` handle with query+terminate access, comparing persisted creation identity through that same handle before signaling it. Current helper does not expose or retain the handle.
- Windows daemon tree ownership comes from an unnamed kill-on-close Job Object created during spawn and retained only as `Popen._local_ai_job_handle`; registry persists no handle/name. Reopening a leader handle and assigning it to a new Job Object would not capture already-existing descendants. It cannot prove full-tree termination; fail closed for tree stop.
- POSIX `pidfd_open`/`pidfd_send_signal`, if exposed by runtime/kernel, can safely pin and signal one process after identity validation through the pidfd. It cannot address a process group. `process_utils.terminate_tree` signals numeric PGID through `killpg`; pidfd does not close that PGID check/use race. Leader-only pidfd termination can be followed by a group-liveness check, but surviving children keep cleanup unconfirmed. Do not signal numeric PGID after restart.
- Existing code has no pidfd helper. No helper change or test run made. Current process-tree recovery remains fail closed; successful restart-stop acceptance needs persistent/recoverable kernel-owned group/job membership or a separately authorized narrower stop contract.

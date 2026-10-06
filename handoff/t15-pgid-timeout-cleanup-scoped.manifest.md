# T15 POSIX timeout cleanup handoff

## Baseline and ownership

- Worktree: `C:\Users\Adam\.codex\worktrees\fefe\.local-ai-hub`
- Base HEAD: `3ac4d67ec26bcda6e3f55427441fd72258323e27`
- Patch contains `src/local_ai_hub/process_utils.py` T15 timeout cleanup changes and new exclusive test module `tests/test_process_utils_timeout_cleanup.py`.
- T06 owns `commands.py`, `tests/test_command_concurrency_contract.py`, and `tests/test_command_timeout_cache_contract.py`; all excluded from current patch. Timeout/cache file retains only pre-existing T06 dirty diff (4 insertions, 5 deletions). My temporary appended block/import was removed; original dirty hunks preserved. No T06 worktree edits.
- No Docker, WSL, Linux engine, staging, or patch application.

## Artifacts and hashes

- Patch: `handoff/t15-pgid-timeout-cleanup-scoped.patch`
- Patch SHA-256: `6E7290F2F7D730BBE7CCED6C73DFF5B096345EFABCD2FD55AC60A6658ECE500D`
- Manifest: `handoff/t15-pgid-timeout-cleanup-scoped.manifest.md`
- Baseline blob `src/local_ai_hub/process_utils.py`: `d0488b75c3fb5c589d6d79afe362c228c7a69ee5`; scoped target blob: `85aed93acab2bb62e8e755487f6937826ecb0c1c`.
- New test module `tests/test_process_utils_timeout_cleanup.py`; scoped blob: `2eac657124fe90a278a7b355b18c3a0f3dc42619` (no baseline file at HEAD).

`git apply --stat` lists exactly two files: 329 insertions, 81 deletions. Non-mutating `git apply --reverse --check handoff/t15-pgid-timeout-cleanup-scoped.patch` exited 0 for both included paths against the current candidate. Patch remains unapplied. No forward apply or reverse application performed. `git diff --check` exited 0; only existing LF/CRLF normalization warnings appeared.

## Change summary

- POSIX `terminate_tree` refuses numeric PID/PGID signals without continuously held ownership.
- `_terminate_and_drain` avoids POSIX numeric `Popen.kill()`, stream closure, or wait/reap while tree cleanup is unconfirmed.
- Cleanup returns `_CleanupOutcome`. `TimeoutExpired` exposes `cleanup_confirmed`, `cleanup_unconfirmed`, `cleanup_process`, and `cleanup_process_group`; retained `Popen` reference preserves process and pipe state for safe retry.
- Windows `Popen.kill()` fallback remains available through its stable process handle.

## Tests and receipt

T06 read-only review confirmed original POSIX numeric `Popen.kill()` timeout fallback is fixed. Regression was RED before fix: caller invoked `kill()` twice when tree cleanup returned false.

Exact current command:

```powershell
python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_process_utils_timeout_cleanup.py
```

Result: **6 passed in 0.08s** on Windows. All POSIX process operations are mocked. The tests cover `run_hidden` timeout caller, cleanup/drain outcome, and fail-closed signal refusals. They do not establish Linux behavior.

## Runtime blocker and safety boundary

No Linux kernel/runtime available. Docker, WSL, and Linux engine startup prohibited. No real orphan process was created or observed. Real `killpg`, PID/PGID reuse timing, descendant termination, and reaping remain unverified. No continuously held POSIX group signal capability exists in this path.

**Orphan-process termination remains unproven. Fail-closed refusal can leave processes or children running. Acceptance stays open; do not claim no-orphan cleanup PASS.**

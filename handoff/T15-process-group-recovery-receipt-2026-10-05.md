# T15 process-group recovery receipt — 2026-10-05

## Scope and ownership

- Worktree: `C:\Users\Adam\.codex\worktrees\fefe\.local-ai-hub` (registered T15 artifact only).
- HEAD: `17d9f93f9d5eded85eee3a19dc7cb62dc554fd97`.
- Repository revision reported by the command broker: `f9e3dfa0b1cdc7f9e7ec7f909fc394b2a275bfe654c7f4ef8436f99f65fb229f`.
- No source or test file changed during this continuation. Root and foreign worktrees untouched.
- `src/local_ai_hub/commands.py` remains dirty from an existing `+3/-4` hunk in `_snapshot_patch_targets`, owned by T06 rollback work. T15 did not alter it; `commands.py::run` not edited.

## Source and test pins

| Path | HEAD blob | Worktree blob | Worktree SHA-256 | Status |
|---|---|---|---|---|
| `src/local_ai_hub/commands.py` | `a9e927362f21fd3b381c30d771dd0059a124937f` | `5fc5c1144574b74523816c4bba76ec8b751907b2` | `ed97e7220030b4fc181bca02e5281d677e683d6038c5ce6748101a3e37ccea17` | Existing dirty T06 hunk, unchanged before/after this T15 continuation |
| `tests/test_command_concurrency_contract.py` | `421c43a77d1adb404cffe466586f05a8721fab10` | same | `180be8930a40d81cf470fd92b590bc25757414d89c1e67fad28fdad4d36e3be6` | Clean; unchanged |

## Focused receipt

Broker call: `local_ai_command(action="run", cwd="C:\\Users\\Adam\\.codex\\worktrees\\fefe\\.local-ai-hub")`.

```text
python -B -m pytest -q -p no:cacheprovider tests/test_command_concurrency_contract.py -k "recovered_daemon or leaderless" --tb=short
```

- Request: `req_4d254b56b4dd`; execution: `7282e0169f184fc48bf60674e4af7361`.
- Python 3.13.2, Windows; exit 0; `3 passed, 3 skipped, 78 deselected in 0.11s`.
- Skips: three POSIX daemon process-group cases (`POSIX daemon process groups only`, source lines 1991 and 2109); Linux/POSIX leaderless-group persistence is therefore not exercised on this Windows host.

Supplementary focused command was also issued:

```text
python -B -m pytest -q -vv -p no:cacheprovider tests/test_command_concurrency_contract.py -k "daemon or process_group or ownership_token" --tb=short
```

It selected 9 tests and broker reported exit 0. Returned stdout was truncated after two named passing tests; response diagnostics also reported three POSIX-only skips. Do not treat this truncated response as the complete test receipt.

The result file/hash inventory command returned output and exit 0, but the broker disposition was `allowed=false`, `class=unknown`, reason `command not in safe broker allowlist`. Its output matched the hashes above. No validation result relies on that command.

## Review and retrieval failures

- Initial adaptive repository context returned terminal HTTP 503: `task context receipt is missing, stale, or incomplete`, `retryable=false`; response was partial. No retry.
- Repository code-index request remained pending and was terminated; no result. No retry.
- `local_ai_repo(action="search")` rejected unsupported `max_results` with HTTP 400, terminal and non-retryable.
- `local_ai_repo(action="review_diff", paths=[...])` rejected unsupported `paths` with HTTP 400, terminal and non-retryable.
- Corrected packet-scoped `review_diff` request returned failure: `qwen2.5-coder:7b: AttributeError: '_InterruptibleSocketReader' object has no attribute 'peek'; qwen2.5-coder:3b: resource pressure blocks background admission`. No retry. Packet review therefore remains incomplete.
- `local_ai_coord(task_get, task_id="T15")` returned 404 `task not found`; the pre-existing Codex task goal remains the active acceptance record.

## Acceptance status and blockers

- Approved recovery behavior is present in this checkout: persisted `process_group_id`; dead leader accepted only with verified group ownership; otherwise recovered process is treated as exited. T15 continuation made no source change.
- Windows mockable recovery selectors passed. POSIX integration/persistence cases skipped on this Windows host; Linux acceptance remains `NOT VERIFIED`.
- T15 paired performance acceptance remains `NOT RUN`: no clean T06 candidate pin and no T20 GO/slot ID. The previous paired probe remains `acceptance=false` and is not replaced by this receipt.
- No rollback selectors, broad suite, or benchmark ran in this continuation.
- No passing receipt or source presence alone completes overall T15 acceptance.

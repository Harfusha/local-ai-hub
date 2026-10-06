# T16 cross-process write/commit race receipt v1

## Scope and ownership

- Candidate: `C:\Users\Adam\.codex\worktrees\t16-orchestration-recovery\.local-ai-hub`, HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`.
- Root: `C:\Users\Adam\.local-ai-hub`, HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc`; read-only only.
- Added one T16-owned multiprocessing regression in `tests/test_work_fencing.py`; no production source change. It holds writer A inside `commit_guard`, starts expired successor B on another process, verifies B cannot claim until A commits, then checks monotonic attempt/path tokens and successor's final write.
- Lease/fencing guards stay enabled. Existing crash-recovery fixture only disables unrelated background workers in its child process.
- Candidate dirty state retains inherited T16/T21/shared changes. T21 `project_config.py`, T06 `commands.py`, and root were not edited. No stage/commit/reset.

## Exact candidate test evidence

Command:

`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_work_fencing.py`

Final result: `12 passed, 1 skipped in 2.67s`. Skip: directory-symlink privilege `WinError 1314`; junction/reparse tests remain separately covered.

Focused new selector also passed: `1 passed in 1.30s`.

During initial harness diagnosis, first attempt stopped before race because successor signaled readiness after `FencingLeaseStore` initialization, which blocks on writer's SQLite lock. Moved readiness signal before store construction. Final module run above was after that harness correction; no production failure was observed.

## Candidate source pins (SHA-256)

- `src/local_ai_hub/work_fencing.py`: `287DA1CDC5A8CA31EA96CE08D9D3D2EDC641F7BF7DC0F815BC3B2AECCED2F214`
- `tests/test_work_fencing.py`: `1A2F8F34BF07F76ECEF0B303BFCAB0E0B8C96A1AE11D7477DBBBC4BB4C358807`

## Exact root-current T20 patch

Patch: `handoff/T16-root-current-cross-process-commit-race-v1.patch`
SHA-256: `CFCFF000F6FD1C3F1A3434B2B21BD8BB61AC5930A33D1B9AAB82C5BB027A4F66`.

It adds only the race helpers and selector to `tests/test_work_fencing.py` (95 lines; no root production code). Root test preimage SHA-256: `64115A4BC20C6F7375E39AA8C8BAD51AE24D2E1C3EAC28D96DCFEFC3DB88C9B6`; root `work_fencing.py` SHA-256: `C93C22210A479DA74A8ACD19134BAE2BC80979BDDD55E9E5FA08A50042ECBDD0`.

Read-only `git apply --check --whitespace=error` against current root: `PASS`; `git apply --stat`: `1 file changed, 95 insertions`. No root files changed.

T20's previous root fencing/recovery selector remains owner-reported `7 passed / 2.10s`; no duplicate root run in this task. Symlink-specific selector remains `NOT TESTED` due `WinError 1314`; do not mark T16 complete until disposition.

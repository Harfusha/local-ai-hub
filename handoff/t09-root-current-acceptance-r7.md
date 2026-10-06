# T09 root-current acceptance R7 packet — 2026-10-04

## Owner-only delta

- Patch: `handoff/t09-root-current-acceptance-r7.patch`
- Patch SHA-256: `372D44F255F53CEB89341197734424E266BD9478DDDC935F301E8429707A00E6`
- Only path: `tests/test_agent_receipt_completion_t09.py`
- Root preimage SHA-256 / Git blob: `D34BA6EF2B4B8F695368C6025D5BCC0745385F8F6DD4492F8FBE4C482B5A11B1` / `8f5f0438233553e998cc9fa4225fb55f41537d6e`
- Candidate postimage SHA-256 / Git blob: `3018B29468928EC6323E2546EF195DA0DA0B8E5D19AFC61FC569A6C51A8FC7DD` / `2da58753d2f508da37878df42f145fd0a4c0c03b`
- HEAD: candidate and root `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
- Added five T09 tests: cancelled task with valid receipt; search-index rebuild after reopen; durable documentation source-review without command ID; model assessment rejected as test evidence; benchmark receipt requires command ID.

## Root preflight

Exact read-only command:

```powershell
git -C "C:\Users\Adam\.local-ai-hub" apply --check --whitespace=error "C:\Users\Adam\.codex\worktrees\t09-root-current\.local-ai-hub\handoff\t09-root-current-acceptance-r7.patch"
```

Result: **PASS**, exit 0. No root write or test run.

## Acceptance receipts

Candidate full selector on exact postimage: `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_agent_receipt_completion_t09.py` — **20 passed in 5.92s**, exit 0.

Candidate `tests/test_agent_verification.py` previously passed **21 tests**. Detailed commands, intermediate fixture failure, and all pre/post hashes: `handoff/t09-next-test-handoff-20261004.md`.

## Disjointness and ownership

- `agent_verification.py` R6 and structured description/index code are already in root; R7 changes neither production file.
- Root/candidate `agent_tasks.py` differs only by three root `session_id=context.session_id` insertions at lines 426, 457, 535; excluded from R7.
- No path-hint references in T09-owned `agent_tasks.py`, `agent_verification.py`, or receipt tests. `tests/test_project_path_hints.py` has no T09 diff and is released from T09 ownership (candidate SHA-256 `59BEE7875CBF3EF7776C3077993F5F94109031BDF0189DD85ED56A832AD0550F`). Candidate `project_config.py` is inherited dirty T21 content, not T09-owned (candidate/root SHA-256 both `00E80B1342E5E70A66FA8955D95553127E913F56EC693CF527B6AC96053BDBDE`); T09 neither edits nor releases that adapter from this checkout.
- T08 paths (`agent_events.py` and related) and T16 paths (`work_orchestrator.py`, `worktrees.py`, `process_utils.py`, their tests) absent from R7. T08 notified; no acknowledgment yet. T16 confirmed R7 does not touch its orchestration files.
- Local AI Hub lease unavailable by user instruction. Root integration remains unapproved; orchestrator owns any application after lease/owner review and fresh T20 GO.

# T08 release gate classification — 2026-10-05

## Root integration evidence

- Direct full post-integration root T08 owner suite: **143 passed in 36.86s**, parent-reported. This was a direct root run, not the earlier overlay runner; T08 did not rerun it.
- Root targeted integration: **12 passed in 9.20s** across event reliability, both swarm lifecycle selectors, and project-memory audit.
- Identity/delete batch: **24 passed in 36.46s**. T05 migration/context batch: **56 passed in 10.17s**. Async suite: **58 passed in 8.12s**.
- Strict snapshot release check: **GREEN** (parent-reported). Compile/selftest: **GREEN** (parent-reported; commands not supplied).
- Swarm fixture actual root SHA uses CRLF `2fd8794694e255f1544d6056e6e05711e86bcf70d9e7fe433ef51c57040aacd3`; its LF-normalized SHA equals manifest post `0ca80dd24562c3d5cfb9e9e823c77dc607c3e7e57934f2eee4367708cf81e707`.

## Root files from these integration packets

`src/local_ai_hub/agent_events.py`, `src/local_ai_hub/swarm.py`, `tests/test_swarm_orchestrator.py`, `tests/test_project_memory_audit_completion.py`, `src/local_ai_hub/async_jobs.py`, `tests/test_async_jobs.py`.

## Remaining acceptance

No remaining T08 acceptance was reported. No tests were rerun by T08 for this receipt update. HUB remains ignored; no separate Agent OS `verify_completion` tool receipt was produced. Root edits and parent-run validation remain parent-owned.

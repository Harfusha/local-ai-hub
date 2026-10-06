# T08 crash-recovery completion fixture v5 — 2026-10-04

## Diagnosis

Root selector failed before the crash window: test created a task with only `ScopeContext.repository_id`, then attempted to supply server-managed `repo_root` and `worktree.repo_root` through `TaskStore.checkpoint`. Root `TaskStore.create(..., repo_root=...)` owns that field. The candidate already used the creation API for `repo_root`, confirming the root fixture had drifted. The fix preserves the server-managed-field guard.

Root completion also validates test receipts against command evidence. Fixture now stores a tenant-owned command-verification artifact and binds receipt `owner`, `criterion`, `command_id`, `evidence_type`, repository revision, and mutation generation. No production gate changed.

## Candidate verification

Candidate-only command, exit 0: `1 passed in 1.01s`.

```powershell
$env:PYTHONPATH=(Join-Path (Get-Location) 'src'); python -B -m pytest -q -p no:cacheprovider --tb=short -W error::ResourceWarning tests/test_agent_crash_recovery.py::test_committed_task_completion_survives_restart_before_publish
```

Root selector remains unverified after this fix; do not infer root acceptance from the candidate receipt.

## Root-current pins

- Root HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`
- Root test preimage `tests/test_agent_crash_recovery.py`: `210b0c5b3ba41d836dfff5d30cbb5cea2639b4935c1613d294dbdb6ead371d9c`
- Root test expected postimage LF SHA-256: `c3329b8d734d401baf3d759c311d586a371b3f5813062d5751d9de83526e6277`
- Candidate test SHA-256: `c67a8a02e0e0bfe5df5f75dcfed6adadc79e0141969efd8615db43547fd18963`
- Source contract pins: `agent_tasks.py` `6ee041fc54ba05da18ddd542917423216a6010f50bcee2d49a271ee527a77b18`; `agent_verification.py` `2604a542c491aee46ef1d653642247eb615d081d2f97976c105c0fab276ef9d7`; `artifacts.py` `bbdb461575a015a7c64624aba6e90ad8a62b646c1e273714b2c3780d6fe8c7a7`.

## Immutable packet

`handoff/t08-crash-recovery-completion-fixture-root-current-20261004-v5.patch`

SHA-256: `d07538885d3345d4702ca18e2a6b463337deab0a7804708312bdaea3c87ed95d`.

Patch changes only `tests/test_agent_crash_recovery.py`. Root `git apply --check --whitespace=error`: exit 0. Root was not edited or tested.

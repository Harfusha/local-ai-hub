# T06 transaction isolation acceptance v4

Status: candidate in the T06 task worktree. Do not merge into root/master yet.

## T06 changes

- `src/local_ai_hub/commands.py` passes one resolved `coordination_id` to both the path lease and work fencing stores during transaction recovery and normal execution. When only one store supports namespacing, or the project namespace cannot be resolved, the broker fails closed.
- `tests/test_t06_project_namespace_bridge.py` exercises the real HTTP lease route and real `CommandBroker` against linked worktrees. It requires the T16 namespace APIs and skips on the older standalone T06 package.
- `handoff/T06-T09-validation-receipts-v4-root-current.patch` carries the root-current T09 producer change. It derives alias, config digest, and environment identity only from `_ResolvedProjectCommand`; it hashes environment values and does not write them to evidence. It binds receipt admission to the resolved alias and criterion.

## Validation receipts

- T06 selected rollback, recovery, daemon, and generic-lint admission tests: **7 passed, 1 skipped**. `PYTHONPATH` explicitly selected this worktree's `src`. The skip is the namespace test on the older T06 package, which lacks T16's project namespace modules.
- Temporary T06/T16/T21 source overlay: **1 passed**. The test held `owned.txt` through the actual T16 HTTP lease route in one linked worktree; the real T06 broker rejected the overlapping mutation in its linked worktree before execution.
- Root-current receipt patch: **`git apply --check` passed; patched `commands.py` AST parse passed** in a temporary copy. Temporary patched-root producer test: **1 passed**. It ran configured `pyflakes` through `run_project_command`, checked persisted proof alias/config/command/environment digests, and confirmed generic `run(..., criterion="lint")` emitted no source-review receipt.
- `git diff --check` passed for tracked T06 edits. Root `commands.py` was only read; no root files or tests were changed or run.

## External acceptance blockers

- T16 `FencingLeaseStore.acquire` still needs a physical token floor when moving from an existing root-scoped writer token into a project namespace. Current evidence does not establish stale-writer exclusion across that migration.
- T16 recovery restore preflight still needs to reject a non-directory ancestor before restoring any file. A later restore failure can otherwise follow earlier writes.
- T09 must validate the persisted proof against the resolved configured command, permitted arguments, and environment identity. Alias/config digest plus a plausible hash alone cannot prove execution; `--help` can exit successfully without running tests. T06 v4 emits command text, command hash, environment hash, and a combined execution binding, but T09 consumer validation and end-to-end completion remain pending.
- Docker-backed command execution remains unverified. The namespace collision test stops before spawning Docker; daemon and rollback checks do not prove Docker transaction runtime behavior.
- Local AI Hub tools were unavailable in this session. The required `ensure-tools.ps1` file was absent from the installed skill directory. Validation used one bounded native fallback with explicit T06 `PYTHONPATH` and isolated temporary overlays.

## Candidate identity

- Root preimage `src/local_ai_hub/commands.py`: SHA-256 `11887A31E422891DF1B29C7300AAC49B3FB57047343024ADE9493531B3AA2D0B`.
- Patch `T06-T09-validation-receipts-v4-root-current.patch`: SHA-256 `70E3E0DA5831FF702E604788FEA39830099CBB9C1BB5A7F85B54383B5B453DEF`.
- Patched root-current `commands.py` in temporary overlay: SHA-256 `65D4A50E4407CD18B80762F8A3063E319FE4911B86CF113AD6DAE349D57C81B9`.
- Root currently has unrelated dirty changes. Recheck this preimage before applying the patch; do not apply it to a different source state.

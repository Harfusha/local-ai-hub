# T16 project-namespace lease consumer proposal

## Scope

Candidate-only implementation adds the lease consumers for the T21 producer contract. T16 does not reproduce producer identity derivation. `ProjectContext.coordination_id` returns the existing hint-store identity and fails closed when project config has errors.

## Identity and safety contract

- Consume T21 `coordination_id` as lease identity. Do not recompute or hash physical roots in T16.
- Keep `physical_root` as a separate argument. Use it for path normalization, containment, worktree resolution, and actual writes.
- Same coordination ID plus same normalized relative path conflicts across linked worktrees, even when owners/tenants differ.
- Different coordination IDs do not collide when relative path strings match. This covers unrelated Git common directories and local namespace overrides.
- Explicit `coordination_id=None` means project configuration is invalid. Project-scoped lease requests fail closed; they do not fall back to physical-root identity.
- Fencing attempts and path leases share namespace identity for attempt ownership and overlap checks. Attempt and lease records retain physical root. `commit_guard` rejects expired or superseded attempts before write/journal commit.
- Normalize each relative path under the caller's physical root before acquiring a shared-namespace lease. Reject traversal and paths that resolve outside that root.

## Proposed consumer seam

- `ScopeLeaseStore.claim` and `claim_batch` accept an internal `coordination_id`. They retain physical root for normalization and conflict details. `list` can select the same namespace. Omitted IDs preserve legacy callers; explicit `None` fails closed.
- `FencingLeaseStore.claim_attempt` and `acquire` accept the internally resolved ID. SQLite stores separate `scope_id` and physical `resource`; migration backfills old rows to physical scope and same-root claims still see legacy active leases.
- `WorkOrchestrator` resolves the ID from `resolve_project_context` for recovery, rollback, patch writes, and execution attempts. It never accepts a client-supplied ID. Invalid project config blocks fenced work.

## Tests

`tests/test_t16_project_namespace_leases.py` derives IDs through `resolve_project_context(...).coordination_id`. It covers linked-worktree conflict across owners, unrelated Git common directories, local namespace override, invalid-config fail-closed behavior, physical-root containment, fenced write/commit, legacy active lease preservation, and namespace fencing across real subprocesses.

The subprocess case resolves the producer ID independently in each process. It shares one SQLite store across linked worktrees, commits through successor guard, then rejects stale process commit. It does not reproduce T21's identity derivation.

## Candidate receipts

- Before bridge: linked-worktree selector failed with `TypeError: ScopeLeaseStore.claim() got an unexpected keyword argument 'coordination_id'`.
- After bridge: namespace suite passed `8 passed` in 13.14s.
- Candidate acceptance batch passed `63 passed, 1 skipped, 1 deselected` in 41.12s across namespace leases, work fencing, lease deadlock, orchestrator, and handoff acceptance tests. Skip is Windows symlink privilege (`WinError 1314`). The deselected existing real broker selector belongs to T06 overlap.
- Namespaced subprocess selector passed `1 passed` in 1.92s. It used three hidden child-process invocations: initial owner, successor commit, stale commit rejection.
- The real command broker selector was also attempted and fails because this candidate lacks `CommandBroker.set_fencing_lease_store`; T06 broker work is explicitly outside this scope. Do not count this as a namespace pass.
- `git diff --check` passed.
- Root tests and writes remain prohibited by T20 integration gate. T16 candidate receipts do not prove root integration or full acceptance.

## Root-current handoff

`T16-namespace-root-current.patch` targets exact T20 root-current source. `T16-namespace-root-current-patch.md` records predecessor hashes, symbol ownership, patch-check receipt, and root-current broker overlay proof. `root-current-overlay/tests/test_work_handoff_acceptance.py` loads root `commands.py` by asserted module origin and overlay fencing code. Patch remains unapplied until T20 gate releases.

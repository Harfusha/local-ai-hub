# Command Broker Transaction Isolation Plan

## Status

T20 plan accepted. T06 candidate implementation is in progress. On 2026-09-30, prior P0 stash/worktree batches passed 5 and 8 tests; the earlier rollback/cache/policy/daemon batch passed 46 tests. The final post-change six-file suite passed 155 tests with 6 platform skips in 48.15s; the focused regression selectors passed 10 tests with one platform skip. The suite log is `%TEMP%\local-ai-hub-t06-safety-final-20260930.log` (SHA-256 `1922D97F966839BB468F9E064B93A118CBFF45A8B799091BEB458CEEC3FA3AA5`). The earlier full run had four failures; final validation fixed the Windows target-handle revalidation, added the missing-target race test behavior, and corrected test doubles. Full transaction isolation is not complete or verified; broader acceptance and platform-dependent Docker checks remain open.

Final complete six-file command: `python -m pytest -q tests/test_command_rollback.py tests/test_cache_invalidation.py tests/test_command_timeout_cache_contract.py tests/test_auxiliary_action_policy.py tests/test_daemon_lifecycle_hardening.py tests/test_process_utils.py --tb=short -ra` (155 passed, 6 skipped, 48.15s, exit 0). Focused command covering rollback races, receipt opt-out, daemon stop/status, and pruning (10 passed, 1 skipped, exit 0) is in `%TEMP%\local-ai-hub-t06-focused-20260930.log` (SHA-256 `458677FEF7EDEAC4CF1BC22021B556E8179C798730E2A196649055214EEFA400`). `git diff --check` passed; Git reported LF-to-CRLF warnings.

Focused selectors passed in the latest T06 assigned slot: `test_mutating_run_requires_explicit_paths_before_spawn`, `test_mutating_run_rejects_unsafe_write_set_before_spawn`, `test_repair_loop_requires_write_set_before_running_command`, and `test_repair_loop_rejects_patch_outside_write_set_before_writing` (4 passed, 1.72s). Verbatim stdout receipt: `%TEMP%\local-ai-hub-t06-write-set-selectors-20260930.log`, SHA-256 `184A7CE10D98E06D8F6DB453079B6FD5D27449083E6C6917B96F9BC832E963E9`. A broader nine-file run returned 213 passed, 6 skipped, 24 failed in 61.37s. Two repair-loop mutation-replay selectors exposed the missing no-replay guard; T06 added that guard afterward and prepared `test_repair_loop_skips_retry_after_failed_mutating_command`. T06 also prepared `test_repair_loop_does_not_delete_undeclared_bytecode_cache`. Twenty-two remaining failures belong to T07 mutation transport/journal coverage in `tests/test_mutation_replay.py`. The two T07 repair-loop callers also need task-owned fixture and explicit `paths`; T07 owns that file. Broad log: `%TEMP%\local-ai-hub-t06-transaction-safety-20260930.log`, SHA-256 `05B6644D88CCC8FDB9F93CA424A5DDC84DC8DFFFD5801E6564223BC79B7FD11B`. T05 passed focused regressions (3/3) and `test_agent_memory.py` (29/29), then released to T08. T08 received direct user approval for one command-incident `repository_root=cwd` caller field; its 9-selector focused run passed and it released the shared slot to T06. T06's assigned run at HEAD `94337de7309b66c63ff427cce8cd3a49e6414d73` returned 159 passed, 7 skipped, 2 failed in 52.63s (shell timer 53.16s, exit 1). Log: `%TEMP%\local-ai-hub-t06-next-slot-20260930.log`, SHA-256 `AFE79F5FE2D4F1B944B52A4CA6DEE68EDD443A0110FE81730E3195044C85C3CC`. Both failures are `test_private_snapshot_preserves_dirty_ignored_and_untracked_inputs` and `test_private_snapshot_rejects_source_index_change_during_copy`; both stop at `_tree_manifest` with `transaction input changed while opening: .gitignore`. T20 received the exact receipt and T06 released the slot. T05 completed its four memory selectors; T07 then completed its 101-test focused run and released the slot to T06. T04 owns the next shared slot. `tests/test_command_transaction_snapshot.py` defines four unverified broker transaction regressions: private snapshot plus declared import; undeclared-output rejection; concurrent staged-index rejection; and mutation rejection without an enforced Docker boundary. Current code still executes mutations in the source worktree.

Release blockers remain: on 2026-09-30, both `docker info --format '{{.OSType}}'` and `docker image inspect python:3.11-slim --format '{{.Id}}'` failed because `npipe:////./pipe/dockerDesktopLinuxEngine` is unavailable. T09/T16 have not approved the registry and durable-lock recovery contract. Do not claim transaction-isolated execution until those dependencies are resolved and the Windows Docker acceptance run passes.

Current code gap: `CommandBroker.run` still executes declared mutations in the registered source worktree; its Docker option mounts the caller's resolved cwd directly at `/workspace`. It now requires and validates an explicit `paths` write set for mutating classifications. `repair_loop` now requires the same task-owned worktree and write set, rejects generated patch paths outside that set, avoids undeclared bytecode-cache deletion, and skips retry after a failed mutating command. It still writes accepted repairs into the source worktree. New `command_transactions.create_private_transaction_snapshot` is not wired into any broker path and has no pytest evidence. No execution boundary, transaction output enumeration, validated import, durable journal, or crash recovery exists. The registered-worktree gates and rollback write-set do not satisfy that transaction boundary.

Snapshot failure diagnosis: the assigned Windows run exposed that `os.scandir(...).DirEntry.stat()` reports `(st_dev, st_ino) == (0, 0)` here, while handle-backed `os.fstat()` reports the actual file identity. `_tree_manifest` now obtains pre-open metadata with `os.stat(path, follow_symlinks=False)` before retaining its identity/size/mtime comparison. The source fix has since been verified by both affected selectors passing individually; see follow-up receipt below.

After T20's next assigned slot, the index-race selector passed; the snapshot-fidelity selector reached an unrelated test assertion comparing Windows backslashes with Git's forward-slash root. Receipt: 1 passed, 1 failed in 2.85s (shell 3.37s, exit 1), log `%TEMP%\local-ai-hub-t06-snapshot-fix-20260930.log`, SHA-256 `8932FC6D791DC68C790D7AC4A70E1B2CEC83055D33543520566956B94D75ED78`, HEAD `94337de7309b66c63ff427cce8cd3a49e6414d73`. The assertion now compares resolved `Path` values. T06 released the slot after this run; no further T06 snapshot rerun is needed.

### Evidence matrix (2026-09-30)

| Acceptance area | Candidate evidence | Status |
| --- | --- | --- |
| Task-owned gates for `stash_save`, `stash_restore`, and `diff_hunk_stage`; shell-free stash message | 8 focused tests passed; direct broker methods reject paths outside the registered worktree. | Partial: T03 service/MCP task-ID plumbing remains separate. |
| Explicit rollback write set, concurrent-edit preservation, hardlink/reparse-safe restore, and `outcome_unknown` cache invalidation | Final six-file suite: 155 passed, 6 skipped; targeted tests cover final restore-time recheck and atomic no-replace publication when recreating an absent file. | Partial: existing-leaf replacement still has a residual external-writer TOCTOU because portable rename cannot compare-and-swap the leaf; complete isolation/import remains required. |
| Explicit `paths` preflight for mutating `run`, `format`, and `lint_fix` | `run` rejects missing or unsafe paths before spawn; `patch_and_verify` forwards patch-derived paths. Four write-set selectors passed in the latest T06 slot. `repair_loop` rejects undeclared patches and skips retries after failed or outcome-unknown mutations; focused write-set and no-retry safety selectors passed in the T06 candidate (3 passed). | Preflight only; the declared set is not enforced against child outputs. T03 service/MCP task-ID and path plumbing remains separate. T08's incident-provenance hunk remains separate. |
| Daemon policy, launch reauthorization, bounded logs, and cleanup uncertainty | Focused root selectors after T06 follow-up passed (5 passed, 1 Windows skip), covering stop ownership, descendants, restart, service/HTTP task ID, and live POSIX unit behavior. | POSIX process-group integration remains unverified on Linux/macOS; Windows skipped that integration selector. |
| Verification receipt ownership with orchestrator task IDs | `run(..., record_verification=False)` and `patch_and_verify(..., record_verification=False)` suppress CommandBroker receipt persistence while preserving `task_id`; focused regression passed. | T09/T16 caller adoption stays in their owned files; T06 changed only the broker API. |
| Security boundaries, repair loop, network safety, and bundle recovery | The assigned rollback/cache/policy/daemon/process suite passed. | Repair, network, bundle-recovery, and broader acceptance selectors remain unverified. |
| Private input snapshot, sandboxed execution, isolated Git metadata, declared-only import, durable journal, and crash replay | New `command_transactions.create_private_transaction_snapshot` clones private Git metadata and copies tracked, untracked, ignored, and in-root symlink inputs; source and clone manifests are compared. Git index and split-index files receive identity and digest checks before, during, and after copying. Both focused snapshot helper selectors passed individually on Windows (source-index race; dirty, ignored, and untracked input fidelity). `CommandBroker.run` does not call it. | Snapshot helper is tested but unintegrated. No transaction output validation/import, durable journal, child recovery, sandbox enforcement, or task lock/fencing. |
| Windows Docker transaction acceptance | Docker API pipe missing; engine/image inspection failed. | Blocked by Docker Desktop Linux engine availability. |
| Task lock/fencing against expired writers | No approved T09/T16 recovery-lock contract. | Blocked on owner agreement/API. |
| Registered worktree identity | Independent review found `_require_task_worktree` trusted `success` and `worktree_path` without checking live Git identity. T06 now compares registered root, common Git directory, branch, and source `git worktree list`; missing identity metadata fails closed. A second read-only review found no concrete issue. | Candidate fix plus replacement/missing-metadata regressions passed in the latest six-file suite. |

## Preflight result (2026-09-29)

- T09 and T16 confirmed the registry/lease contracts read-only. `TaskStore.get(task_id)` plus `checkpoint.state_data.worktree` is the persisted task association, but not live Git/filesystem validation. Independent T06 review confirmed `_require_task_worktree` checks existence and canonical containment but not Git worktree identity; require live root/common-dir/registered identity comparison before mutating spawn.
- `ScopeLeaseStore` uses SQLite WAL and `BEGIN IMMEDIATE` for cross-process path claims when processes share the same DB. Claims from the same tenant do not conflict; use a unique tenant per concurrent command. TTL is 30–7200 seconds and requires renew/release with the exact lease ID. Lease identity is not bound to task ownership, and there is no fencing token or guarantee that an expired writer stopped. Owners confirm it is advisory and does not itself satisfy stale-writer protection during import/recovery. T09/T16 API edits remain outside T06; obtain an owner-approved fencing/recovery contract before implementation.
- Windows check: Docker CLI exists at `C:\Program Files\Docker\Docker\resources\bin\docker.exe`; `com.docker.service` reports Running. `docker info --format ...` failed because `npipe:////./pipe/dockerDesktopLinuxEngine` is missing. Docker Desktop Linux-container engine and the `python:3.11-slim` image are not confirmed available. The required non-skipped Windows import test cannot run yet.
- Gate: do not start implementation until the Docker Desktop Linux engine is available and T09/T16 approve how T06 prevents a lease-expired writer from importing after ownership has lapsed.

## Goal

Implement the accepted specification in `docs/superpowers/specs/2026-09-29-command-broker-transaction-isolation-design.md`. Mutating broker commands execute in a task-owned isolated transaction, import only declared outputs after validation, and recover safely after interruption.

## Guardrails

- Work only in `C:\Users\Adam\.codex\worktrees\t06-safe-commands\.local-ai-hub`.
- Preserve existing candidate edits and limit source/test edits to T06 transaction paths.
- Do not edit T03-owned `services.py` or `mcp_server.py`, T09/T16-owned task registry or lease APIs, T15 alias/environment symbols or performance hooks, `/api/context/pack`, or the shared root worktree.
- Do not claim OS-wide isolation where a platform sandbox is unavailable; unsupported mutating execution fails closed.
- Implement and review in small phases. Run no tests before plan approval.

## Existing ownership and API boundary

- `CommandBroker._require_task_worktree` in `commands.py` validates through `self.task_store.get(task_id)` and `checkpoint.state_data.worktree.{worktree_path,success}`, then checks canonical cwd containment and Git path overrides. T06 extends this check; it does not create or register tasks.
- The existing durable path lease API is `ScopeLeaseStore.claim(tenant, root, paths, ttl_seconds, purpose)`, with `release` and `renew` in `leases.py`. T06 may consume this API but must not change it or add an in-memory substitute. Hold the write-set lease through import/recovery. Confirm with T09/T16 that this is the approved cross-process ownership contract; any missing task-wide recovery lock is a dependency.
- `TaskStore.create(auto_worktree=True)` in `agent_tasks.py` and its registry/checkpoint shape are not T06-owned. T09/T16 must confirm the required task/worktree registry semantics before an ephemeral-worktree flow is implemented.
- T03 owns `services.py` and `mcp_server.py`. T06 supplies an adapter contract: authorize the original mutating request before task/worktree creation; adapters create/register the task-owned worktree, pass its task ID and write set to `CommandBroker`, and return task ID plus absolute worktree path. The original cwd is never the import destination. T03 implements its adapter in its own scope.

## Phase 1: T06 ownership and write-set contract

1. Keep T06 source edits in `commands.py`: use the existing task-store/registered-worktree validation and reject missing, ambiguous, or unregistered ownership before spawn.
2. Require explicit `paths` for direct mutating `run`; derive patch write sets from validated patch headers; require explicit/derived targets for other mutating actions. Keep read-only calls compatible.
3. Reauthorize the resolved command immediately before spawn. Define transaction ID, import/recovery outcome, conflict, and child termination fields needed by the T03 adapter.
4. Send T03 the adapter contract above; list registry and durable-lock gaps for T09/T16. Do not edit their files in this plan.

## Phase 2: Private transaction snapshot and execution

1. Add transaction creation/cleanup helpers for a private copy of the registered worktree's current input state, including tracked edits, untracked files, ignored files, and required metadata.
2. Snapshot links without following them. Preserve in-root relative links; reject external links, unsupported reparse tags, and declared paths that traverse a link/reparse point.
3. Create transaction-private Git administration and object database. Isolate index, HEAD, refs, reflogs, config, hooks, worktree metadata, lockfiles, and sequencer state; redirect global Git config writes into private state.
4. Use the existing `sandbox="docker"` backend on Windows through Docker Desktop Linux containers. The current backend maps `cwd` to `/workspace` and defaults to `python:3.11-slim`; T06 must map only the transaction directory read/write. Native local execution that cannot enforce the transaction write boundary remains unsupported for mutations.
5. Acquire the existing `ScopeLeaseStore` write-set lease and confirm child-tree termination before deleting transaction state. A gap in durable recovery locking blocks release until T09/T16 provides or approves an API.

## Phase 3: Validated import and crash recovery

1. Enumerate transaction changes and reject outputs outside the declared write set, unsafe path types, or path-policy violations.
2. Implement root-handle-anchored, no-follow destination resolution, file-identity/content preimage checks, temporary sibling writes, and atomic leaf replacement.
3. Persist a durable journal with task/worktree identity, transaction ID, normalized write set, source preimages, validated postimages, and per-path progress.
4. Import only declared additions, modifications, and deletions. Treat destination drift as a conflict; preserve unexpected content.
5. Recover journals at startup and before new task mutations. Make replay idempotent, and retain transaction state if child termination or recovery outcome is unknown.

## Phase 4: T03 adapter contract and focused tests

1. Give T03 the request/response contract for task ID, absolute task worktree path, write set, and transaction result. T03-owned adapter changes are tracked separately and are not T06 paths.
2. Add deterministic T06 tests for write-set enforcement; declared-only import; dirty/untracked/ignored inputs; private Git index/ref/config; same-path lease conflicts; timeout/cancel/crash; journal recovery; destination drift; and symlink/reparse and traversal races.
3. Add a Windows Docker integration test: an explicitly authorized mutation writes a declared output inside the transaction container, the broker imports it into the registered task worktree, and the original cwd remains unchanged. Run on Windows with Docker Desktop Linux containers; skipping because Docker is unavailable is not an acceptance pass.
4. Preserve and extend existing T06 rollback, timeout, and daemon lifecycle tests. Add only T06-scoped fixtures and assertions.
5. Update T06 command docs with guarantees, outcome fields, conflicts, and sandbox limits. T03 updates API docs for adapter behavior in its own scope.

## Phase 5: Review and validation

1. Inspect the scoped diff and verify no T15 symbols or shared-root paths changed.
2. Run focused command-broker tests through the approved command route; inspect exact failure artifacts if any.
3. Run indexed impact/review for changed paths, then one bounded security review focused on path containment, process lifetime, journal recovery, and policy-before-side-effect ordering.
4. Record exact changed paths and validation receipts. Report any platform or acceptance criterion that cannot be proven; do not mark completion from static checks alone.

## Exact checkout and path ownership

- Worktree root: `C:\Users\Adam\.codex\worktrees\t06-safe-commands\.local-ai-hub`
- Base commit: `94337de7309b66c63ff427cce8cd3a49e6414d73`
- Shared root excluded: `C:\Users\Adam\.local-ai-hub`
- Inherited dirty paths to preserve: `src/local_ai_hub/commands.py`, `tests/test_command_rollback.py`, `tests/test_command_timeout_cache_contract.py`, `tests/test_command_unblocked.py`, `tests/test_daemon_lifecycle_hardening.py`.
- T06-owned paths permitted after plan approval: `src/local_ai_hub/commands.py`, focused T06 command tests (including a new transaction test module if needed), T06 command docs, and T06 spec/plan docs.
- T03 handoff paths, not T06 edits: `src/local_ai_hub/services.py`, `src/local_ai_hub/mcp_server.py`.
- T09/T16 dependencies, not T06 edits: `src/local_ai_hub/agent_tasks.py` task/worktree registry and `src/local_ai_hub/leases.py` durable lease API.
- Excluded T15 scope: `run_project_command` alias/environment symbols, T15 performance hooks, and `/api/context/pack`.

Do not alter unrelated dirty files unless they are already within the command transaction contract and necessary; request owner review before any cross-owner scope change.

## Approval gate

This revised plan needs T20 review and T09/T16 confirmation of the registry/lease contract before Phase 1 edits or test execution. The Windows Docker integration run is a release acceptance requirement. After approval, preserve inherited changes and report inherited and T06-owned paths separately.


After normalizing the Git-root assertion, the remaining snapshot-fidelity selector passed: 1 passed in 1.72s (shell 2.35s, exit 0), log `%TEMP%\local-ai-hub-t06-snapshot-path-fix-20260930.log`, SHA-256 `882E4951CA8CBD0CBD4189655587D9FB81C0871D32DE36BE53354065746D1F54`, HEAD `94337de7309b66c63ff427cce8cd3a49e6414d73`. Combined with the earlier assigned source-index race selector passing, both snapshot helper regressions now pass individually. This does not verify broker transaction execution/import; four broker-level transaction selectors remain unverified.


## Resumed T06 work (2026-10-01)

User resumed T06 after the cross-task freeze. At this checkpoint, T06 had updated its owned transaction helper and snapshot tests: `create_private_transaction_snapshot_with_manifest` returned the verified baseline; `validate_transaction_output` returned declared postimages/removals and rejected undeclared tree changes; `verify_transaction_source_unchanged` checked concurrent edits only for declared import targets. Snapshot regressions covered declared nested output, undeclared output, declared removal, changed declared source, and an unrelated concurrent source edit; AST parsing passed. The exclusive pytest slot had not yet been issued at this checkpoint. The transaction implementation and current safety receipt are documented in the later T06 acceptance update. Docker Linux-engine acceptance and the T09/T16 durable lock/fencing contract remain open.

## T06 acceptance update (2026-10-01)

The shared pytest slot was granted to T06 after T20's prior root selector completed. From the task-owned candidate at HEAD `94337de7309b66c63ff427cce8cd3a49e6414d73`, the focused safety batch passed **176 tests with 6 platform skips in 114.42s** (exit 0): `tests/test_command_transaction_snapshot.py`, `tests/test_command_rollback.py`, `tests/test_cache_invalidation.py`, `tests/test_command_timeout_cache_contract.py`, `tests/test_auxiliary_action_policy.py`, `tests/test_daemon_lifecycle_hardening.py`, and `tests/test_process_utils.py`. The skips cover Windows symlink privilege, POSIX race cases/advisory flock, and POSIX daemon process-tree handles.

The current candidate wires mutating broker execution through `_run_private_transaction`, with Docker fail-closed readiness, write-set leasing, source snapshot/revalidation, declared-output validation/import, journaled recovery, and `outcome_unknown` handling. The new snapshot regressions and existing rollback/cache/policy/daemon selectors pass in the batch above. The earlier `tests/test_task_worktree_cleanup_contract.py` receipt remains **21 passed**; it was not rerun in this slot.

Acceptance remains **partial**: a fresh `docker version` probe failed because the Windows Docker Linux-engine named pipe is absent, so the isolated Docker transaction path has no live engine receipt. The T09/T16 durable recovery-lock and fencing contract is still unconfirmed. Do not report end-to-end transaction isolation as verified. Hub context/command calls failed before transport write and bounded status reported `success=false`; the suite therefore ran once natively in the T06 worktree. No test process or command wrote to the root checkout.
## T06/T07 replay-safety integration update (2026-10-01)

Integrated selected T07 replay-safety changes in the task-owned T06 candidate while preserving the existing T06 transaction and rollback hunks. The repair loop keeps definite failed private mutations on the discard path and preserves explicit uncertainty for timeout/cancel/unknown outcomes. Inline Python policy adds only exact `sys.version` and one-shot loopback health-probe exceptions; the loopback read remains uncached and is not marked replay-safe. Four legacy repair tests now create and register linked task worktrees; their fixture setup does not relax the ownership gate. `tests/test_command_rollback.py` was not edited in this update.

Targeted validation passed **45 tests in 26.26s**: the full `tests/test_auto_fix_repair_loop.py` and `tests/test_command_replay_policy.py`, definite-discard and uncertain-rollback cases, two-live-client HTTP retry, and three ambiguous-client transport cases. A narrower classifier/fixture/policy selection passed **25 tests in 7.31s**. `git diff --check` and AST parsing of the two edited Python files passed. An earlier broad exploratory selector included the full `tests/test_mutation_replay.py` and reported failures in unrelated client request-id/response-normalization/maintenance-route cases; these were outside the selected replay-safety selectors and remain unverified here.

Live acceptance remains partial: Docker Desktop Linux engine unavailable (named pipe missing); T09/T16 durable lock/fencing contract unconfirmed. No root checkout writes, commit, or push.

## T16 bounded contract audit handoff (2026-10-01)

A read-only T16 handoff audit (source access unavailable to that auditor; no edits/tests/root writes) reports that current T09/T16 evidence does **not** establish one active writer or reject a stale owner at T06 transaction commit:

- T09 `evaluate_completion_receipts` / `VerificationStore.completion` checks owner-visible artifacts, repository revision, mutation generation, cancellation, receipt freshness, and fail-closed resolver/database errors. Reported T09 candidate receipt: 119 passed / 35.91s; root was not tested. These are completion/freshness receipts, not writer fences.
- T09 `create_git_worktree` reports `worktree_id` and owner/TTL metadata; this establishes creation/ownership metadata, not atomic per-command lease acquisition, monotonic fencing, or stale-owner rejection at commit.
- T16 `work_orchestrator.submit` reportedly uses `BEGIN IMMEDIATE` plus unique `work_id`; `_next` claims queued work with a state predicate and row-count check. This is dispatch/claim CAS. Reported `test_work_handoff_acceptance.py` covers leases/path overlap, replay, bounded wait, restart recovery, CAS/cancel races; it does not prove CommandBroker checks lease/fence ownership before each write/commit. T16 steps execute sequentially; per-mutating-step worktree isolation is not established.
- T06 snapshot/write-set/journal/rollback receipts (handoff reports 139 passed / 5 skipped) still do not establish a verified fence check at transaction start and commit.

Required missing proof: authoritative atomic lease API and token/epoch semantics; broker checks at each mutation and commit; test where owner A expires, B acquires, then A's write/commit is rejected without changing source or journal. Until then, keep single-writer/stale-owner acceptance open; do not equate lease, receipt, or private-snapshot evidence with full worktree isolation.

## T16 command-fence handoff (2026-10-01; API supplied)

T16 has explicit approval to implement a cross-process atomic writer lease with a monotonic fencing token checked at write and commit. T06 remains partial until this API is available and wired; current `ScopeLeaseStore.claim` is advisory and expires by wall clock. T06's private snapshot and preimage check reject a source edit observed before import, but separate `verify_transaction_source_unchanged` and `_restore_rollback_scope` calls leave a check-to-write race. Do not treat the current lease plus preimage check as stale-owner fencing.

### Required T16 API contract

Use the authoritative T16 worktree identity and owner/epoch source. API names may differ; semantics must match:

1. `claim_mutation(worktree_id, task_id, owner_id, root, paths, ttl)` atomically claims normalized write-set paths and returns opaque `token`, monotonic `epoch`, normalized write-set digest, expiry, and current mutation generation. Overlapping scopes conflict; disjoint scopes may proceed concurrently.
2. `renew_mutation(token, expected_epoch, ttl)` extends only the current owner/epoch; expired or superseded tokens fail without revival.
3. `commit_write_set(token, expected_epoch, expected_generation, write_set_digest, apply)` serializes epoch validation and the callback's declared-path write/rollback commit with claims. No check-then-write gap. It returns a receipt with resulting generation and exact committed paths. Recovery imports use same fenced operation.
4. `release_mutation(token, expected_epoch)` releases only the exact current grant. Stale release cannot affect a newer owner.
5. Errors fail closed. Expired/superseded token, generation mismatch, coordinator error, or unknown commit result produces no retryable success; preserve journal and report `recovery_required` / `outcome_unknown` when commit state cannot be proven.

### T06 integration points

- Replace `ScopeLeaseStore` as transaction authority; it may remain an advisory overlap hint only.
- Claim exact registered worktree/task identity and `paths` before snapshot/execution. Renew while command runs.
- Commit in `_run_private_transaction` only through atomic `commit_write_set`; callback rechecks expected source preimages, writes only declared outputs, verifies postimages, and updates/removes journal under the same fence.
- `_recover_transaction_journals` must reacquire a current fence for journal paths and use the same fenced commit/rollback API. Never let stale command owner recover or remove a newer journal.
- On a rejected fence, keep foreign source state unchanged; retain unresolved journal; return terminal, non-retryable failure with explicit uncertainty when needed.

### Required deterministic tests before acceptance

- Broker executes only in private snapshot; declared outputs commit, undeclared outputs never touch source (existing coverage: `test_mutating_run_executes_private_snapshot_and_imports_declared_output`, `test_mutating_run_rejects_undeclared_transaction_output`).
- Disjoint declared paths from two owners both commit; both source outputs preserved (new fake-executor test; included in 5 passed / 9.96s targeted receipt).
- Owner A expires; B obtains higher epoch and commits; A's later write, commit, rollback, and journal removal are all rejected with source/journal unchanged (new stale-preimage test covers only observed source conflict; it does **not** prove token fencing; included in the 5-test receipt).
- Fence/coordinator failure and timeout/cancel/unknown execution fail closed, never claim success; preserve uncertain journal and incident evidence (existing timeout/rollback coverage plus fence-specific failure tests still required).

T16 supplied the exact `FencingLease` / `FencingLeaseStore` signatures in its candidate. T06 broker now accepts the injected store, acquires and renews a per-command lease, holds `commit_guard` across declared-path import/rollback and journal terminalization, records lease ID/token in transaction and recovery journals, and rejects recovery tokens that do not advance beyond recorded epochs. The application composition still needs T16 to inject its authoritative store with `CommandBroker.set_fencing_lease_store`; until then, broker mutations fail closed with `mutation_fence_unavailable`. No guessed API import. No root integration.

The 5-test targeted run completed with **5 passed in 9.96s** just as T02's exclusive test-slot notice arrived. After the exact API message, tests were extended with fake-fence coverage and command hook changes; these edits have **not** been run or validated because T02 owns the test slot. Further validation waits for a free slot.

## T06 continuation checkpoint (2026-10-01)

User approved T16's refined `WorkAttemptFence` transaction design and selected task-owned worktrees for mutating broker commands. T06 owns `commands.py`; T16 owns the authoritative lease store, orchestration, and app wiring. The agreed API includes `claim_attempt`, `renew_attempt`, `release_attempt`, `acquire(..., attempt=...)`, and `commit_guard(lease, actual_paths)`. T06's internal caller keyword is `_work_attempt_fence`; T16 must inject its store with `CommandBroker.set_fencing_lease_store(...)` and pass the active attempt through every mutation entry point. The broker validates task ID and canonical worktree resource, binds path leases to the attempt, records both fences in the journal, and requires a newer same-task attempt for recovery.

Current continuation edits in `commands.py` and regression fixtures are not verified. The five-test run from before this continuation passed, but subsequent attempt-fence integration edits have not been tested. Nested attempt propagation now covers `patch_and_verify`, `repair_loop`, `format`, and `lint_fix`; recovery fixture and stale/disjoint writer cases now model task attempts. Static AST parsing of `commands.py` passed before these latest edits and must be repeated; no test or build has run after the latest edits.

The shared pytest slot was previously held by T02. The latest bounded `local_ai_coord(action="leases")` request failed with `outcome_unknown=true`; do not retry or claim a slot assignment. Continue source-only work; run the authorized narrow rollback/outcome-unknown/cache and policy/daemon safety selectors only after the next slot is explicitly available. No edits were made to app composition, `services.py`, `mcp_server.py`, or the shared root checkout.

T16 interface confirmation (2026-10-01): the concrete type is `local_ai_hub.work_fencing.WorkAttemptFence` and the store API matches the refined contract. `WorkOrchestrator._execute_fenced` currently supplies `writer_fence` and `writer_fence_store_path` in `services.command` arguments. In the T16 candidate, `services.py::command` does not yet forward those fields to `CommandBroker.run`, and `app.py` does not yet inject `FencingLeaseStore` into the broker. These are T03/T16-owned integration hunks; T06 notified T16 and made no edits outside its broker/test ownership. T02 still holds the exclusive pytest slot. `normalize_paths(..., root=...)` canonicalizes symlink/junction ancestors within root; T06 continues passing logical relative write-set paths to lease calls.

T16 candidate wiring rechecked (2026-10-01): `WorkOrchestrator.__init__` injects the same `FencingLeaseStore` through `set_fencing_lease_store`; `_execute_fenced` passes `writer_fence` and current `paths`; `LocalAIServices.command` maps a non-null fence to `_work_attempt_fence`. The service's current `run` branch forwards the explicit `paths` list through `rollback_paths`, so T06 now honors any explicit `rollback_paths` as a write-set fallback, including when rollback-on-failure is disabled. The T06 transaction snapshot fixture now exercises that call shape. Only T06-owned broker/tests/plan changed. T05 owns the shared test slot; no tests have run after the attempt-fence changes.

Latest slot handoff (2026-10-01): T16 candidate source confirms the broker-store injection, `writer_fence` plus changed-path forwarding, and `LocalAIServices.command` translation to `_work_attempt_fence`. The service currently forwards its path list through `rollback_paths`; T06 consumes that field as the declared transaction write set even without rollback-on-failure. T06 notified T16 and T20 with the exact API and candidate revision `94337de7309b66c63ff427cce8cd3a49e6414d73`. The most recent coordination assigns T01 the next exclusive root check slot; T06 candidate tests remain queued until T01 reports and releases. No tests have run after these edits; static AST checks for seven T06 Python files and `git diff --check` pass.

Ruling (2026-10-01): Mutating commands require an existing task-owned worktree; do not create an ephemeral worktree. This follows the user's explicit selection and the current `_require_task_worktree` implementation. The older design sentence permitting ephemeral creation is superseded; the T06-owned spec now states the fail-closed rule. Cost if wrong: standalone mutating calls without registered task context remain unavailable by design.

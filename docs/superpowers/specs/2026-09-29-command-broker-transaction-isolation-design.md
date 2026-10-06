# Command Broker Transaction Isolation

## Status

Architecture approved by the user on 2026-09-29. Revised against T20 review feedback; T06 implementation is active under the linked plan.

## Problem

Mutating broker commands currently run in the registered task worktree. Rollback snapshots and postimage checks reduce damage, but a command can still expose partial writes, affect undeclared paths, or race with another writer. A timeout or broker crash can leave those writes behind. Rechecking a path before rollback does not provide transaction isolation.

## Goal

Run every broker operation that may write files in a private transaction copy of the registered, task-owned worktree. On success, import only its declared write set. On failure, timeout, cancellation, or confirmed child-process termination after broker failure, discard the transaction. Shared and unregistered paths are never eligible for mutation.

The transaction preserves the source worktree's input state, including tracked edits and untracked or ignored files needed by the command. Its Git administrative state is private: command-created index changes, refs, and metadata must not alter the source worktree or another worktree.

## Entry points and write sets

- `run` requires a registered task-owned worktree and an explicit `paths` write set whenever classification says the command may mutate files. Missing or empty write sets fail closed. A read-only command can continue to run without a write set.
- A mutating call without `task_id` may resolve `cwd` only when it maps to exactly one registered task-owned worktree. Zero or ambiguous matches fail closed before filesystem, registry, or process side effects; do not create an ephemeral worktree. Read-only calls without a task ID keep their existing behavior.
- `patch_and_verify` derives the write set from the patch headers, rejects paths outside the registered worktree, applies and verifies the patch inside the transaction, then imports only those paths on success.
- Other file-mutating broker actions, including `repair_loop`, `auto_fix`, and `format`, use the same transaction lifecycle. Their write set is explicit or derived from their declared targets before execution. An action without a complete write set is rejected before spawning a process.
- Staging-only or process-control actions that do not write worktree files are outside this transaction API unless their implementation writes files as a side effect; such side effects must be classified and covered before release.
- MCP/service adapters pass the task ID and write set consistently. Existing `paths` semantics must not silently turn a mutating invocation into an unscoped one.

## Transaction lifecycle

1. Resolve a missing `task_id` only from exactly one registered task-owned worktree matching canonical `cwd`; reject zero or ambiguous matches before any filesystem, registry, or process side effect. Acquire the task worktree mutation lock. Validate task ownership, registry state, canonical root containment, and that every declared path is relative, normalized, unique, and permitted by path policy. Reauthorize the resolved transaction command immediately before spawn.
2. Capture the source preimage for declared paths and construct a private transaction checkout from the registered worktree's current input state. The snapshot includes tracked edits, untracked files, ignored files, and file metadata required by the command. It excludes the source `.git` administration directory and creates private Git administration as described below.
3. Execute the command only in the transaction checkout. Docker, when used, mounts that checkout read/write and does not mount the source worktree.
4. On process success, enumerate transaction changes. Reject import if any changed path is outside the declared write set, any declared path escapes through a symlink/reparse point, or any source preimage no longer matches. Undeclared files remain private and are discarded.
5. Persist a durable import journal containing transaction ID, task/worktree identity, normalized write set, source preimages, validated transaction postimages, and per-path import progress. Resolve destinations relative to an already-open registered-root directory handle, reject reparse points at every component, compare recorded file identity and content, then write a temporary sibling and atomically replace the leaf. Do not validate a string path and later reopen it from the process working directory. Import only declared postimages and removals.
6. Mark the journal committed only after every declared path is imported and verified. Remove the transaction checkout and journal, then release the task lock.
7. On nonzero exit, timeout, cancellation, spawn error, or any validation/import failure, wait for and confirm termination of the full child process tree before discarding the checkout. If termination cannot be confirmed, retain the checkout and journal as recoverable state; do not claim rollback succeeded.

## Snapshot and filesystem boundary

- Snapshot without following symlinks, junctions, or other reparse points. Preserve in-root relative symlinks as links. Reject external-target links, unsupported reparse tags, and any declared path whose traversal crosses a link/reparse point. A declared link path may import the link object itself only after rechecking its in-root target; never follow it during import. Do not silently dereference a link into copied content.
- During execution, enforce a write boundary at the transaction root where the platform/runtime supports filesystem sandboxing. Docker mounts only the transaction root as writable. Native execution must not be described as sandboxed if a child can write outside the transaction through an absolute path or `..`; such commands require an enforced platform sandbox or must fail closed. This boundary protects against command writes; it cannot stop a separate non-cooperating editor from changing the registered source worktree.
- If snapshotting cannot preserve a path's bytes, file type, permissions/attributes needed for execution, or link identity, fail before spawn and leave the source untouched. Do not omit ignored files based on Git status.

## Git metadata isolation

The transaction has its own Git directory and index. The following mutable state must never point back to or be shared with the source worktree: `HEAD`, index, refs and packed refs, reflogs, local config, hooks, worktree registration/admin files, lockfiles, sequencer/rebase/merge state, shallow/replace/graft state, and the object database. Command changes to branch refs, commits, staging, local config, or Git maintenance therefore remain private and are discarded unless represented by declared filesystem outputs.

Git commands run with transaction-local Git environment/config paths. Global Git config writes by the child are redirected to private transaction state; no source or user-level Git configuration is writable through the broker transaction. Read-only config/object reuse is allowed only if the implementation proves the shared target cannot be modified by the child. The first implementation should prefer a self-contained private object database to avoid relying on that proof. No T15 alias/environment symbols are in scope.

## Crash recovery and conflict behavior

- At broker startup and before a new mutation for a task, inspect unfinished transaction journals for that task.
- A crash before import leaves the source untouched; discard the isolated checkout after confirming no child process remains.
- A crash during import is detected from the journal. Recovery compares each destination with its recorded preimage and postimage, then idempotently completes the validated import or restores the recorded preimage. Unexpected content is treated as a conflict and preserved; recovery stops without overwriting it.
- A concurrent Hub mutation is serialized by the task lock. If a non-cooperating editor or process changes a declared destination after the preimage check, the import must detect the mismatch where possible and report a conflict rather than overwrite it. Parent-directory replacement between validation and import must not redirect the atomic replacement outside the registered root.
- The lock cannot force external editors or arbitrary processes to cooperate. The implementation must not claim OS-wide isolation or absolute atomicity across multiple files. The durable journal makes partial import recoverable, while the conflict check limits damage from races.

## Failure contract

Return stable fields `transaction_id`, `transaction_status`, and `failure_kind`. `transaction_status` is `committed`, `discarded`, or `recovery_required`; `failure_kind` is empty on commit and otherwise distinguishes `command_failed`, `timeout`, `cancelled`, `undeclared_output`, `destination_conflict`, `import_failed`, and `child_termination_unconfirmed`. Use `discarded` only after child termination is confirmed and source preimages remain unchanged. Use `recovery_required` when child termination or import completion is uncertain. A command is successful only after all declared outputs are imported and verified. A failed or unknown import must never be reported as rolled back until source preimages are verified.

## Deterministic acceptance tests

- Two simultaneous mutations for one task serialize; independent task worktrees may proceed concurrently.
- A failing command that edits declared files leaves the source byte-for-byte unchanged.
- Successful execution imports declared modifications, additions, and deletions only.
- Undeclared tracked, untracked, ignored, and directory outputs stay in the private checkout and are not imported.
- Timeout and cancellation terminate the full child tree before the transaction is removed; unconfirmed termination retains recovery state.
- Simulated broker crash before import leaves the source unchanged; crash after each per-file import step recovers idempotently or reports a preserved conflict.
- A source destination changed between preimage capture and import is not overwritten.
- Replacing a parent directory or leaf with a symlink, junction, or reparse point between validation and import cannot redirect a write outside the registered root.
- Symlink, junction/reparse-point, traversal, case/normalization, and path-replacement races cannot import outside the registered root.
- Commands that attempt to write through Docker affect only the transaction checkout.
- Mutating calls with an explicit `task_id` reject unregistered worktrees, shared destinations, and missing write sets before process spawn.
- A mutating CLI/MCP call without `task_id` fails closed before filesystem or process side effects. A mutating call requires an existing task ID whose registry entry owns the requested task worktree; do not create an ephemeral worktree. Unregistered, shared, missing, or ambiguous task worktrees fail closed.
- A missing/empty mutating write set is rejected before process spawn, regardless of how task ownership was resolved.
- Git index/ref/config changes remain private, including `git add`, `git commit`, `git branch`, local/global `git config`, and Git maintenance commands.
- Snapshotting preserves dirty, untracked, and ignored inputs. Relative in-root symlinks retain link identity; external symlinks and unsupported reparse points fail before spawn.
- A child attempt to write the original source by absolute path or parent traversal is blocked by the enforced filesystem boundary or rejected as unsupported before execution.
- Existing read-only command behavior and task-worktree ownership checks remain covered.

## Scope boundaries

This work is limited to T06 command transaction isolation, its service/MCP plumbing, recovery state, and focused tests/docs. Do not edit or transfer T15 alias or environment symbols. Do not edit the shared root worktree. Preserve existing candidate changes and unrelated paths. T06 implementation is approved; run tests only in a T20-assigned shared pytest slot.

## Known limits

The journal supports recovery from broker/process crashes, but a multi-file import is not instantaneously atomic to arbitrary external readers. External writers that ignore the task lock can race; preimage checks and conflict preservation reduce risk but cannot eliminate every TOCTOU window without OS-level enforcement. These limits must be documented in returned outcomes and operator-facing docs.

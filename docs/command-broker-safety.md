# Command broker safety

This document describes the T06 command broker contract. A command result is successful only when the requested operation completed and every declared worktree output passed validation.

## Mutating commands

Mutating commands require an existing task ID, a registry entry that owns the requested task worktree, and an explicit write set. The broker rejects missing task ownership, shared worktrees, empty write sets, and paths outside the registered worktree before it starts a process. It does not create an ephemeral worktree. Read-only commands keep their existing path behavior.

The broker creates a private transaction checkout from the registered worktree. The checkout preserves relevant tracked, untracked, ignored, and dirty inputs. Git administrative state stays private. Commands run against the transaction checkout; the source worktree is not mounted into the Docker transaction container.

On success, the broker imports only declared additions, modifications, and removals. It checks for undeclared output, source drift, and unsafe path replacement before import. A durable journal records import progress. The broker reports commit only after it verifies every imported output.

## Failure outcomes

The result includes `transaction_id`, `transaction_status`, and `failure_kind` when transaction handling applies.

| Status | Meaning |
| --- | --- |
| `committed` | All declared outputs imported and verified. |
| `discarded` | Failed transaction discarded after child termination and source preimages were confirmed unchanged. |
| `recovery_required` | Child termination or import state is uncertain, or recovery found a conflict. Preserve transaction journal and investigate before retry. |

`outcome_unknown=true` means the broker cannot prove whether all effects were reversed or imported. `fail_closed=true` and `retryable=false` prevent treating that response as a safe retry. A declared `rollback_paths` set limits rollback; it does not authorize writing other paths. Cache entries for affected paths are invalidated when rollback is uncertain.

Do not claim rollback from a nonzero exit alone. The broker verifies source preimages. It preserves external edits and hardlink aliases when identity or content checks fail.

## Daemons

Daemon commands use structured arguments and pass policy checks before process launch. Daemon records bind process ownership to task identity. Status is observational. Stop reports success only after the process tree is confirmed stopped; unconfirmed cleanup stays visible for retry or recovery. On Windows, the broker uses a Job Object to control descendants, including after the leader exits.

## Limits and acceptance

Task mutation locks serialize cooperating Hub commands. They do not force unrelated editors or processes to cooperate. The broker detects source drift and preserves conflicts where possible; it does not claim operating-system-wide isolation from arbitrary native child writes. The private checkout is not itself a security sandbox. Mutating execution must use an enforced supported boundary or fail closed.

The T06 candidate has focused tests for write-set validation, declared-output import, rollback uncertainty, process-tree cleanup, and daemon ownership. These tests do not prove Windows Docker operation or T09/T16 durable fencing integration. Those require separate integration receipts on the supported host and integrated revision.

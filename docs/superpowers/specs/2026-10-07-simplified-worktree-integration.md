# Simplified Worktree and Integration Process

**Status:** Governing workflow for Local AI Hub development and release integration.
**Purpose:** Stop duplicate work and reduce coordination overhead while preserving every useful change.

## Principles

1. The primary agent works directly in the current `master` checkout by default and owns planning, implementation, review, and integration. Do not delegate audits, create handoff packets, or split one task across chats merely to create activity.
2. Keep one source of truth: the existing master plan/release matrix. Give each work item one stable ID, one concise owner/scope/status/next action, and its actual test command/result. Check the plan and current Git state before starting; update the same item instead of creating a duplicate task or chat.
3. Use a branch or worktree only when isolation is materially needed: independent work that can run in parallel, a real conflict/safety boundary, or an explicit user request. Prefer the fewest possible checkouts. Do not create a worktree per task by default.
4. Preserve all tracked, untracked, and stashed work until it has been inspected and classified. Never use blanket reset/checkout, mass stash, or deletion as a synchronization strategy. Commit coherent unfinished work as a clearly named WIP commit when needed to make synchronization safe; record what remains.

## Integration cadence

- Integrate each completed, bounded unit into the current `master` promptly, before starting dependent work. Keep the number of long-lived branches small; do not wait for a large batch of tasks before integrating.
- Before synchronizing a dirty branch, inspect `git status`, its diff, and its commits. Preserve the overlay; commit it before merge/rebase when safe. Resolve overlaps by understanding both sides, not by choosing one side wholesale.
- After integration, run the narrow relevant tests on the resulting `master`, update the existing plan row with the actual outcome, and make `master` the current base for any necessary remaining work.
- Periodically reconcile all active branches/worktrees against `master`. “Synchronize” means preserve and integrate relevant work, classify unresolved work, and refresh the active base; it does not mean blindly merge every ref.

## Partial integration and archival

- A partial cherry-pick or hunk-level integration is allowed when only part of a source change is relevant. Before archiving its source, inspect the complete remaining diff and commits and record, in the master plan, which changes were integrated and which are deferred, rejected, or still required.
- Archive the source worktree/branch recoverably after that disposition is recorded, so the applied work cannot be reworked accidentally and the unapplied work is not lost. Preserve the original commits/snapshot under an `archived/` branch/ref or the app's recoverable worktree archive. Never drop a stash or delete the only copy as part of archival.
- If deferred work is still required, continue it as a small, explicit item based on current `master`; do not keep developing on a stale source checkout. Create a fresh worktree only if isolation is still necessary.
- Remove an active registration only after checking that its contents, unique commits, dirty files, and stashes have recoverable disposition. Age, detached HEAD, or a branch name is not sufficient evidence that work is disposable.

## Evidence and communication

- Do not create ZIPs, custom handoff bundles, repository-wide fingerprints, per-file hash manifests, or cascades of SHA checks for routine integration. Use ordinary Git status/diff/log/show and the exact test output needed to decide.
- A commit ID is useful to identify a Git revision; a SHA-256 is appropriate only when a concrete integrity/security protocol requires it. Neither replaces tests or source review.
- Report only changed paths, the exact validation command and real result, the commit/ref when relevant, and remaining blockers. Mark a task done only when its own acceptance criteria pass.
- Release readiness is decided from the integrated `master` revision and installed/runtime evidence required by the release checklist—not from branch counts, handoff claims, hashes, or test receipts from another revision.

## Agent and parallel-work rules

- The primary agent performs audits and owns the final implementation/integration directly. Do not create agent chats for audits, inventory, status gathering, or to relay work back to the primary agent.
- Use a subagent only for a genuinely independent, bounded implementation that materially shortens the critical path, or when the user explicitly asks. Its write scope must not overlap another worker. Integrate the result directly after reviewing the diff and running its tests; do not require a ZIP or a custom fingerprint packet.
- Local AI Hub retrieval and command tools remain useful when available. If Hub transport fails, make only the already-bounded attempt allowed by repository instructions, then use direct local tools without retry loops.

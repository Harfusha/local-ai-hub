# Simplified Worktree and Integration Process

**Status:** Permanent governing workflow for Local AI Hub development and release integration.  
**Purpose:** Prevent duplicate work and coordination overhead while preserving all useful changes.

## Core Principles

1. **Direct primary ownership:** The primary agent works directly in the current `master` checkout by default and owns planning, implementation, review, and integration. Do not delegate audits, create handoff packets, or split one task across chats merely to create activity.
2. **Single source of truth:** Keep one source of truth: the project plan / release matrix (`docs/FINAL_COMPLETION_PLAN.md`). Give each work item one stable ID, one concise owner/scope/status/next action, and its actual validation command and result. Check the plan and current Git state before starting; update the existing item instead of creating duplicate tasks.
3. **Minimal isolated checkouts:** Use a branch or worktree only when isolation is materially needed: genuinely independent parallel work, a real conflict/safety boundary, or an explicit user request. Prefer the fewest possible checkouts. Do not create a worktree per task by default.
4. **Preserve unfinished work:** Preserve all tracked, untracked, and stashed work until it has been inspected and classified. Never use blanket reset/checkout, mass stash, or deletion as a synchronization strategy. Commit coherent unfinished work as a clearly named WIP commit when needed to make synchronization safe; record what remains.

## Integration Cadence

- **Prompt bounded integration:** Integrate each completed, bounded unit into the current `master` promptly, before starting dependent work. Keep the number of long-lived branches small; do not wait for a large batch of tasks before integrating.
- **Pre-synchronization inspection:** Before synchronizing a dirty branch, inspect `git status`, its diff, and its commits. Preserve the overlay; commit it before merge/rebase when safe. Resolve overlaps by understanding both sides, not by choosing one side wholesale.
- **Post-integration validation:** After integration, run the narrow relevant tests on the resulting `master`, update the plan item with the actual outcome, and make `master` the current base for any necessary remaining work.
- **Periodic branch reconciliation:** Periodically reconcile all active branches/worktrees against `master`. Synchronize means preserve and integrate relevant work, classify unresolved work, and refresh the active base; it does not mean blindly merging every ref.

## Partial Integration and Archival

- **Hunk-level integration:** A partial cherry-pick or hunk-level integration is allowed when only part of a source change is relevant. Before archiving its source, inspect the complete remaining diff and commits and record in the plan which changes were integrated and which are deferred, rejected, or still required.
- **Recoverable archival:** Archive the source worktree/branch recoverably after that disposition is recorded, so applied work cannot be reworked accidentally and unapplied work is not lost. Preserve original commits/snapshot under an `archived/` branch/ref or the application's recoverable worktree archive. Never drop a stash or delete the only copy as part of archival.
- **Continuation on master:** If deferred work is still required, continue it as a small, explicit item based on current `master`; do not keep developing on a stale source checkout. Create a fresh worktree only if isolation is still necessary.
- **Safe de-registration:** Remove an active worktree registration only after checking that its contents, unique commits, dirty files, and stashes have recoverable disposition. Age, detached HEAD, or a branch name is not sufficient evidence that work is disposable.

## Repository Plan Artifacts

- Durable project plans use stable, project-specific IDs and remain tracked under `.local-ai-hub/plans/`. Never ignore the whole plans directory.
- Validation-only plan IDs use the explicit lowercase prefixes `plan_smoke_` or `plan_ephemeral_`; keep these plans temporary and promote useful requirements/results into the existing durable plan.
- Archive or remove transient plans through the supported project-plan interface after their validation purpose ends. Do not use transient IDs for durable project work.

## Evidence and Communication Standards

- **Standard Git tooling:** Do not create ZIPs, custom handoff bundles, repository-wide fingerprints, per-file hash manifests, or cascades of SHA checks for routine integration. Use ordinary Git status, diff, log, show, and the exact test output needed to decide.
- **Meaningful identifiers:** A commit ID identifies a Git revision; a SHA-256 hash is appropriate only when a concrete integrity or security protocol requires it. Neither replaces actual test execution or source review.
- **Concise reporting:** Report only changed paths, the exact validation command and real result, the commit/ref when relevant, and remaining blockers. Mark a task done only when its own acceptance criteria pass.
- **Release acceptance basis:** Release readiness is decided from the integrated `master` revision and installed/runtime evidence required by the release checklist—not from branch counts, handoff claims, hashes, or test receipts from another revision.

## Agent and Parallel Work Rules

- **Direct audit ownership:** The primary agent performs audits and owns final implementation and integration directly. Do not create agent chats for audits, inventory, status gathering, or to relay work back to the primary agent.
- **Bounded subagent delegation:** Use a subagent only for genuinely independent, bounded implementation that materially shortens the critical path, or when explicitly requested. Its write scope must not overlap another worker. Integrate the result directly after reviewing the diff and running its tests; do not require custom packaging.
- **Local AI Hub tooling:** Local AI Hub retrieval and command tools remain prioritized when available. If Hub transport fails, make only the already-bounded attempt allowed by repository instructions, then use direct local tools without retry loops.

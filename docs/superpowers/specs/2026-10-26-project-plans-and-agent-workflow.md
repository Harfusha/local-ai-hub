# Repository-owned Hub workspace and agent workflow

Status: PROPOSED DESIGN, revision 3, 2026-10-26. No runtime, installer or hook implementation is claimed.

## Operator requirements and current decision

Specifications belong in Git and must be updated when the operator clarifies requirements, or created when no relevant specification exists. Plans have editable names, descriptions, clarifications and tasks, with a project Kanban and a plan filter. Active work, unfinished results and required integration must remain visible across chats.

The latest operator direction replaces the earlier database-owned planner and periodic-export proposal: plans and other repository-specific work artifacts are real files in the selected repository/worktree. Hub creates, validates, edits, saves, indexes and displays those files. Git versions them normally. There is no second canonical plan in Hub's database and no periodic plan export or special backup branch in this design.

This document is a specification, not a live implementation plan. Existing governing instructions remain in force until the replacement is implemented and validated; do not disable current planning prematurely.

## Current source evidence

Source inspected in this checkout on 2026-10-26:

- `agent_board.py` has no project/plan identity in its board schema; `session_briefing(include, root)` does not use `root` when reading the board and tasks.
- `services.py` forwards board mutations separately from Agent OS task transitions.
- `agent_tasks.py` already provides execution contracts, checkpoints and verification. Retain these facilities and usage counters without creating a competing user-plan store.
- `project_config.py` defines `.local-ai.toml` and `.local-ai.worktree.toml`. Preserve their current authority; do not introduce another competing project configuration inside the proposed folder.

These are source observations, not installed-runtime or UI acceptance.

## Repository directory and ownership

Proposed convention, not files created by this specification:

```
.local-ai-hub/
  README.md                    # Short orientation and links to authoritative files
  .gitignore                   # Ignore only local/generated material
  plans/<name>.plan.json       # Canonical named plans, including structured task records
  specs/*.md                   # Default for new specifications when configured
  decisions/*.md               # Rationale and links to adopted specification changes
  knowledge/*.md               # Curated repository facts with sources and validity
  local/                       # Ignored transport/cache material, when needed
```

Existing specifications remain at their existing authoritative paths, including `docs/superpowers/specs/` here. Do not copy or move them merely to populate the new folder. A decision note explains why and links to the actual requirement; it must not become another copy of the specification. The README is orientation, not another manually maintained current-state summary.

Tracked files contain branch-specific, portable project knowledge: plans, adopted requirements, relevant decisions and curated technical facts. Pending private transcripts, credentials, absolute machine paths, session IDs, active leases, heartbeat data, raw logs, indexes, models and tool environments do not belong in tracked plan files. Keep shared live coordination in the configured Hub state store; keep optional per-worktree cache/spool under ignored `local/` with bounded retention. Ignore rules do not remove data already tracked; installation must detect that case instead of promising privacy from a new ignore entry.

Owner-global preferences, credentials, model inventory and installation settings remain Hub-owned. This folder is not a reason to copy all Hub state into every repository. Existing memory adoption retains provenance, scope and freshness; moving a fact into a Markdown file does not make it verified.

Declare the supported artifact types and roots in one project configuration contract. Keep the existing configuration paths until an explicitly designed replacement is shipped. Never maintain silent aliases or two writable configurations.

## Plans as files

Use a versioned, deterministic, human-readable structured format, proposed as one `<name>.plan.json` per plan. The filename is a location, not identity. Each plan has a stable ID, editable title/description, objective, lifecycle, specification references, default integration target and tasks keyed by stable IDs. Task fields include title, description, clarifications, work status, dependencies, scope, acceptance criteria, next action, blocker, source-result references and required delivery targets. Ordering is explicit and must not depend on array position or title.

Renaming a file or title preserves identity. A deliberate clone into an independent plan receives a new ID. Duplicated IDs within the same worktree are an error. Cyclic or missing dependencies are visible validation failures. Archive/cancellation preserves the disposition of unfinished source changes; it cannot silently delete tasks or delivery obligations.

Plan metadata, work status and Git references are versioned. Current activity is a separate Hub overlay bound to the actual execution. A file saying `done` is a declaration, not an authentic verification receipt: completion imported through manual edits or a merge must be checked against current requirements, source and target evidence before being presented as verified delivery.

Kanban is a derived view of these plan files, filtered by project, worktree and custom plan name. Edits in the dashboard and agent tools operate on the same files. External valid file changes are reindexed; cache loss can be repaired by reading the repository. Invalid schemas, duplicate JSON keys, merge conflict markers or unsupported versions are reported without overwriting the file. A last-known-good cached view is explicitly stale and cannot authorize writes or completion.

## Exact repository and worktree binding

Every read/write request binds an authorized physical root. Resolve it using the existing repository/coordination identity and actual Git worktree metadata, including a `.git` pointer file. Do not infer shared authority from a repository URL, directory name, branch name or an untrusted ID stored in a plan.

Default to the current chat's explicitly bound root/worktree. Users may select another authorized registered root in the UI or request. Show project, physical worktree and branch prominently before editing. Never redirect a request to a sibling or primary checkout because it seems newer. An explicit selection must not change another chat's selection.

Use the view identity `(repository coordination ID, worktree identity, plan ID, file revision)`; retain branch/ref and HEAD as execution provenance, not immutable identity. A branch switch, rebase or worktree replacement invalidates previously selected file revisions and requires a fresh read before writes. Detached HEAD and non-Git roots need truthful explicit handling, not a guessed target branch.

## Multiple branches are multiple file versions

Branches A and B may contain different versions of the same logical plan. Hub displays those versions with their worktree/branch context and does not silently combine their statuses into one canonical project plan. A project overview may aggregate registered views while keeping provenance and differences visible. It cannot claim coverage of unknown worktrees or refs.

Independent worktrees may edit the same relative plan path. They do not share a physical-file lock. Hub-mediated edits within one worktree use an exclusive write protocol plus an expected content revision and atomic replacement; stale clients receive a conflict. Verify the root, file confinement and selected Git context again at write time. Durable writes acknowledge the saved file before updating the cache.

Require all managed agent writers to use this protocol. Ordinary manual edits are discovered and validated, but arbitrary simultaneous non-cooperating filesystem writers are outside a cooperative lock's guarantee. Acceptance must exercise the actual supported OS/filesystem write protocol; do not claim a filesystem-wide compare-and-swap merely because a checksum was checked before rename.

Git merges code and plan changes together. Stable task IDs and deterministic formatting reduce unnecessary conflicts. Independent field/task changes may be combined by a validated three-way operation; conflicting requirements/statuses need explicit resolution. Never pick the most advanced status, latest timestamp or one whole side automatically. Structural merge automation is optional for the first version; truthful conflict handling is mandatory.

A task specification reference includes its authoritative path and adopted content/committed revision. A clarification saved on one branch is not automatically present on another. The affected attempt must reconcile its required specification version; unrelated tasks may continue. Record unpublished specification drafts honestly until committed.

## Active work and Agent OS execution

Logical plan/task IDs identify portable work. Agent OS execution/task IDs identify actual attempts and their contracts. Map executions to the file view and logical task without conflating the two. A retry, resumed chat or replaced worktree is not automatically a new user task. If another registered attempt is already doing the same work, show it before allowing accidental reimplementation; an intentional alternative attempt requires explicit scope.

Assignment is not activity. Hub records the actual task/execution owner, session, authorized root, affected paths and renewable lease. An expired lease means stale ownership needing reconciliation, never completion or automatic permission to discard work. Physical checkout writes, logical task ownership and target-branch integration have distinct resource boundaries. Independent branches may work in parallel; the target integrator still reconciles overlapping results.

Agent OS checkpoints that change user-visible progress apply a revision-checked mutation to the bound plan file. They do not separately maintain a canonical board row. Record operation identity and save outcome so a crash after the file save but before acknowledgement can be reconciled without applying the change twice. A failed file write leaves the operation pending; a successful cache update cannot substitute for a saved plan.

Keep lifecycle, work phase, delivery and activity distinct. Verified source work can await integration while no worker is active. A task requiring several delivery targets completes only after each required target is verified or explicitly removed from scope with a reason. Do not create passing receipts from a status field or user assertion.

## Clarifications and automatic agent use

At start/resume/context restoration, load the bound worktree's plan/specification references, pending changes, current attempts and outstanding delivery work. Use bounded summaries and exact recovery references rather than reading every project file into context.

A supported host adapter captures an operator clarification with its actual session/turn identity before dependent implementation proceeds. Preserve the original message in authorized private coordination storage when needed; do not automatically commit whole messages or secrets. Distinguish requirement changes from questions. Update the relevant specification or create one, then patch affected plan/task records. Keep the change pending until both writes are confirmed. Cross-file updates need a durable idempotent intent and recovery path; two renames are not one atomic transaction.

Before new implementation, identify the existing task/result, reconcile affected changes, verify file revisions and acquire actual ownership. At milestones, update the same plan task through Hub. Before final completion, confirm persisted specification/plan changes and required verification/integration. On interruption, save confirmed progress and next action. Explicit pause/cancellation always takes precedence over automatic continuation.

Superpowers integration must require this workflow persistently: specifications in their authoritative Git files, live planning through Hub-managed repository plan files, no independent Markdown plan for the same work, and no completion without required integration. Adapt supported planning/execution extension points; do not silently edit cached upstream skills or leave conflicting active instructions. Installation manages compatible Superpowers when missing and validates the actual host adapter. Synchronize managed instructions and INSTALL/UPDATE prompts when implementation ships.

Host hooks must be tested for mid-turn messages, ordinary prompts, tool edits, interruption and restoration in each supported agent. MCP alone cannot intercept arbitrary native actions. An unsupported host is visibly advisory, not falsely described as enforced. A lost Hub does not erase the plan files, but active ownership cannot be guessed; preserve pending operations and do not silently start a competing writer. Continuation loops must be bounded.

## Saved, committed and delivered are different states

Hub saves the canonical file immediately; no periodic export is needed. The UI separately reports saved/uncommitted, committed locally and remote publication where configured. Saving a file is not a Git commit, and a local commit is not an off-machine backup. Use ordinary bounded commits containing the owned code/specification/plan changes, preserving unrelated dirty state. No automatic push authorization follows from enabling plan management.

Source work records its target delivery obligations before implementation. A completed source contribution remains awaiting integration until the actual change is present and verified in the required target. The integrator merges/resolves the relevant plan changes with the code and records verified delivery in the target's plan. An old source branch may retain its historical plan state; Hub can show confirmed target provenance without rewriting that branch's file behind the owner.

On project activation and before archival, reconcile registered attempts, plan versions, source refs, dirty/untracked files and target results. Every leftover needs an accountable owner, next action or explicit disposition. Preserve useful changes recoverably before removing a worktree. Neither age nor a plan's `done` declaration proves that source work was integrated. The responsible workflow must continue the same task or record why it cannot; an unattended list alone does not solve abandoned work.

Restoring an old Git revision restores that branch's declared plan state. It must not resurrect active leases or automatically replay integrations/pushes. Hub rechecks current ownership and evidence, and marks missing source refs or obsolete delivery claims unresolved. Private execution state has its own existing backup/retention contract; the repository files do not pretend to back up the entire Hub installation.

## Adoption and required acceptance

Do not move existing plans/specifications or discard board records automatically. Inventory and explicitly map selected legacy work into file-backed plans; preserve unresolved records. The new planner is accepted only when file writes, indexing and host behavior work together. User-facing project/plan views and counts must use the same bound scope.

Required scenarios:

- Plans with identical titles in two projects/worktrees remain correctly scoped. Renaming preserves identity; explicit selection never edits a sibling checkout.
- Two worktrees edit different tasks on different branches, commit code and plan changes, then merge. Independent edits survive and genuine conflicts remain visible; no export process touches either checkout.
- A stale UI/agent revision conflicts with another writer. A branch switch between read and save prevents writing stale content onto the new branch. Direct valid edits reindex; malformed/conflicted files are preserved and visibly invalid.
- A mid-turn clarification updates or creates the correct specification and plan, survives a crash between writes, and is recovered by another chat without duplicate application.
- Checkpoints update saved plan files and the Kanban automatically. Activity expires independently; a manual `done` edit cannot manufacture verified delivery.
- Existing source-ready work is found instead of reimplemented, integrated once with the required plan update, or left explicitly blocked under an accountable owner. Archival preserves every remaining change.
- A restored old branch does not revive sessions/leases or replay external effects. Saved, committed, pushed and integrated indicators reflect actual evidence.
- Clean install, compatible/custom Superpowers, missing hooks and unavailable Hub produce truthful distinct behavior. End-to-end host proof is required in addition to source tests.

Technical basis: Git gives linked worktrees separate working trees and indexes while sharing repository data; ordinary tracked files follow their selected branch. Ignore rules apply to untracked material and are not a secret-removal mechanism. See [git-worktree](https://git-scm.com/docs/git-worktree) and [gitignore](https://git-scm.com/docs/gitignore). Application-level scope, locking, recovery and adoption still require implementation and failure tests.

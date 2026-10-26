# Project plans and automatic agent workflow

Status: PROPOSED DESIGN, 2026-10-26. No runtime, installer or hook implementation is claimed.

## Operator requirements and authority

The operator clarified the intended workflow during the design conversation:

- Specifications belong in Git. When a user clarifies requirements, update the relevant specification; create one when none applies.
- Live plans belong in Local AI Hub, not in Git Markdown plans. Each project has a Kanban view with a filter for a custom-named plan.
- Plans and tasks have editable titles, descriptions and clarifications. A task can visibly indicate who is actively working on it.
- Git may contain periodic plan exports for backup. Exports are not another editable live plan.
- Superpowers must be an installer-managed dependency of the agent integration when missing.
- Completed work must reach its authorized integration target, and existing unfinished or unintegrated work must be found before duplicate implementation.

These requirements supersede the earlier proposal to keep live plan checkboxes in Git. This document is a specification, not a live implementation plan. Until the new workflow is implemented and validated, existing governing instructions remain in force; do not disable the current planning mechanism prematurely.

## Current implementation evidence

Source inspected in the current checkout on 2026-10-26:

- `src/local_ai_hub/agent_board.py`: the board schema has no project or plan identity; items have an optional `linked_task_id` and independent status.
- The same file's `session_briefing(include, root)` accepts `root` but does not use it when listing board items or tasks.
- `src/local_ai_hub/services.py` forwards board mutations independently from Agent OS task transitions.
- `src/local_ai_hub/agent_tasks.py` already provides task contracts, checkpoints and completion verification. Reuse these stores and gates rather than introduce a second task engine.

These are source observations, not installed-runtime or UI acceptance.

## One state model per project

The canonical project identity is the resolved repository coordination ID. Authorized roots resolve to this identity. Branches, clones and worktrees remain explicit execution scopes; they must not accidentally create separate project boards or broaden access to other roots.

Hub is authoritative for live planning state and its event history. Git is authoritative for specification text. A plan links to specification paths and revisions. The dashboard, agent briefing and any exported Markdown are views of these records, not independent editable stores.

A plan has a stable ID, project identity, custom title, description, objective, status, owner, specification references, integration target, clarification history, revision and timestamps. Renaming a plan preserves references and tasks. Plan titles are display names, not storage keys.

A task reuses its Agent OS task ID and contract. It belongs to one project and one plan, with title, description, acceptance criteria, clarification history, dependencies, affected paths, execution scope, owner, next action, blocker, verification and integration evidence. Moving it between plans is explicit and audited. Small ad hoc work can use one project Inbox plan instead of requiring a new plan for every request.

Plans and tasks support revision-checked edits by the human and authorized agents. Every change records actor, origin, time and previous revision. A stale edit conflicts instead of silently overwriting another writer. User edits to requirements create changes requiring reconciliation, not silently accepted implementation claims.

## Status and active work

Task progress distinguishes planned, ready, implementation, verification, awaiting integration, blocked, paused, integrated and cancelled work. The implementation must define canonical enum values and their mapping to existing Agent OS states; do not add coercive aliases or pretend these are current APIs.

Activity is separate from progress. Claiming a task records the actual task/execution owner, session, authorized root/worktree, purpose and a renewable expiring lease. A human assignment does not by itself prove active execution. The dashboard shows who is working and when activity was last confirmed.

Only one writer may own overlapping paths. Plan-level work can have several agents on disjoint tasks. Lease renewal and writes are fenced; an expired worker cannot resume writing under its old claim. Expiry marks ownership stale and work needing reconciliation, never complete, discarded or automatically safe to take over.

The Kanban is a projection of canonical task state. Creating, editing or checkpointing a task updates the card automatically. Agents do not maintain a second board item manually. Dashboard filtering is project first, then plan; an installation-wide overview aggregates only authorized projects. Counts, pagination and briefings use the same filters.

## Processing an in-flight clarification

1. A supported host adapter captures the exact user message with project, session and turn/message identity before the next dependent operation. Store a pending change idempotently; identical delivery does not create duplicate changes.
2. The agent distinguishes a requirement change from a question or status request. Preserve the original wording and source. Agent guesses remain proposals; ambiguity remains unresolved rather than becoming an invented operator decision.
3. For a requirement change, update the applicable Git specification, or create a scoped specification when none exists. Record which earlier decision is superseded; do not discard its history.
4. Reconcile the active Hub plan and affected task contracts, dependencies, acceptance criteria and next actions with the specification change. Supersede only evidence invalidated by that change.
5. Acknowledge the pending change only after the specification write and Hub updates are confirmed. A crash between them leaves a recoverable pending operation. Further affected implementation and completion remain gated until reconciliation succeeds.

Git and the Hub database cannot share one transaction. Use durable intents/outbox records and idempotent acknowledgements for cross-store updates. Reconciliation checks actual file/revision state rather than manufacturing success from a checkpoint flag.

Specification updates are authorized workspace writes subject to ownership and path confinement. Unrelated tasks may continue when a change does not affect them. Explicit cancellation or pause always takes precedence over automatic continuation.

## Automatic use by agents

Provide a Hub-owned workflow adapter over existing public tools. Keep public tool count compact; concrete action schemas must be designed against existing coordination APIs rather than invented here.

- On start, resume, fork and context restoration: resolve the project, load its selected plan, active task, pending clarifications, blockers and awaiting-integration work. Return a bounded context with exact recovery references for mandatory omitted detail.
- Before new implementation: locate an existing task/result in the same project, reconcile pending changes, claim the task and affected paths, and verify that the selected specification/plan revisions are current. Similar text alone cannot merge distinct tasks.
- At meaningful milestones: update the same task with actual progress, evidence, blocker and next action. Derive plan progress and the Kanban projection automatically.
- Before completion: enforce task-type-specific evidence, processed clarifications, synchronized specification references, released ownership and required integration disposition.
- On interruption or disconnect: persist the last confirmed state and pending operations. Never infer a successful operation from silence or retry an unknown-outcome mutation blindly.

Host hooks connect these events where supported. Validate receipt of messages submitted during an active turn, not just ordinary new turns. For Codex, assess `UserPromptSubmit`, `PreToolUse`, `Stop`, `Interrupt` and context/session events against the installed host. Other agents need their own tested adapters.

MCP alone cannot intercept arbitrary native edits or messages. A host without working interception must be visibly marked advisory/unsupported for enforcement; it cannot pass automatic-adoption acceptance. Completion continuations must be bounded and stop on genuine blockers, explicit pauses or cancellations. Do not create an endless stop-hook loop.

Hub outages preserve pending work and fail closed for dependent mutations/closure. Provide bounded recovery information; do not silently switch to an independently editable Git plan. A local pending-delivery spool, if needed, is transport state with deduplication, not a second planner.

## Integration and existing abandoned work

For repository-changing tasks, record the authorized target branch and integration owner from the start. Verified source work transitions to awaiting integration; the owner integrates each bounded unit promptly before dependent implementation. Direct work on the target branch still needs the required committed result and current validation.

Completion requires deterministic evidence that the intended change is present in the target and required checks passed there. Handle ordinary merges, squash and selective integration without treating a source commit's mere existence as proof. Respect approval boundaries and existing writer ownership.

When integration cannot proceed, retain the task, source location, concrete blocker, accountable owner and next action. A worker may finish its bounded contribution without closing the parent delivery obligation. Non-code tasks use their own explicit acceptance criteria rather than a universal merge requirement.

At rollout and on project resume, reconcile registered branches/worktrees and known tasks. Classify every leftover as active, awaiting integration, already integrated, deferred, rejected, cancelled or unresolved. Record disposition of every remaining change before recoverable archival. Never delete by age, fabricate acceptance, reset dirty work or copy another owner's implementation.

Stale ownership and awaiting-integration work stay visible in project briefings. Dead-work prevention means a durable continuation/disposition obligation plus actual integration, not merely another forgotten queue.

## Git backups

Support configurable periodic and milestone exports of canonical plan snapshots into a clearly marked backup directory, for example `docs/superpowers/plan-backups/<plan-id>/`. Include schema version, project/plan identity, record revisions, specification references and export time. Serialize a consistent snapshot without credentials or private raw chat transcripts.

Exports are labelled generated and not edited as live plans. Editing an export does not update Hub state. Restore/import is a separate explicit, reviewed operation with identity validation and conflict detection. Never silently replace newer Hub state with an old export.

Creating an export file, committing it and pushing it are distinct authorized operations. Respect the current Git writer and dirty baseline. A failed backup is visible and retryable by operation identity; it does not roll back legitimate live work or falsely report a successful Git backup.

## Installation and instructions

Agent integration installation detects the host, installs missing Superpowers through its supported mechanism, validates a pinned compatible version and installs the Hub adapter. Reuse compatible existing installations. Preserve custom modifications and reject incompatible setup explicitly; never silently overwrite plugin caches or install several competing copies.

Keep runtime-only/headless installation distinguishable from a fully working agent workflow. Installation success for this feature requires an executable capability check of the selected host adapter, Superpowers visibility and Hub project binding.

Put persistent Hub-owned instructions in managed integration files/blocks, not only this chat. The instruction contract must require:

- Update or create Git specifications for requirement clarifications before dependent implementation.
- Create and maintain live plans/tasks in Hub; do not create parallel live Markdown plans.
- Load project state on resume; claim and checkpoint actual work; reuse existing tasks/results.
- Complete delivery only after required integration and recorded disposition of leftovers.
- Treat generated plan exports as backups, not instructions or a source of live authority.

Adapt Superpowers planning/execution at supported extension points so its output uses Hub plans. A competing unmodified instruction to write live Git plans must not remain active. Synchronize the installer, update path, managed agent instructions, `docs/INSTALL_PROMPT.md` and `docs/UPDATE_PROMPT.md` when implementation ships.

## State evolution and rollout boundaries

Use final canonical schemas and explicit versioned records; do not introduce runtime migration shims or runtime ALTER loops. Existing unscoped board records require reviewed project/plan assignment or preserved unresolved disposition. Do not guess identity from a title, label, cwd or current project. Preserve/export existing records before any approved offline conversion or rebuild.

Introduce the workflow in bounded integrated units: canonical project/plan state and task projection; agent clarification and execution adapters; integration/reconciliation gates; installer and export/UI delivery. This ordering is a design dependency, not a second Git implementation checklist. Track actual execution in Hub once its plan model exists.

## Required acceptance scenarios

- Two projects with identically named plans/tasks remain isolated in lists, counts, edits, exports and briefings; renaming or changing worktrees preserves the correct project and stable IDs.
- Human edits and two concurrent agents cannot silently lose updates; disjoint tasks may proceed, overlapping writes and expired claims are fenced.
- A mid-turn clarification updates or creates the Git specification, reconciles the Hub plan and survives restart in another chat. A question does not become an invented requirement.
- A crash between specification write and Hub acknowledgement leaves recoverable pending work. Duplicate event delivery does not duplicate tasks or decisions.
- Creating/checkpointing/completing a task updates the project/plan Kanban without manual board calls. An unresolved specification sync or required integration prevents delivery completion.
- Completed code on another branch is found and integrated once. Conflicts or approvals remain explicit. Old work is archived only after recoverable full disposition.
- Pauses, cancellation, unavailable Hub, missing hooks and stale leases cannot manufacture progress or cause unbounded continuation loops.
- Clean install, compatible existing Superpowers and incompatible/custom installations produce truthful distinct results; actual host events and agent behavior are demonstrated end to end.
- Periodic export produces a consistent Git backup; a dirty checkout, unavailable writer or failed commit cannot be reported as a committed backup. Restore cannot overwrite newer state silently.

Passing source tests alone does not establish host-hook, installed-agent, dashboard, Git integration or backup acceptance. Keep their evidence separate and current.

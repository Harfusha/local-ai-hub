# Repository-owned Hub workspace and agent workflow

Status: IMPLEMENTED IN SOURCE, revision 7, 2026-10-27; integrated acceptance is still pending. Coordination dashboard now reads and edits repository plan files through the same revision-checked operations as agents, filters by repository/worktree and plan, and derives plan progress from that board. It no longer presents the retired global SQLite milestones as project work. The MCP client and HTTP route discard shared `changed_paths` transport metadata for plan operations while retaining strict validation for other fields. Fresh targeted evidence: 214 dashboard tests, 240 plan/Agent OS/host/route tests, 28 planner API/MCP regression tests, compileall, selftest and release-check passed. The full Windows suite reported 44 failures, 12,614 passes and 102 skips; root-cause classification and host/runtime integration remain open. The running Hub is v5.1.0 and its direct `HubClient` plan-list route works, but the connected MCP tool still returns `unexpected argument ... changed_paths`; do not claim MCP plan-operation acceptance until that stale transport path is refreshed and retested. Earlier run #173 evidence is historical, not evidence for this revision. The multi-worktree test proves lifecycle and rejects caller-minted receipts; it does not claim a complete production broker receipt-to-merge acceptance run.

## Operator requirements and current decision

**Checkpoint ordering and recovery:** Agent OS plan synchronization serializes projections across processes and retains durable per-event intents before bound task updates commit. Clearing the task's blockers also clears the plan blocker. Rebinding the same task and session recovers pending intents and refuses conflicting edits. `checkpoint_sync="not_pending"` does not prove the plan and task agree. This does not establish delivery verification.

**Required crash-safe checkpoint protocol:** A bound task update must make its recovery intent durable before the task transaction can commit, without blocking a later checkpoint transaction behind a delayed plan projection. The intent must identify the task, binding, pre-update plan fields and enough task revision identity to distinguish an uncommitted attempt from a committed checkpoint. When before and after task state coincide, revision comparison alone is ambiguous; use the transaction's persisted event identity or fail closed if that evidence is unavailable. Recovery must discard a provably uncommitted intent without changing the plan, replay a committed checkpoint only if the relevant plan fields still equal the captured baseline, and report a conflict if they were edited independently. If the intended projection was already saved before a crash, recovery must recognize it idempotently instead of reporting a false conflict. Concurrent intents must retain their identities, and rebinding must not bypass an unresolved intent. An unavailable or malformed intent must fail closed, and unrelated plan fields must be retained. Implementation has focused process-crash and concurrent-writer coverage; release and live-runtime verification remain separate.

**Dependency progress, 2026-10-27:** Normal setup checks Superpowers for Codex and Gemini CLI when those hosts are on PATH and agent configuration and companion skills are enabled. Codex checks compatible enabled bytes and attempts the supported marketplace plugin when missing; its CLI has no version pin, so unexpected versions or indeterminate outcomes require review. Gemini uses the pinned extension ref and verifies installed files. On `01a073de`, an isolated Gemini CLI 0.65.0 installation reported the extension enabled for user and workspace and a repeat check was a no-op; the user's Gemini host is absent. Plugin installation and enablement do not establish host hook delivery.

**Steering criteria:** MCP `plan_reconcile_steering` must pass explicitly supplied `acceptance_criteria` through validation and to the reconciliation handler. Filtering host-added task metadata on other plan actions must not discard this action's own contract input. Plan task edits carry their criteria within `task_data`.

**Plan creation errors:** Dashboard plan IDs use the repository schema's `plan_` prefix and character rules. The rendered HTML pattern must remain valid under browser Unicode-set validation; invalid plan data returns an actionable HTTP 400, while revision conflicts retain HTTP 409.

**Incomplete board:** A selected or discovered plan that cannot be loaded must not disappear from a successful board response. Report the failure with the affected plan path or identity so agents and operators do not mistake incomplete work for an empty board. A genuinely missing selected plan remains a not-found error.

**Open implementation gap, 2026-10-27:** `RepoPlanWorkspace.edit_task` currently accepts `source_ready` and `done` as direct status edits without authentic execution or integration verification. Checkpoint synchronization also derives `done` from an execution status and the absence of pending deliveries, without independently verifying required delivery targets. These states are declarations, not proof. Do not treat them as completion until the bound execution's receipts and each required target's integration have been verified. The host-native receipt producer remains an independent required capability; an ordinary test result or caller-supplied pass flag is insufficient.

**Async cancellation evidence, 2026-10-27:** Before the cancellation propagation fix, an isolated MCP job remained active for the synthetic backend's roughly 120-second response after cancellation. After `34412f96`, a new isolated job reached terminal `cancelled`; the synthetic backend observed disconnect and terminated its handler about 0.66 seconds later. This demonstrates the synthetic transport path only; it does not prove cancellation or cleanup of a real model. Details and request identities are recorded in `docs/agent-evaluation/results-followup-2026-10-27.md`.

**Native execution accounting gap, 2026-10-27:** In one isolated Agent OS task, a bounded host-native Python command completed but did not create a task budget record. The internal broker accounts for its own executions; no supported producer connecting the native command to that task's budget was established. Do not infer that native commands consume budget or mint verification receipts. The isolated observation is recorded in `docs/agent-evaluation/results-followup-2026-10-27.md`; other paths remain unverified.

The completion design must bind verification to the actual candidate content and each target's integration, not treat `RepoStateTracker`'s cache fingerprint as a byte-level proof: its Git path uses bounded metadata signatures and its degraded paths can be stale or truncated. Plan-file status updates themselves change the worktree state, so the design must distinguish the verified source snapshot from subsequent plan bookkeeping without excluding actual code or specification changes. Any missing, stale, ambiguous or unavailable evidence leaves completion unverified.

Specifications belong in Git and must be updated when the operator clarifies requirements, or created when no relevant specification exists. Plans have editable names, descriptions, clarifications and tasks, with a project Kanban and a plan filter. Active work, unfinished results and required integration must remain visible across chats.

The latest operator direction replaces the earlier database-owned planner and periodic-export proposal: plans and other repository-specific work artifacts are real files in the selected repository/worktree. Hub creates, validates, edits, saves, indexes and displays those files. Git versions them normally. There is no second canonical plan in Hub's database and no periodic plan export or special backup branch in this design.

Project workspace directory settings and persisted project-file targets are canonical relative paths from the resolved repository root. Reject POSIX and Windows absolute or drive-relative paths, empty, `.` and `..` segments, and malformed separators. Resolve and check containment beneath the repository root before creating directories or writing files; symlink or junction traversal outside the root rejects. Do not persist absolute filesystem paths as project-file targets.

The Coordination dashboard uses an explicit repository/worktree root and a plan filter. Kanban cards and plan-progress summaries derive from the selected plan files; mutations use their file revision. The legacy global SQLite milestone panel is not a project-status source and must not offer writes after legacy-board mutation is disabled. Resource semaphores remain an installation-wide coordination surface, not project tasks.

This document is a specification, not a live implementation plan. Existing governing instructions remain in force until the replacement is implemented and validated; do not disable current planning prematurely.

## Initial source evidence (design baseline)

Source inspected in this checkout on 2026-10-26:

- `agent_board.py` has no project/plan identity in its board schema; `session_briefing(include, root)` does not use `root` when reading the board and tasks.
- `services.py` forwards board mutations separately from Agent OS task transitions.
- `agent_tasks.py` already provides execution contracts, checkpoints and verification. Retain these facilities and usage counters without creating a competing user-plan store.
- `project_config.py` defines `.local-ai.toml` and `.local-ai.worktree.toml`. Preserve their current authority; do not introduce another competing project configuration inside the proposed folder.

These are source observations, not installed-runtime or UI acceptance.

## Invariants and first-release boundary

There is one canonical saved plan per file view, one authoritative specification per requirement, and one actual execution identity per attempt. Git versions project declarations; Hub owns live execution/authorization/evidence. Neither side may silently impersonate the other's authority. A cached view, successful file save, user status declaration and verified delivery are four distinct facts.

The first release supports file-backed plans, project/worktree/plan selection, revision-checked edits, live activity, pending requirement changes, task adoption, integration obligations and tested installation. Structured automatic Git conflict resolution, autonomous background source integration, multi-machine synchronization and migration of all historical memory are not prerequisites. Their absence must not weaken truthful conflict reporting, pending-work recovery or completion gates.

Every failure must leave an actionable state: retryable read failure, conflicting revision, pending write/reconciliation, missing artifact, stale owner, unsupported host, blocked integration or required operator decision. Unknown outcomes are never converted into success, repeated mutations or a newly duplicated task.

## Repository directory and ownership

Proposed convention, not files created by this specification:

```
.local-ai-hub/
  README.md                    # Short orientation and links to authoritative files
  .gitignore                   # Ignore only local/generated material
  plans/<plan-id>.plan.json    # Canonical plans; editable custom names are in the files
  specs/*.md                   # Default for new specifications when configured
  decisions/*.md               # Rationale and links to adopted specification changes
  knowledge/*.md               # Curated repository facts with sources and validity
  local/                       # Ignored transport/cache material, when needed
```

Existing specifications remain at their existing authoritative paths, including `docs/superpowers/specs/` here. Do not copy or move them merely to populate the new folder. A decision note explains why and links to the actual requirement; it must not become another copy of the specification. The README is orientation, not another manually maintained current-state summary.

Tracked files contain branch-specific, portable project knowledge: plans, adopted requirements, relevant decisions and curated technical facts. Pending private transcripts, credentials, absolute machine paths, session IDs, active leases, heartbeat data, raw logs, indexes, models and tool environments do not belong in tracked plan files. Keep shared live coordination in the configured Hub state store; keep optional per-worktree cache/spool under ignored `local/` with bounded retention. Ignore rules do not remove data already tracked; installation must detect that case instead of promising privacy from a new ignore entry.

Owner-global preferences, credentials, model inventory and installation settings remain Hub-owned. This folder is not a reason to copy all Hub state into every repository. Existing memory adoption retains provenance, scope and freshness; moving a fact into a Markdown file does not make it verified.

Declare the supported artifact types and roots in one project configuration contract. Keep the existing configuration paths until an explicitly designed replacement is shipped. Never maintain silent aliases or two writable configurations.

## Initialization, configuration and trust

Project initialization binds an explicit authorized root and previews missing managed files before creating them. It creates only the supported structure needed by the selected features, checks effective Git ignore rules and reports whether the intended shared files are actually trackable. It does not populate every repository discovered on disk. A project can retain existing specification paths and start with only `plans/`, a managed ignore entry and orientation links.

Use `.local-ai.toml` as the existing shared configuration authority and `.local-ai.worktree.toml` only for supported local overrides. New workspace settings must be added to that canonical schema rather than accepted as undocumented keys. Choose one configured plan root and one specification-location policy; do not search alternative writable roots after a failure. Existing AGENTS files remain authoritative instruction locations, updated through narrowly owned managed blocks when the feature ships. Load current workspace artifacts through bounded scoped file access before optional semantic indexing; do not wait for preprocessing to discover the current plan. Respect explicit operator exclusions and report incompatible configuration rather than silently bypassing them. Keep local caches and private transport out of project indexing.

Plans and project notes are repository data. They cannot grant command permissions, change the authorized root, claim a writer identity, override host policy, mark an actual receipt as passed or authorize network publication. Validate relative paths and resolve confinement again before each mutation; reject symlink/junction escapes. External references remain explicitly external context, not implicit access permission.

## Plans as files

Use a versioned, deterministic, human-readable structured format, proposed as one `<plan-id>.plan.json` per plan. The filename is a location, not identity. Each plan has a stable ID, editable title/description (including its objective), lifecycle, specification references, default integration target and tasks keyed by stable IDs. Task fields include title, description, clarifications, work status, dependencies, scope, acceptance criteria, next action, blocker, source-result references and required delivery targets. Ordering uses optional integer `order`, with stable task ID as a tie breaker; it must not depend on array position or title.

Renaming a file or title preserves identity. A deliberate clone into an independent plan receives a new ID. Duplicated IDs within the same worktree are an error. Cyclic or missing dependencies are visible validation failures. Archive/cancellation preserves the disposition of unfinished source changes; it cannot silently delete tasks or delivery obligations.

Plan metadata, work status and Git references are versioned. Current activity is a separate Hub overlay bound to the actual execution. A file saying `done` is a declaration, not an authentic verification receipt: completion imported through manual edits or a merge must be checked against current requirements, source and target evidence before being presented as verified delivery.

Kanban is a derived view of these plan files, filtered by project, worktree and custom plan name. Edits in the dashboard and agent tools operate on the same files. External valid file changes are reindexed; cache loss can be repaired by reading the repository. Invalid schemas, duplicate JSON keys, merge conflict markers or unsupported versions are reported without overwriting the file. A last-known-good cached view is explicitly stale and cannot authorize writes or completion.

## File contract v1 and operations

The proposed first contract uses UTF-8 JSON, `schema_version: 1`, opaque stable plan/task IDs, a task map keyed by task ID and deterministic formatting. Titles/descriptions remain display text within explicit size limits. Reject duplicate keys, nonfinite numbers, invalid field types, unsupported enum values and unknown schema versions; never silently coerce a damaged plan to empty defaults. Validation errors identify the file and field while preserving the original bytes. The v1 limits are 1 MiB per file, 1,000 tasks and nesting depth 32; additional field limits are in the [schema](../../../src/local_ai_hub/repo_plan/repo-plan.v1.schema.json). These are explicit design bounds, not a measured performance claim. Do not truncate persisted work to satisfy response budgets.

The [example file](contracts/repo-plan.v1.example.json) matches the inline example below and is a draft illustration, not live project work. The schema follows [JSON Schema 2020-12](https://json-schema.org/draft/2020-12/json-schema-validation). Parse-time duplicate/nonfinite/depth/byte checks, dependency identity/cycles, required specification adoption, full Git-ref syntax, actual path confinement, transition permissions and authentic delivery evidence remain semantic/runtime gates; structural schema validation alone cannot establish them. Field bounds do not imply permission to silently shorten operator requirements.

A minimal draft illustrates the shape, not a currently supported API or an implementation task created by this document:

```json
{
  "schema_version": 1,
  "id": "plan_example",
  "title": "Project workspace",
  "description": "Manage project work through repository files.",
  "lifecycle": "draft",
  "default_target_ref": "refs/heads/master",
  "spec_refs": [],
  "tasks": {
    "task_example": {
      "title": "Implement scoped plan editing",
      "description": "Edit only the selected worktree's canonical file.",
      "kind": "code",
      "work_status": "planned",
      "depends_on": [],
      "clarifications": [],
      "acceptance_criteria": ["A stale file revision returns a conflict."],
      "next_action": "Bind the adopted specification before execution.",
      "blocker": null
    }
  }
}
```

Drafts may be incomplete; beginning affected implementation requires resolved scope, adopted requirements and acceptance criteria. Full records additionally carry relevant specification revisions, dependency references `(plan_id, task_id)`, clarification summaries with supersession links, owned scope, result references and delivery obligations. Do not commit machine-local session/lease identities or raw transcripts. An accepted decision summary links to its specification; it does not replace that requirement text.

Keep plan lifecycle (`draft`, `active`, `paused`, `completed`, `cancelled`, `archived`), task work declarations (`planned`, `ready`, `in_progress`, `blocked`, `source_ready`, `done`, `cancelled`), delivery disposition and live activity as distinct dimensions. These are proposed file enums, not aliases for existing Agent OS enums. Define an explicit adapter mapping and reject ambiguous transitions. A completed plan reopened by changed requirements receives explicit reconciliation; a rename alone does not invalidate work.

Expose bounded list/read/create/edit/task-edit/rename/archive/validate operations through the existing compact tool surface; their final action names must follow current tool schemas. Mutations require the actual root/view, stable record identity, expected file revision and an idempotency key. A file content revision is a concurrency token returned on read, not a timestamp written on every heartbeat. Patch only the intended fields and preserve unrelated tasks. No-op edits do not churn JSON, update times or Git diffs. Renaming a title does not implicitly rename its file.

Return exact scope, saved content revision, operation identity, changed paths and any pending verification/reconciliation. Large details remain bounded and recoverable by reference. Do not return success when only a cache or an intent was written. Removing a file, moving tasks between plans or changing an active execution's scope requires explicit disposition; do not recreate a deleted file from stale cache. Archive is reversible and cannot hide active attempts or unresolved delivery without showing their disposition.

## Exact repository and worktree binding

Every read/write request binds an authorized physical root. Resolve it using the existing repository/coordination identity and actual Git worktree metadata, including a `.git` pointer file. Do not infer shared authority from a repository URL, directory name, branch name or an untrusted ID stored in a plan.

Default to the current chat's explicitly bound root/worktree. Users may select another authorized registered root in the UI or request. Show project, physical worktree and branch prominently before editing. Never redirect a request to a sibling or primary checkout because it seems newer. An explicit selection must not change another chat's selection.

Selecting a branch that is not checked out provides a read-only revision view. Editing requires selecting an existing authorized checkout, or separately authorizing its creation; a dropdown must not silently switch a busy checkout. Project-wide overviews preserve each file view's provenance, support counts/pagination consistently and do not provide an ambiguous project-wide write target.

Use the view identity `(repository coordination ID, worktree identity, plan ID, file revision)`; retain branch/ref and HEAD as execution provenance, not immutable identity. A branch switch, rebase or worktree replacement invalidates previously selected file revisions and requires a fresh read before writes. Detached HEAD and non-Git roots need truthful explicit handling, not a guessed target branch.

## Multiple branches are multiple file versions

Branches A and B may contain different versions of the same logical plan. Hub displays those versions with their worktree/branch context and does not silently combine their statuses into one canonical project plan. A project overview may aggregate registered views while keeping provenance and differences visible. It cannot claim coverage of unknown worktrees or refs.

Resolve dependencies in the selected worktree's plan graph, or through an explicit pinned authorized external contract. A task completed on another branch does not automatically satisfy a dependency here. A bounded or incomplete graph produces unresolved readiness, not proof that no cycle or blocker exists. The overview must not feed another branch's most recent status into execution decisions.

Independent worktrees may edit the same relative plan path. They do not share a physical-file lock. Hub-mediated edits within one worktree use an exclusive write protocol plus an expected content revision and atomic replacement; stale clients receive a conflict. Verify the root, file confinement and selected Git context again at write time. Durable writes acknowledge the saved file before updating the cache.

Require all managed agent writers to use this protocol. Ordinary manual edits are discovered and validated, but arbitrary simultaneous non-cooperating filesystem writers are outside a cooperative lock's guarantee. Acceptance must exercise the actual supported OS/filesystem write protocol; do not claim a filesystem-wide compare-and-swap merely because a checksum was checked before rename.

Git merges code and plan changes together. Stable task IDs and deterministic formatting reduce unnecessary conflicts. Independent field/task changes may be combined by a validated three-way operation; conflicting requirements/statuses need explicit resolution. Never pick the most advanced status, latest timestamp or one whole side automatically. Structural merge automation is optional for the first version; truthful conflict handling is mandatory.

For the first release, ordinary Git conflict resolution followed by schema/semantic validation is sufficient. Until resolved, display the conflicting file as such and do not authorize dependent work from a cached good version. Content from both branches must be preserved for review. A cherry-pick containing code without its plan/specification changes creates a visible synchronization obligation, not a claim that those changes were delivered too.

A task specification reference includes its authoritative path and adopted content/committed revision. A clarification saved on one branch is not automatically present on another. The affected attempt must reconcile its required specification version; unrelated tasks may continue. Record unpublished specification drafts honestly until committed.

## Active work and Agent OS execution

Logical plan/task IDs identify portable work. Agent OS execution/task IDs identify actual attempts and their contracts. Map executions to the file view and logical task without conflating the two. A retry, resumed chat or replaced worktree is not automatically a new user task. If another registered attempt is already doing the same work, show it before allowing accidental reimplementation; an intentional alternative attempt requires explicit scope.

Assignment is not activity. Hub records the actual task/execution owner, session, authorized root, affected paths and renewable lease. An expired lease means stale ownership needing reconciliation, never completion or automatic permission to discard work. Physical checkout writes, logical task ownership and target-branch integration have distinct resource boundaries. Independent branches may work in parallel; the target integrator still reconciles overlapping results.

Agent OS checkpoints that change user-visible progress apply a revision-checked mutation to the bound plan file. They do not separately maintain a canonical board row. Record operation identity and save outcome so a crash after the file save but before acknowledgement can be reconciled without applying the change twice. A failed file write leaves the operation pending; a successful cache update cannot substitute for a saved plan.

Use one mapping from a logical file task/view to its Agent OS execution attempts. Existing task/event transactions, command authorization, receipts, counters and context identity remain authoritative for execution. Do not pretend the SQLite transaction also commits filesystem writes. A checkpoint begins a durable pending file operation and is not acknowledged as fully synchronized until its result is confirmed. Plain file reads remain possible without adopting or launching an execution.

Bind each execution to an explicit contract revision and adopted file/specification revisions. A requirement change must reconcile that execution contract as well as the plan file. Preserve the old contract and receipts as history, invalidate only affected acceptance, and retain one logical user task. If the current backend cannot revise a contract, introduce an explicit superseding technical attempt with recorded lineage and disposition; do not silently mutate old evidence or duplicate the logical work. Support this path before claiming end-to-end clarification handling. Changing or deleting criteria merely to force completion is not reconciliation.

Before execution, criteria must identify their supported verification producer and evidence kind. Text descriptions alone cannot make a receipt-gated contract executable. For native command validation, the authenticated host adapter must persist actual execution provenance/results through the canonical receipt path, bound to the real task owner, authorized root, criterion and candidate revision. Caller-supplied `passed=true`, invented execution IDs and a prose checkpoint are not substitutes for producer records. Documentation/review criteria need a supported authentic inspection/review producer rather than pretend test results. If that bridge is unavailable, report verification pending explicitly; never advertise a fully enforced workflow that can run native checks but cannot close its own tasks.

Keep lifecycle, work phase, delivery and activity distinct. Verified source work can await integration while no worker is active. A task requiring several delivery targets completes only after each required target is verified or explicitly removed from scope with a reason. Do not create passing receipts from a status field or user assertion.

## Durable save and recovery protocol

For a Hub-mediated write: authorize the exact view and lease; read and validate current bytes/context; compare the expected content revision; persist a bounded intent containing operation identity, input revision and intended result identity; write and validate a temporary candidate in the same supported filesystem; recheck ownership/context and publish using the tested exclusive/atomic save protocol; confirm the saved bytes before acknowledging and invalidating projections. Retain recovery material until acknowledgement is durable. Never expose partial JSON as a successful save.

Atomic visibility and power-loss durability are separate capabilities. Test the actual Windows/filesystem path, flush/replace behavior, cancellation and antivirus/file-sharing failures; do not claim universal crash durability from `rename` alone. Cross-store completion always remains a recoverable protocol, not a claimed distributed transaction.

Recovery distinguishes: input still present (operation not applied), intended result present (acknowledge the existing application), a confirmed later managed operation (follow its recorded chain), and unrelated/ambiguous bytes or changed Git context (stop for reconciliation). Never blindly replay a stale patch onto a newer branch. Idempotency records and retention must outlive the documented retry window; a key reused with a different payload rejects.

For specification plus plan changes, persist one intent with both expected revisions and explicit per-file outcomes. A partial save remains visibly pending and blocks only affected implementation. Reconcile forward after checking actual files; never roll back a user's later edit merely to simulate all-or-nothing behavior. Cache/index failures after confirmed saves report that the file is saved but its view is stale, and rebuild without reapplying the mutation.

Use watchers for responsiveness, not authority. Recheck files/context on read-before-write, resume and completion because events can be lost. Git checkout/merge conflicts, manual edits, missing files and unsupported schema versions invalidate relevant cached authority. Missing Hub state permits rebuilding file views; it does not reconstruct active ownership or authentic receipts from JSON declarations. Configured retention bounds pending transport/cache without deleting unresolved work silently.

## Clarifications and automatic agent use

At start/resume/context restoration, load the bound worktree's plan/specification references, pending changes, current attempts and outstanding delivery work. Use bounded summaries and exact recovery references rather than reading every project file into context.

A supported host adapter captures an operator clarification with its actual session/turn identity before dependent implementation proceeds. Preserve the original message in authorized private coordination storage when needed; do not automatically commit whole messages or secrets. Distinguish requirement changes from questions. Update the relevant specification or create one, then patch affected plan/task records. Keep the change pending until both writes are confirmed. Cross-file updates need a durable idempotent intent and recovery path; two renames are not one atomic transaction.

Bind the message to the actual current execution context. If no task is selected or the affected scope is ambiguous, retain an unassigned pending change for explicit resolution rather than modifying an arbitrary recent plan. Capture steering at the earliest event the host actually exposes. An action already accepted by a running tool cannot be retroactively prevented; reconcile its real result and fence subsequent affected changes before continuing. Unsupported in-flight interception remains a declared capability limit, never a promise of instantaneous rollback.

Before new implementation, identify the existing task/result, reconcile affected changes, verify file revisions and acquire actual ownership. At milestones, update the same plan task through Hub. Before final completion, confirm persisted specification/plan changes and required verification/integration. On interruption, save confirmed progress and next action. Explicit pause/cancellation always takes precedence over automatic continuation.

Superpowers integration must require this workflow persistently: specifications in their authoritative Git files, live planning through Hub-managed repository plan files, no independent Markdown plan for the same work, and no completion without required integration. Adapt supported planning/execution extension points; do not silently edit cached upstream skills or leave conflicting active instructions. Installation manages compatible Superpowers when missing and validates the actual host adapter. Synchronize managed instructions and INSTALL/UPDATE prompts when implementation ships.

The managed instructions must state concrete actions: resolve the current root before work; adopt/reuse the existing file task; on a requirement change update/create its specification and reconcile the bound task before dependent edits; checkpoint progress through the same task; commit owned code/specification/plan changes coherently; and close delivery only after target verification. When interrupted, preserve blocker and next action rather than write a new unrelated plan. A question or status request is not automatically a requirement change.

Host hooks must be tested for mid-turn messages, ordinary prompts, tool edits, interruption and restoration in each supported agent. MCP alone cannot intercept arbitrary native actions. An unsupported host is visibly advisory, not falsely described as enforced. A lost Hub does not erase the plan files, but active ownership cannot be guessed; preserve pending operations and do not silently start a competing writer. Continuation loops must be bounded.

Use host-specific capability probes and named support levels: file-management available, instructions integrated, and workflow interception verified. Missing one cannot be masked by success at another. Before enabling interception, persist only the minimum scoped pending message data necessary for reconciliation and preserve existing privacy settings. An adapter that cannot observe in-flight steering must not claim to solve that failure mode.

## Installation, update and rollback

Keep runtime-only installation distinct from agent-workflow setup. For each selected supported host, detect existing Superpowers and its source/version, reuse a compatible installation or install the pinned compatible release when missing, then install the Hub-owned adapter and narrowly managed instructions. Preserve customizations and incompatible installations for explicit resolution. No model pull, duplicate startup process or upstream cache rewrite follows from installing this feature.

Verify project binding, actual skill visibility, hook event delivery, a temporary scoped file operation and continuation/cancellation behavior before activating enforced mode. Installation and updates are idempotent. An incomplete adapter update keeps the last known working integration, or reports workflow setup incomplete; it must not advertise full success because files were copied. Managed blocks need ownership markers and revision checks so updates preserve surrounding user instructions.

Schema evolution is explicit: unsupported versions remain intact/read-only, and an approved offline conversion records its source, backup and result without a silent compatibility shim. Rollback disables the new managed interception, preserves all project files and pending work, and reports which saved schema versions the older runtime can read. Removing an integration never deletes the repository's plans or specifications.

## Saved, committed and delivered are different states

Hub saves the canonical file immediately; no periodic export is needed. The UI separately reports saved/uncommitted, committed locally and remote publication where configured. Saving a file is not a Git commit, and a local commit is not an off-machine backup. Use ordinary bounded commits containing the owned code/specification/plan changes, preserving unrelated dirty state. No automatic push authorization follows from enabling plan management.

Source work records its target delivery obligations before implementation. A completed source contribution remains awaiting integration until the actual change is present and verified in the required target. The integrator merges/resolves the relevant plan changes with the code and records verified delivery in the target's plan. An old source branch may retain its historical plan state; Hub can show confirmed target provenance without rewriting that branch's file behind the owner.

Define one accountable target integrator per delivery obligation. Register that obligation before source work so a lost worker cannot take the only record of it away. Source-ready work must enter that integrator's existing continuation queue before dependent implementation; a missing/inactive integrator surfaces to the operator as blocked ownership, never a fabricated agent. Do not create duplicate chats or implement another copy merely because the original chat ended.

Plan files may declare completion but current verified delivery is a computed result of authentic evidence. Do not embed a commit's own hash or its final-revision receipt inside the same commit. Persisted source/result references may point to already existing commits; final receipts live in the existing verification system and bind the actual resulting revision. If committing the final plan change invalidates a full-revision receipt, run the required check on that final revision. Scope-specific reuse is allowed only where the existing verifier already supports it, never as an invented exemption.

The UI distinguishes declared work status, source verification, target delivery and current activity. Restored historical `done` records remain historical declarations until their relevant claims are checked; they cannot mint a fresh pass. A blocked integration, unsupported host or unavailable receipt remains an explicit limit of the delivery result, not a reason to loop forever or quietly report completion.

On project activation and before archival, reconcile registered attempts, plan versions, source refs, dirty/untracked files and target results. Every leftover needs an accountable owner, next action or explicit disposition. Preserve useful changes recoverably before removing a worktree. Neither age nor a plan's `done` declaration proves that source work was integrated. The responsible workflow must continue the same task or record why it cannot; an unattended list alone does not solve abandoned work.

Restoring an old Git revision restores that branch's declared plan state. It must not resurrect active leases or automatically replay integrations/pushes. Hub rechecks current ownership and evidence, and marks missing source refs or obsolete delivery claims unresolved. Private execution state has its own existing backup/retention contract; the repository files do not pretend to back up the entire Hub installation.

## Complete working example

1. Open authorized worktree A, initialize only missing supported files, select a custom-named plan and bind the relevant existing specification. Resolve a pre-existing logical task before creating a new one.
2. Adopt task T1 into a real execution and claim its actual checkout paths. Worktree B may adopt independent T2, even with overlapping relative paths, while both views retain their source/target provenance.
3. During T1, the operator changes a requirement. Capture it as pending, update/create the specification in A, update T1 with the adopted change and clear the pending operation only after both file outcomes are confirmed. Do not change T2 if it is unaffected.
4. If the process dies between those saves, the next session loads the same task and intent, inspects the actual file revisions and completes reconciliation without a second task or a blind retry. An explicit pause remains respected.
5. Check the bounded source unit, save T1 as source-ready, commit the owned code/specification/plan changes and register the actual result in its execution record. Git save/commit/push indicators remain separate. T1's target obligation stays open.
6. The named integrator takes that obligation, integrates code and relevant project files, resolves any genuine plan conflict and checks the resulting target revision. Record completion declarations and obtain required final authentic verification without a self-referential receipt.
7. Inspect the entire source remainder, preserve deferred/dirty/untracked changes, record their disposition and recoverably archive only what is actually safe. T2 and its unrelated worktree remain untouched.
8. Another chat or clone reads the committed project files and can continue the logical work. It neither assumes that historical activity is live nor replays already completed integrations from an old intent.

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

Each scenario needs identified candidate bytes, actual command/host events, observed file/Git outcomes and explicit expected scope. Add failure injection before/after intent persistence, candidate publication, acknowledgement and each specification/plan save. Exercise duplicate requests with different payloads, dropped watcher events, expired fencing, process restart, disk-full/sharing failures, deleted/renamed plans, schema upgrades/rollback and a missing integrator. Assert preservation and truthful pending states, not just a successful handler response.

Specifically exercise a requirement that changes acceptance criteria mid-execution: the same logical task adopts a new contract revision or a linked superseding attempt, old evidence is retained with truthful applicability, and a real host-native validation produces an accepted receipt that can close the current contract. Repeat with an inspection/documentation criterion. A stale original contract or a successful native command without accepted provenance must remain visible, not leave an apparently finished task silently planned forever.

Shipping requires the complete working example on the installed supported host with two real worktrees, a real in-flight clarification, session restart, actual source/plan commits, target integration and recoverable archival. Focused source tests, synthetic events, mocked Git results and a generated screenshot are useful isolated evidence but cannot substitute for that run. Completion verification must use actual producer receipts and final candidate provenance, never invented PASS metadata.

Technical basis: Git gives linked worktrees separate working trees and indexes while sharing repository data; ordinary tracked files follow their selected branch. Ignore rules apply to untracked material and are not a secret-removal mechanism. See [git-worktree](https://git-scm.com/docs/git-worktree) and [gitignore](https://git-scm.com/docs/gitignore). Application-level scope, locking, recovery and adoption still require implementation and failure tests.

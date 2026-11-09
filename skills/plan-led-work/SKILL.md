---
name: plan-led-work
description: >-
  Use for substantial multi-step implementation, investigation, refactoring, or
  integration work. Create specifications through Superpowers and track tasks,
  completed work, and blockers in Local AI Hub plans.
---

# Plan-led work

Keep the approved specification and the live Hub plan aligned throughout work.

## Intake and traceability

- For substantial or continuing work, keep one Hub plan as the source of truth. Reuse the matching active plan; do not create a duplicate.
- Convert every accepted user request, clarification, and decision into a plan task, acceptance criterion, or recorded scope decision before acting on it. Link each requirement to the task that will satisfy it.
- Track unresolved questions and deferred or out-of-scope items explicitly, with their owner or revisit condition. Do not let them disappear inside chat history.
- Preserve user wording where it changes meaning, constraints, priorities, or acceptance. Do not silently replace a clarification with an agent interpretation.

## Before implementation

1. For new or changed behavior, use the applicable Superpowers brainstorming and specification workflow. Resolve meaningful open requirements before implementation; save the approved specification in the repository's established spec location.
2. Use Local AI Hub plan actions or its project-plan interface. List plans first. Update a matching active plan; create one only when none fits. Never edit Hub plan storage directly.
3. Turn the specification and acceptance criteria into small plan tasks with clear owners, dependencies, and next actions. The Hub plan is the canonical checklist.
4. For substantial execution, create or reuse the Hub Agent OS task contract and bind it to its plan task with `plan_bind_task` when that action is exposed. Keep task checkpoints consistent with the project plan.

## Use the Hub workflow

- Start with `plan_list`, then read the matching plan with `plan_get` and its task board with `plan_board_view`. Reuse the matching plan and task; do not infer status from chat history.
- First inspect the active MCP schema. Call named operations below only when exposed. If an operation is absent, use the Hub's supported project-plan interface; if that is unavailable, record the exact blocker and stop dependent edits. Never bypass the Hub by editing plan storage directly.
- When a user changes scope, decisions, or acceptance, reconcile that steering with `plan_reconcile_steering` before dependent edits when exposed. Supply the current `expected_revision`; when changing a spec, also supply its current `expected_spec_revision`, `spec_rel_path`, and approved `spec_content`. Include a stable `steering_id`, concise summary, and revised `acceptance_criteria`. Resolve revision conflicts against the latest plan/spec; never overwrite them blindly.
- If a clarification changes only task detail, update the existing task with `plan_task_edit` and the current plan revision. Do not create a second task for the same requirement.
- Bind execution to the corresponding plan task with `plan_bind_task` when exposed, using the actual task, plan, plan-task, repository root, session ID, and current plan revision.
- Send progress through `task_checkpoint` when exposed, with the canonical nested checkpoint fields. Bound tasks sync phase, next action, status, and blockers into the plan. Inspect `checkpoint_sync`; `not_pending` alone does not prove the plan and task agree. If sync reports a pending recovery, reread the plan and rebind the same task and session. Do not replay the checkpoint mutation or overwrite conflicting plan edits.
- On resume, use `session_briefing`, task lookup, and the current `plan_get`/`plan_board_view` actions available in the active schema. Reuse the latest accepted checkpoint and evidence. Recheck only changed or invalidated items.
- Before completion, satisfy each acceptance criterion with authentic verification evidence. Use exposed receipt-gate actions for Agent OS completion. Use `plan_validate` when exposed to check plan validity; it does not replace verification receipts. Mark the plan complete only after its tasks are settled and required evidence is accepted.
- Follow the active MCP schema. If an operation is not exposed, use the Hub's supported project-plan interface or report the precise integration blocker; do not silently skip reconciliation or checkpoint recovery.

## Preserve context

- Capture the user's goal, constraints, decisions, clarifications, acceptance criteria, and open questions in the Hub plan. Keep the approved specification linked or referenced there.
- When the user clarifies or corrects something, pause dependent work. Update the plan and, when behavior or scope changed, the specification before continuing. Acknowledge the new direction; keep independent work moving.
- When resuming after a break, handoff, or context compaction, reread the latest user direction, Hub plan, relevant specification, and current diff. Compare them before acting. Use the newest user instruction when earlier notes conflict.
- Treat chat memory as a hint. Treat the current user message, approved specification, and Hub plan as the working record. Do not make the user repeat details already present there.
- After processing new user input, reconcile it against the plan: add new work, update affected acceptance criteria, or record that it changes no scope. Confirm briefly what changed and what continues.

## While working

- After each meaningful milestone, update the matching Hub plan task. Mark completed items done only after their acceptance evidence exists.
- When blocked, immediately mark the task blocked, record the concrete blocker, and set a useful next action. Keep unrelated tasks moving when possible.
- Update the plan when scope, assumptions, dependencies, acceptance criteria, or estimates materially change. Record decisions and evidence references briefly.
- Keep checklist state accurate. Do not leave completed work unchecked or mark unfinished work complete.
- When marking work done, record what changed and the evidence that verifies it. Include relevant test/check names and result, evidence IDs when available, and the repository revision or file scope they cover.
- On resume, trust a completed item while its recorded evidence still applies. Reopen or recheck it only if the user changes its requirement, relevant files changed after its evidence, verification failed, or a dependency/blocker invalidates it. Check the affected item only; do not repeat a full project audit to rediscover known status.
- Keep planned, in-progress, blocked, implemented-but-unverified, and verified-done work distinct. If the Hub schema lacks one of these states, record the distinction in the task description/checkpoint rather than mislabeling completion.
- Report progress at phase changes, meaningful milestones, before long waits, and when blocked. Use a compact `Done / Next / Blocked` update. Do not leave the user without an update for more than a minute during active work.
- For substantial work, checkpoint through the Hub with explicit `phase`, `next_action`, `affected_paths`, `evidence_ids`, `blockers`, and useful `state_data`. Keep durable clarifications and decisions in the project plan.
- After a context handoff, include current status, next action, and blockers in the Hub plan checkpoint so the next agent can resume without reconstructing the thread.
- Use the active Hub schema and available actions. If an action is unavailable, use the Hub's supported project-plan interface; do not bypass it by editing stored plan files.
- If durable plan writing is unavailable, keep working only where safe, state clearly that tracking was not persisted, and report the specific blocker. Never claim the plan is current when a write failed or its result is unknown.

## Completion

- Reconcile every checklist item with the actual diff and validation evidence.
- Check the latest user clarifications against the specification and plan before closing work.
- Confirm every accepted request maps to verified work or a visible open, blocked, or deferred item. Do not re-open verified-done items without a concrete invalidation reason.
- Record remaining blockers and next actions before handing work back.
- Complete the Hub task only when its acceptance criteria pass. A plan update alone is not proof of completion.

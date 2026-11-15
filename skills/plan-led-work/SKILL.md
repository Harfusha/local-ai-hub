---
name: plan-led-work
description: Substantial multi-step work: track tasks, progress, blockers in Local AI Hub plans. Superpowers specs aligned.
---

# Plan-led work

Approved spec and live Hub plan stay aligned throughout work.

## Intake and traceability
- Single source of truth: one Hub plan. Reuse active plan; never duplicate.
- Every user request/clarification -> plan task, criterion, or scope record before action. Link requirements to tasks.
- Unresolved questions/deferred items: record with owner or revisit condition.
- User constraints, priorities, acceptance criteria: preserve verbatim.

## Before implementation
1. New/changed behavior: Superpowers brainstorm/spec workflow first. Save approved spec in repo.
2. List plans (`plan_list`), read matching (`plan_get`), task board (`plan_board_view`). Update active; never edit plan storage directly.
3. Spec + criteria -> bite-sized plan tasks with owners, dependencies, next actions.
4. Bind execution: `local_ai_coord(action="plan_bind_task")`. Keep checkpoints synced.

## Hub workflow
- Schema-first: check active MCP schema; call operations only when exposed. Unavailable: record blocker, stop dependent edits.
- Scope change: reconcile with `plan_reconcile_steering(expected_revision=..., steering_id=..., summary=..., acceptance_criteria=...)`. Spec change: pass `expected_spec_revision`, `spec_rel_path`, `spec_content`.
- Task detail change: `plan_task_edit(expected_revision=...)`. No duplicate tasks.
- Bind task: `plan_bind_task(task_id=..., plan_id=..., plan_task_id=..., root=..., session_id=..., expected_revision=...)`.
- Checkpoints: `task_checkpoint(checkpoint={phase, next_action, affected_paths, evidence_ids, blockers, state_data})`. If recovery pending: reread plan, rebind task/session.
- Resume: `session_briefing`, task lookup, `plan_get`, `plan_board_view`. Recheck only changed items.
- Completion gate: authentic verification evidence for each criterion. Receipt-gate actions for Agent OS completion. `plan_validate` checks plan validity.

## Execution rules
- Checkpoint at phase changes, milestones, waits, blockers. Format: `Done / Next / Blocked`.
- Blocked? Mark blocked immediately, record concrete blocker, set next action.
- Mark done only with authentic verification evidence (test command, result, evidence ID, repo revision/scope).
- Resumption: trust verified items while evidence valid. Never repeat full project audit.
- Complete task only when all acceptance criteria pass. Plan update alone != completion.

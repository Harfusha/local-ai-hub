---
name: plan-led-work
description: "Substantial multi-step work: track tasks, progress, blockers in Local AI Hub plans. Superpowers specs aligned."
---

# Plan-led work

Approved spec and live Hub plan stay aligned throughout work.

## 0. Mandatory First Entrypoint Protocol (Never Skip)
- **First action on any task or turn:** Call `local_ai_coord(action="plan_list", root=ABS_ROOT)` or `local_ai_coord(action="plan_board_view", plan_id=..., root=ABS_ROOT)`.
- Never guess or rediscover state from scratch: the active Hub plan is the authoritative single source of truth for what is completed, in-progress, or blocked.
- Trust verified tasks: do not re-audit or re-implement completed items unless explicit regressions are detected.

## 1. Superpowers Plans & Specs Linking
- Every plan and task must maintain bidirectional traceability with Superpowers artifacts:
  - Superpowers specifications: `docs/superpowers/specs/<spec-name>-design.md`
  - Superpowers implementation plans: `docs/superpowers/plans/<date>-<topic>.md`
- Attach spec paths to `spec_refs` in plan metadata and tasks:
  `spec_refs: [{"path": "docs/superpowers/specs/...", "revision": {"kind": "working"}}]`
- Always reference clickable `file:///` links to the corresponding Superpowers plan and spec in task summaries and chat responses so agents and humans can immediately inspect exact requirements.

## 2. Intake and Traceability
- Single source of truth: one Hub plan per project. Reuse active plan; never duplicate.
- Every user request/clarification -> plan task, criterion, or scope record before action. Link requirements to tasks.
- Unresolved questions/deferred items: record with owner or revisit condition.
- User constraints, priorities, acceptance criteria: preserve verbatim.

## 3. Real-Time Status Lifecycle (Zero Stale State)
- **Start work:** Immediately update task status to `work_status="in_progress"` via `plan_task_edit(expected_revision=...)`.
- **Blocked:** Immediately mark `work_status="blocked"`, set `blocker="concrete reason"`, and define `next_action`.
- **Completed:** When tests pass, immediately update `work_status="completed"` with verification evidence. Never leave completed tasks in `in_progress` or `todo`.
- **Checkpoints:** Run `local_ai_coord(action="task_checkpoint", ...)` at every milestone with format `Done / Next / Blocked`.

## 4. Hub Workflow
- Schema-first: check active MCP schema; call operations only when exposed. Unavailable: record blocker, stop dependent edits.
- Scope change: reconcile with `plan_reconcile_steering(expected_revision=..., steering_id=..., summary=..., acceptance_criteria=...)`. Spec change: pass `expected_spec_revision`, `spec_rel_path`, `spec_content`.
- Task detail change: `plan_task_edit(expected_revision=...)`. No duplicate tasks.
- Bind task: `plan_bind_task(task_id=..., plan_id=..., plan_task_id=..., root=..., session_id=..., expected_revision=...)`.
- Resume: `session_briefing`, task lookup, `plan_get`, `plan_board_view`. Recheck only changed items.
- Completion gate: authentic verification evidence for each criterion. Receipt-gate actions for Agent OS completion. `plan_validate` checks plan validity.


## 5. Verified execution for substantial work
- When the installed Hub supports verified execution, create the Agent OS
  GoalContract with `slo_profile.verified_execution` metadata, including
  independent criteria, dimensions and dependencies. For reviews and large
  collections, use the declared resource/check matrix from deterministic
  inventory; partition oversized scopes rather than silently skipping items.
- Use `verify_completion` after material changes and context recovery;
  follow its next obligation and keep unresolved issues visible. Record
  discoveries using `task_checkpoint` state_data.execution_problem_report.
  A source read or self-reported success is not verification evidence.
- Do not call a plan or project complete until mandatory criteria and
  blocking reports are verified. If work is blocked, report the actual
  remaining obligations. See `docs/VERIFIED_EXECUTION.md`.

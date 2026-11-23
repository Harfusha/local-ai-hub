# Multi-agent coordination

Local AI Hub provides bounded microtasks via `qwen2.5-coder:7b` (local_ai_task). External cloud agents (Codex, Claude, Gemini, Cursor, Copilot) remain the principal orchestrators.
 Agent OS through `local_ai_coord` handles non-trivial multi-step, long-running, delegated, or acceptance-criteria work: create a task contract, checkpoint phases, and verify receipts before completion.
 For explicitly requested closed whole-task delegation, use `local_ai_work`; routine planning and integration stay with the main agent.

Cross-Agent Coordination Primitives:
- **Resource Semaphores (`semaphore_acquire`, `semaphore_release`, `semaphore_status`)**: Serialize access to exclusive single-instance tools, processes, or engines (e.g. Unity Editor, specialized hardware/ports, single-writer state) across agents and sessions. Never busy-loop; use capacity and ttl_seconds.
- **Event-Driven Waiting (`wait_for_event`)**: Long-poll topic signals (e.g. `semaphore.<name>.released` or custom task events) instead of polling in a loop.
- **Project Board (`board_item_create`, `board_item_update`, `board_item_list`, `board_summary`)**: Track multi-agent deliverables, update task progress across columns (`planned`, `in_progress`, `done`, `blocked`, `cancelled`), and log blockers.
- **Milestones (`milestone_create`, `milestone_status`)**: Measure completion percentages across board deliverables.
- **Session Briefing (`session_briefing`)**: Call at agent initialization to compile an instant overview of active tasks, held semaphores, and board deliverables.

Rules:
- Never duplicate the same scope across agents.
- Use `local_ai_coord` leases to guard overlapping files before editing.
- Main agent owns final acceptance and user response. The main agent owns planning, edits, review, validation and final integration.

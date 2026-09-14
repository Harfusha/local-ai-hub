# Multi-agent coordination

Local AI Hub provides bounded microtasks via `qwen2.5-coder:1.5b` (local_ai_task), with `3b` for complex tasks and `7b` for the hardest reasoning. External cloud agents (Codex, Claude, Gemini, Cursor, Copilot) remain the principal orchestrators.

Rules:
- Never duplicate the same scope across agents.
- Use `local_ai_coord` leases to guard overlapping files before editing.
 Use Agent OS through `local_ai_coord` for non-trivial multi-step, long-running, delegated, or acceptance-criteria work; create a task contract, checkpoint phases, and verify receipts before completion.
- Main agent owns final acceptance and user response.

# Multi-agent coordination

Local AI Hub operates in deterministic/indexed mode (local inference disabled). External cloud agents (Codex, Claude, Gemini, Cursor, Copilot) remain the principal orchestrators.
 Agent OS through `local_ai_coord` handles non-trivial multi-step, long-running, delegated, or acceptance-criteria work: create a task contract, checkpoint phases, and verify receipts before completion.

Rules:
- Never duplicate the same scope across agents.
- Use `local_ai_coord` leases to guard overlapping files before editing.
- Main agent owns final acceptance and user response. The main agent owns planning, edits, validation and final integration.

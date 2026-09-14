# Multi-agent coordination

Local AI Hub uses qwen2.5-coder:0.5b only for preprocessing, 1.5b for quick tasks, 3b for complex tasks, and 7b for the hardest reasoning (`local_ai_task`). External cloud agents (Codex, Claude, Gemini, Cursor, Copilot) remain the principal orchestrators.

Rules:
- Never duplicate the same scope across agents.
- Use `local_ai_coord` leases to guard overlapping files before editing.
- Main agent owns final acceptance and user response. A bounded `local_ai_work` order owns only its declared transactional workspace task through verified handoff.

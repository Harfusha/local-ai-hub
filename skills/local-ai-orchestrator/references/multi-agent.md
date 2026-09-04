# Multi-agent coordination

Local AI Hub provides bounded microtasks via `qwen2.5-coder:7b` (local_ai_task). External cloud agents (Codex, Claude, Gemini, Cursor, Copilot) remain the principal orchestrators.

Rules:
- Never duplicate the same scope across agents.
- Use `local_ai_coord` leases to guard overlapping files before editing.
- Main agent owns final integration, validation, and user response.

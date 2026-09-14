# Multi-agent coordination

Local AI Hub uses `qwen2.5-coder:3b-instruct-q5_K_M` for default fast/general microtasks and `qwen2.5-coder:7b-instruct-q5_K_M` only for complex or high-risk work; `qwen2.5-coder:1.5b-instruct-q5_K_M` is preprocessing-only (local_ai_task). External cloud agents (Codex, Claude, Gemini, Cursor, Copilot) remain the principal orchestrators.

Rules:
- Never duplicate the same scope across agents.
- Use `local_ai_coord` leases to guard overlapping files before editing.
- Main agent owns final acceptance and user response. A bounded `local_ai_work` order owns only its declared transactional workspace task through verified handoff.

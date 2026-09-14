# MCP routing card

The active tool surface reflects your configuration:

- `local_ai_repo`: deterministic, code index/search, semantic/graph, context/solve, preprocess, impact, `review_diff`, `security_audit`, patch validation and repository checks.
- `local_ai_command`: cached/single-flight safe command broker for tests, lint, typecheck, builds and read-only checks; never the only Hub action for a repository task.
- `local_ai_work`: durable whole-task orchestration with dependency planning, transactional edits, validation, whole-task verification and compact/lazy handoff.
- `local_ai_task`: use `qwen2.5-coder:1.5b` for quick tasks, `qwen2.5-coder:3b` for complex tasks, and `qwen2.5-coder:7b` for hardest reasoning; `qwen2.5-coder:0.5b` is preprocessing-only.
- `local_ai_rag`: semantic fallback only after deterministic/indexed retrieval.
- `local_ai_artifact`: exact `E...` evidence or artifact slices.
- `local_ai_coord`: edit leases and reusable investigation memos, task contracts and durable memory.
- `local_ai_status`: bounded health/cache/telemetry inspection; no polling loops.

Keep assignments bounded. The main agent retains final acceptance; a `local_ai_work` order may own planning and integration only inside its declared repository task and permissions.

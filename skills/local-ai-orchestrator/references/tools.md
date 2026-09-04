# MCP routing card

The seven-tool surface is deliberate. The main agent selects the narrowest bounded action:

- `local_ai_repo`: deterministic, code index/search, semantic/graph, context/solve, preprocess, impact, `review_diff`, `security_audit`, patch validation and repository checks.
- `local_ai_command`: cached/single-flight safe command broker for tests, lint, typecheck, builds and read-only checks; never the only Hub action for a repository task.
- `local_ai_task`: local-model microtasks, review, compression and second opinions after evidence exists.
- `local_ai_rag`: semantic fallback only after deterministic/indexed retrieval.
- `local_ai_artifact`: exact `E...` evidence or artifact slices.
- `local_ai_coord`: edit leases and reusable investigation memos.
- `local_ai_status`: bounded health/cache/telemetry inspection; no polling loops.

AGY is not a replacement for these tools. Invoke an AGY subagent only when the assignment is fuzzy, open-ended, or itself needs delegated orchestration.

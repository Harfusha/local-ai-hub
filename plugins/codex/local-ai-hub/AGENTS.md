<!-- BEGIN LOCAL AI HUB CODEX INSTRUCTIONS -->
## Codex Local AI Hub Integration

Prioritize `local-ai` MCP tools for all repository exploration, AST code index, and coordination:
- Call `local_ai_repo(action="code_index"|"search"|"context")` before reading files.
- Never dump full files > 80 lines; use `local_ai_artifact(action="slice")` or `local_ai_repo(action="source")` with query coordinates.
- Delegate read-only exploration or critique to local Qwen advisory subagents (`qwen-explorer`, `qwen-critic`) via `local_ai_task(action="delegate")`.
- Record durable task progress in `local_ai_coord(action="task_create"|"task_checkpoint"|"verify_receipt")`.
<!-- END LOCAL AI HUB CODEX INSTRUCTIONS -->

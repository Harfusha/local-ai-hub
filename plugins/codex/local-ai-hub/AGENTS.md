<!-- BEGIN LOCAL AI HUB CODEX INSTRUCTIONS -->
## Codex Local AI Hub Integration

Prioritize `local-ai` MCP tools for all repository exploration, AST code index, and coordination:
- Call `local_ai_repo(action="code_index"|"search"|"context")` before reading files.
- Never dump full files > 80 lines; use `local_ai_artifact(action="slice")` or `local_ai_repo(action="source")` with query coordinates.
- After indexed evidence, call one matching exposed `local_ai_task` semantic action for each independent non-trivial reasoning, exploration, review, second-opinion, or compression subtask. Review material edits after completion; do not call once per mechanical command.
- Use action-specific fields from the live schema: `reason.problem`, `review.code`, `second_opinion.question`, `compress.text`, `explore.task`, `delegate.task`. Semantic output is advisory; it cannot replace exact evidence, deterministic validation, permission checks, approval, or quality gates.
- Use `local_ai_task(action="delegate")` only for bounded advisory suggestions; native subagent management remains Codex-owned and does not replace main-agent Hub calls.
- Record durable task progress in `local_ai_coord(action="task_create"|"task_checkpoint"|"verify_receipt")`.
<!-- END LOCAL AI HUB CODEX INSTRUCTIONS -->

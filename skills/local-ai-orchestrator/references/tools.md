# MCP routing card

The active tool surface reflects your configuration:

- `local_ai_repo`: deterministic, code index/search, semantic/graph, context/solve, preprocess, impact, `review_diff`, `security_audit`, patch validation and repository checks.
- `local_ai_command`: cached/single-flight safe command broker for tests, lint, typecheck, builds and read-only checks; never the only Hub action for a repository task.
- `local_ai_task`: local generation (`qwen2.5-coder:1.5b` quick tier; `3b` complex; `7b` hardest reasoning), review, compression, routing, and enabled image/audio, benchmark, evaluation, candidate, and async-job workflows.
- `local_ai_rag`: semantic fallback after deterministic/indexed retrieval; also manages docsets and document/diagram ingestion when those actions are enabled.
- Code intelligence: use enabled `semantic`/`graph` actions through `local_ai_repo` for symbol navigation or code relationships; built-in indexes remain the fallback.
- `local_ai_artifact`: exact `E...` evidence or artifact slices.
- `local_ai_coord`: edit leases and reusable investigation memos, Agent OS task lifecycle, scoped memory/relations, context, verification, negative knowledge, and coordination primitives.
- `local_ai_status`: bounded health/cache/telemetry, Agent OS task/incident state inspection; no polling loops.

## Enabled specializations

- symbol or code-relationship questions: `local_ai_repo` semantic/graph actions (Serena symbol navigation; CodeGraph relationship/call-graph analysis); indexed fallback remains available
- Agent OS task and incident state: `local_ai_status(detail="agent_state")`
- image understanding: `local_ai_task(action="vision")`
- audio transcription: `local_ai_task(action="transcribe")`
- local-model or device benchmarking: `local_ai_task` benchmark actions
- model/prompt evaluation and drift checks: `local_ai_task` evaluation actions
- model/prompt candidate and speculative-draft workflows: `local_ai_task` candidate actions
- durable asynchronous local jobs: `local_ai_task` submit/status/wait/result/cancel; wait once, never poll
- curated knowledge sets and document/diagram ingestion: `local_ai_rag` docset and ingest actions
- requested automated repair, affected-test selection, formatting, or lint fixes: `local_ai_command` specialized actions
- local mock, replay, and flaky-test workflows: `local_ai_command` specialized actions
- operator-facing live dashboard: `/dashboard` on the configured Hub server; use `local_ai_status` for bounded agent-side checks



## Agent OS trigger and lifecycle

Use this for non-trivial multi-step, long-running, delegated, or acceptance-criteria work, even when the main agent retains ownership. Create a task contract before edits, keep the returned task ID, checkpoint phase changes, compile context when resuming or when state is scattered, and attach validation receipts. Run `verify_completion` before `task_complete`. Trivial one-step lookups can skip this workflow.

Enabled action families: task lifecycle, scoped memory and relations, context compilation, verification receipts, negative knowledge/incidents, blackboard state, swarm coordination, worktree leases, pub/sub, merge simulation, and dataset curation. Use only actions present in the active MCP schema.

Keep assignments bounded. The main agent retains final acceptance and integration.

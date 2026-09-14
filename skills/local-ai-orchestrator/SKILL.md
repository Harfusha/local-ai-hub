---
name: local-ai-orchestrator
description: Local-first routing for Codex, Gemini, Claude, Cursor, Windsurf, VS Code/Copilot and MCP coding agents. Keeps the main agent as orchestrator and routes bounded work through Local AI Hub. Includes Agent OS task contracts, checkpoints, context and receipt-gated completion.
---

# Local AI Hub routing

Trigger map:
- bounded health/cache/telemetry inspection (never poll): `local_ai_status`
- repository facts/files/symbols: `local_ai_repo`
- tests/lint/typecheck/build: `local_ai_command`
- exact source/evidence text: `local_ai_artifact`
- shared findings or overlapping edits: `local_ai_coord`
- non-trivial multi-step, long-running, or acceptance-criteria work: `local_ai_coord` Agent OS task contracts, checkpoints, context, and verified completion
- semantic retrieval after indexed paths are insufficient: `local_ai_rag`
- bounded local generation or second opinion: `local_ai_task`
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

Recipes (guidance, not gates):
- Recipe — Explore: preprocess once, use the cheapest repository action, fetch only required evidence slices.
- Recipe — Change: gather indexed evidence, use `local_ai_repo(action="solve")` before edits, claim `local_ai_coord` leases for overlapping paths, then run indexed impact/review before validation.
- Recipe — Validate: route repeatable commands through `local_ai_command`, reuse cached results, use `review_diff` or `security_audit` when relevant.
- Recipe — Durable execution: create a task contract before substantial work, checkpoint phase changes, attach validation receipts, and complete only after `verify_completion` passes.
- Recipe — Retrieve: use `local_ai_rag` only after deterministic/indexed paths are exhausted.
- A recipe step may be skipped when irrelevant; one bounded fallback is allowed when Hub is unavailable.

Delegation is the default for any task with useful bounded independent work.
- Use `local_ai_task` for bounded local-model work when local inference is the right fit. `qwen2.5-coder:1.5b` is the default fast tier; `3b` is complex work and `7b` is highest reasoning. `0.5b` is preprocessing-only.

- Use the native Codex `multi_agent_v1__spawn_agent` path only for useful independent bounded work or an explicit Codex-subagent request.
- Codex controls each subagent's scope, `allow_write`, workspace/worktree, timeout, cancellation, sandbox, and integration.
- Do not duplicate the same scope across agents. Keep final decisions, edits, and integration in Codex.
- Skip delegation only for trivial tasks, pure evidence lookups, security/privacy constraints, or no useful independent scope.

## Ownership and tiering

The main agent owns task boundaries, permissions, unresolved decisions and the final user answer.

- **Local AI Hub first:** its own precise bounded microtasks, repository facts, indexed search, preprocess, impact, diff/security review, safe commands, compression, local-model synthesis and second opinions.
- **Native Codex subagents:** use only for useful independent bounded work; Codex assigns scope, write permission, workspace/worktree, timeout, sandbox, cancellation and integration.
- **Tiered Qwen defaults:** use `qwen2.5-coder:1.5b` for quick ordinary tasks, `3b` for complex work, and `7b` for the hardest reasoning after bounded evidence. Reserve `0.5b` for preprocessing.
- **RAG:** use only after deterministic/indexed evidence and the basic local model are insufficient. Do not invoke a model to restate facts already available from the hub.

## READ-ONLY AUDIT CONTRACT

- Read-only means no Git writes, `git worktree add` or removal, dependency installation, builds/imports, generated artifacts, or other workspace side effects. Never label such work read-only when any of these occur; split validation into a separately owned, explicitly side-effecting task.
- Before native discovery or validation, retain preceding Hub result with action, absolute root, status, cache/in_progress state, and evidence IDs. Native discovery is fallback-only after one bounded terminal Hub failure.
- Native validation fallback is allowed only after `local_ai_command` returns `terminal=true` and `retryable=false`; run one bounded fallback, state side effects/owner, and never repeat identical commands.
- Codex controls subagent permissions per task. Native Codex subagents may write only when Codex explicitly enables it, and write work stays in the assigned workspace/worktree. Codex remains integrator.
- Do not run parallel duplicate commands or scopes. Tool labels are not evidence; preserve exact action, arguments, result, and ownership in the audit record.

## Mandatory repository gate

For every non-trivial repository task, use Local AI Hub before broad repository exploration unless fresh sufficient hub evidence is already present.

1. Establish one stable **absolute** project root.
2. On the first task for that root call `local_ai_repo(action="preprocess", root=ABS_ROOT)` **exactly once**. Continue immediately; never poll, wait, refresh or force preprocessing.
3. `local_ai_command` alone is never sufficient for a repository task: first use the cheapest applicable non-command Hub action, then use the command broker only for commands. For implementation, diagnosis, refactoring or complex review, call `local_ai_repo(action="solve")` after evidence and before native edits. After edits, run the applicable indexed impact/review/security/evidence check before final validation.
4. Use the cheapest sufficient action and reuse evidence IDs, artifact slices, command results and coordination memos.

Before native `find`, `rg`, `grep`, recursive glob/tree, or opening more than two files for discovery, call the hub first. Native broad discovery is fallback-only after one bounded hub failure.

Stop escalating when evidence is sufficient; reuse cached results and bounded evidence instead of widening the search.

## Action routing

1. `local_ai_repo(action="deterministic")` — manifests, config, dependencies, entrypoints, tests and static facts.
2. `local_ai_repo(action="code_index")` — symbols, references and imports.
3. `local_ai_repo(action="search")` — exact text/file discovery.
4. `local_ai_repo(action="semantic/graph")` — language-aware relationships via Serena/CodeGraphContext, callers/callees and impact.
5. `local_ai_repo(action="context"|"solve")` — compact mixed evidence or bounded repository reasoning.
6. `local_ai_repo(action="review_diff"|"security_audit"|"impact")` — targeted checks after or around edits.
7. `local_ai_task` — local generation, review, compression, and the enabled image/audio, benchmark, evaluation, candidate, and async-job actions shown in its MCP schema; quick-task tier `qwen2.5-coder:1.5b`, with complex work on `3b` and hardest reasoning on `7b`.
8. `local_ai_command` — tests and safe commands; use enabled repair, affected-test, format/lint-fix, mock, and replay actions only when the task calls for them.
9. `local_ai_artifact` — exact evidence/artifact slices only.
10. `local_ai_coord` — leases before overlapping edits; memos before repeating investigation.
11. `local_ai_rag` — indexed semantic fallback, plus enabled docset and document/diagram-ingestion actions for managed knowledge.

## Reuse and failure protocol

- `cache_hit`/`coalesced`: reuse the result.
- `in_progress=true`: do not duplicate the work.
- `retryable`/429/503: back off and do independent work.
- `degraded`/`stale`: verify only the affected slice.
- Hub unavailable: one bounded health/retry attempt, then native fallback. Never loop or inflate timeouts.

Do not fan out overlapping retrieval layers. Stop escalating when evidence is sufficient. Local AI Hub handles its own bounded work; Codex handles native-subagent design and integration.

## Agent Operating System & Durable Execution

Use Agent OS for every non-trivial multi-step, long-running, delegated, or acceptance-criteria task, even when the main agent keeps ownership. A trivial one-step lookup can skip it. Start before edits; keep the returned `task_id` for every later action.

1. **Create a task contract before edits** and retain the returned task ID:
   `local_ai_coord(action="task_create", root=ABS_ROOT, task="Implement the feature", contract={"acceptance_criteria": ["All tests pass"]})`
2. **Checkpoint meaningful phase changes**, discoveries, affected paths, and the next action; resume with `task_resume` after interruption:
   `local_ai_coord(action="task_checkpoint", task_id=TASK_ID, checkpoint={"phase": "testing", "next_action": "run integration tests", "affected_paths": ["src/main.py"]})`
3. **Compile or retrieve context when resuming or when state is scattered**; search memory before repeating expensive work, then record reusable decisions or failed approaches:
   `local_ai_coord(action="context_compile", task_id=TASK_ID, max_tokens=4000)`
   `local_ai_coord(action="memory_find", query="relevant convention")`
   `local_ai_coord(action="memory_record", record={"kind": "decision", "scope": "repository", "key": "convention", "value": "..."})`

4. **Attach receipts to validation and complete only after every criterion is verified:**
- **Run validation commands with automatic receipt capture:**
  `local_ai_command(action="run", command="pytest -q", task_id="task-1", criterion="All tests pass")`
   `local_ai_coord(action="verify_completion", task_id=TASK_ID)`
   `local_ai_coord(action="task_complete", task_id=TASK_ID)`
   If command auto-capture is unavailable, call `local_ai_coord(action="verify_receipt", checkpoint={"task_id": TASK_ID, "criterion": "All tests pass", "passed": True})`. Use `local_ai_coord(action="task_fail", task_id=TASK_ID, reason="...")` when the contract cannot be met.

The enabled Agent OS action families are task lifecycle, scoped memory and relations, context compilation, verification receipts, negative knowledge/incidents, blackboard state, swarm coordination, worktree leases, pub/sub, merge simulation, and dataset curation. Use only actions present in the active MCP schema.

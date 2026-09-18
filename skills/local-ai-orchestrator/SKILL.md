---
name: local-ai-orchestrator
description: Local-first routing for Codex, Gemini, Claude, Cursor, Windsurf, VS Code/Copilot and MCP coding agents. Keeps the main agent as orchestrator and routes bounded work through Local AI Hub.
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
- semantic generation, exploration, reasoning, review, second opinion and compression: `local_ai_task(action="delegate"|"explore"|"reason"|"review"|"second_opinion"|"compress")`
- closed whole-task delegation with verified handoff: `local_ai_work`
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
- Recipe — Semantic work: use `local_ai_task(action="delegate"|"explore"|"reason"|"review"|"second_opinion"|"compress")` for bounded semantic tasks after needed evidence; deterministic/indexed tools remain for exact facts, symbols, diff and tests.
- Recipe — Durable execution: create a task contract before substantial work, checkpoint phase changes, attach validation receipts, and complete only after `verify_completion` passes.
- Recipe — Retrieve: use `local_ai_rag` only after deterministic/indexed paths are exhausted.
- A recipe step may be skipped when irrelevant; one bounded fallback is allowed when Hub is unavailable.

Delegation is the default for any task with useful bounded independent work.
- Use `local_ai_task` for bounded semantic generation, reasoning, review, independent second opinions, and semantic compression. Use `qwen2.5-coder:7b` only for quick/simple requests, `qwen2.5-coder:7b` for ordinary tasks, `qwen3.5:9b` for more involved work, and `qwen3.5:9b` for the hardest reasoning. Deterministic/indexed tools remain for exact facts, symbols, diff and tests; they do not replace these semantic tasks.
- **Closed whole task:** prefer `local_ai_work(action="submit")` when the Hub can own planning, bounded edits, validation and handoff end-to-end. Use `response_profile="compact"` and request only decision-grade fields; fetch the artifact only when details are needed.
- Use the native Codex `multi_agent_v1__spawn_agent` path only for useful independent bounded work or an explicit Codex-subagent request.
- Codex controls each subagent's scope, `allow_write`, workspace/worktree, timeout, cancellation, sandbox, and integration.
- Do not duplicate the same scope across agents. Keep final decisions, edits, and integration in Codex.
- Skip delegation only for trivial tasks, pure evidence lookups, security/privacy constraints, or no useful independent scope.

## Ownership and tiering

    The main agent owns task boundaries, permissions, unresolved decisions and the final user answer. The main agent owns planning, edits, validation and final integration.

- **Local AI Hub first:** its own precise bounded microtasks, repository facts, indexed search, preprocess, impact, diff/security review, safe commands, compression, local-model synthesis and second opinions.
- **Native Codex subagents:** use only for useful independent bounded work; Codex assigns scope, write permission, workspace/worktree, timeout, sandbox, cancellation and integration.
- **Tiered local models:** `qwen2.5-coder:3b` for preprocessing, `qwen2.5-coder:7b` for quick/simple requests, `qwen2.5-coder:7b` for ordinary tasks, `qwen3.5:9b` for more involved work, and `qwen3.5:9b` for the hardest or highest-risk reasoning. Run deterministic/indexed Hub actions first for exact facts, symbols, diff and tests. Use `local_ai_task` for semantic generation, reasoning, review, independent second opinions and semantic compression.
- **RAG:** use only when deterministic/indexed evidence is insufficient for a bounded retrieval question. Do not invoke a model to restate facts already available from the hub.

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

## Context economy contract

- Every Hub response is aggregate-bounded (default ≈3200 tokens); use `max_response_tokens` only when a different bounded size is needed.
- Prefer `response_profile="minimal"`/`"compact"`; request only decision-grade fields.
- Pass a stable `reuse_key` for repeated logical queries. Use `response_profile="delta"` when only changes are needed; unchanged calls return a pointer, not missing data.
- Use the existing `local_ai_task(action="batch")` for independent local tasks; keep each item bounded and consume compact per-item results.
- The Hub keeps a bounded metadata-only context ledger; inspect it only with an explicit cache/status request, never by replaying the whole session.
- Broad native shell reads are guarded by the optional host hook; use bounded limits or the Hub command/repository tools for discovery.
- Fetch exact source, logs, or evidence only with `local_ai_artifact` slices. Never ask a broad tool for the same payload twice.
- Commands return status, summary, changed paths, and failures; full stdout/stderr stays artifact-backed.
- Do not bypass the budget with native broad reads unless Hub has one bounded terminal failure.

## Action routing

1. `local_ai_repo(action="deterministic")` — manifests, config, dependencies, entrypoints, tests and static facts.
2. `local_ai_repo(action="code_index")` — symbols, references and imports.
3. `local_ai_repo(action="search")` — exact text/file discovery.
4. `local_ai_repo(action="semantic/graph")` — language-aware relationships via Serena/CodeGraphContext, callers/callees and impact.
5. `local_ai_repo(action="context"|"solve")` — compact mixed evidence or bounded repository reasoning.
6. `local_ai_repo(action="review_diff"|"security_audit"|"impact")` — targeted checks after or around edits.
7. `local_ai_work(action="submit")` — delegate one complete bounded repository task; Hub plans a DAG, edits transactionally, validates, verifies, and returns a compact handoff.
8. `local_ai_rag` — semantic fallback only when indexed evidence is insufficient.
9. `local_ai_task(action="delegate"|"explore"|"reason"|"review"|"second_opinion"|"compress")` — semantic generation, exploration, reasoning, review, independent second opinions and compression. Use `qwen2.5-coder:7b` only for quick/simple requests, `qwen2.5-coder:7b` for ordinary tasks, `qwen3.5:9b` for more involved work, and `qwen3.5:9b` for the hardest reasoning. Deterministic/indexed tools remain for exact facts, symbols, diff and tests.
10. `local_ai_command(action="run")` — tests, lint, typecheck, builds and repeatable read-only commands before native execution.
11. `local_ai_artifact` — exact evidence/artifact slices only.
12. `local_ai_coord` — leases before overlapping edits; memos before repeating investigation.

## Reuse and failure protocol

- `cache_hit`/`coalesced`: reuse the result.
- `in_progress=true`: do not duplicate the work.
- `retryable`/429/503: back off and do independent work.
- `degraded`/`stale`: verify only the affected slice.
- Hub unavailable: one bounded health/retry attempt, then native fallback. Never loop or inflate timeouts.

Do not fan out overlapping retrieval layers. Stop escalating when evidence is sufficient. Local AI Hub handles its own bounded work; Codex handles native-subagent design and integration.

## Agent Operating System & Durable Execution

Use Agent OS for every non-trivial multi-step, long-running, delegated, or acceptance-criteria task, even when the main agent keeps ownership. A trivial one-step lookup can skip it. Start before edits; keep the returned `task_id` for every later action.

### 1. Goal Contracts & Resumption
- **Create a task contract before edits:**
  `local_ai_coord(action="task_create", task_id="task-1", contract={"goal": "Implement feature", "acceptance_criteria": ["All tests pass"]})`
- **Checkpoint progress before context truncation:**
  `local_ai_coord(action="task_checkpoint", task_id="task-1", checkpoint={"phase": "testing", "next_action": "run integration tests", "affected_paths": ["src/main.py"]})`
- **Resume after session restart or interruption:**
  `local_ai_coord(action="task_resume", task_id="task-1")`
- **Complete only after `verify_completion` passes every acceptance criterion; otherwise fail with a reason:**
  `local_ai_coord(action="verify_completion", task_id="task-1")`, then `local_ai_coord(action="task_complete", task_id="task-1")` or `local_ai_coord(action="task_fail", task_id="task-1", reason="reason")`

### 2. Scoped Memory & Learnings
- **Store durable findings and decisions:**
  `local_ai_coord(action="memory_record", record={"kind": "decision", "scope": "repository", "key": "convention", "value": "Token format must follow HMAC-SHA256"})`
- **Retrieve memories across turns:**
  `local_ai_coord(action="memory_find", query="convention")`

### 3. Exact Context Compilation
- **Compile active task state, relevant memories, negative knowledge, and active edit leases into minimal tokens:**
  `local_ai_coord(action="context_compile", task_id="task-1", max_tokens=4000)`

### 4. Verification Receipts & Completion Gates
- **Run validation commands with automatic receipt capture:**
  `local_ai_command(action="run", command="pytest -q", task_id="task-1", criterion="All tests pass")`
- **Check if all acceptance criteria are verified before completing:**
  `local_ai_coord(action="verify_completion", task_id="task-1")`
- **Record a direct receipt when command auto-capture is not used:**
  `local_ai_coord(action="verify_receipt", checkpoint={"task_id": "task-1", "criterion": "All tests pass", "passed": True})`

### 5. Negative Knowledge & Incident Avoidance
- **Record failed approach or incident:**
  `local_ai_coord(action="negative_knowledge_record", key="timeout", value="build timed out", reason="unindexed lock", status="add index")`
- **Check before repeating a failed operation:**
  `local_ai_coord(action="negative_knowledge_find", query="timeout")`

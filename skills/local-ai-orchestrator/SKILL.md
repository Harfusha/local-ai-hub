---
name: local-ai-orchestrator
description: Local-first routing for Codex, Gemini, Claude, Cursor, Windsurf, VS Code/Copilot and MCP coding agents. Keeps the main agent as orchestrator and routes bounded work through Local AI Hub.
---

# Local AI Hub routing

Trigger map:
- repository facts/files/symbols: `local_ai_repo`
- tests/lint/typecheck/build: `local_ai_command`
- exact source/evidence text: `local_ai_artifact`
- shared findings or overlapping edits: `local_ai_coord`
- semantic retrieval after indexed paths are insufficient: `local_ai_rag`
- bounded local generation or second opinion: `local_ai_task`
- closed whole-task delegation with verified handoff: `local_ai_work`

Recipes (guidance, not gates):
- Recipe — Explore: preprocess once, use the cheapest repository action, fetch only required evidence slices.
- Recipe — Change: gather indexed evidence, use `local_ai_repo(action="solve")` before edits, claim `local_ai_coord` leases for overlapping paths, then run indexed impact/review before validation.
- Recipe — Validate: route repeatable commands through `local_ai_command`, reuse cached results, use `review_diff` or `security_audit` when relevant.
- Recipe — Retrieve: use `local_ai_rag` only after deterministic/indexed paths are exhausted.
- A recipe step may be skipped when irrelevant; one bounded fallback is allowed when Hub is unavailable.

Delegation is the default for any task with useful bounded independent work.
- Model tiers: `qwen2.5-coder:0.5b` is preprocessing-only, `qwen2.5-coder:1.5b` handles quick tasks, `qwen2.5-coder:3b` handles complex tasks, and `qwen2.5-coder:7b` handles the hardest reasoning.
- Use `local_ai_task` for bounded local-model work when local inference is the right fit. Use 1.5B for quick work, 3B for complex tasks, and 7B for the hardest reasoning.
- **Closed whole task:** prefer `local_ai_work(action="submit")` when the Hub can own planning, bounded edits, validation and handoff end-to-end. Use `response_profile="compact"` and request only decision-grade fields; fetch the artifact only when details are needed.
- Use the native Codex `multi_agent_v1__spawn_agent` path only for useful independent bounded work or an explicit Codex-subagent request.
- Codex controls each subagent's scope, `allow_write`, workspace/worktree, timeout, cancellation, sandbox, and integration.
- Do not duplicate the same scope across agents. Keep final decisions, edits, and integration in Codex.
- Skip delegation only for trivial tasks, pure evidence lookups, security/privacy constraints, or no useful independent scope.

## Ownership and tiering

The main agent owns task boundaries, permissions, unresolved decisions and the final user answer. A submitted `local_ai_work` order may own its bounded internal planning, edits, validation and integration until handoff.

- **Local AI Hub first:** its own precise bounded microtasks, repository facts, indexed search, preprocess, impact, diff/security review, safe commands, compression, local-model synthesis and second opinions.
- **Native Codex subagents:** use only for useful independent bounded work; Codex assigns scope, write permission, workspace/worktree, timeout, sandbox, cancellation and integration.
- **Four model tiers:** use `qwen2.5-coder:0.5b` only for preprocessing, 1.5B for quick work, 3B for complex tasks, and 7B for the hardest reasoning after deterministic/indexed evidence.
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
7. `local_ai_work(action="submit")` — delegate one complete bounded repository task; Hub plans a DAG, edits transactionally, validates, verifies, and returns a compact handoff.
8. `local_ai_rag` — semantic fallback only when indexed evidence is insufficient.
9. `local_ai_task(action="delegate"|"reason"|"review"|"second_opinion"|"compress")` — use 1.5B for quick work, 3B for complex tasks, 7B for hardest reasoning; 0.5B is preprocessing-only.
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

## Ollama advisory subagents

Use named profiles for bounded local second opinions:

- `qwen-explorer` — configured advisory profile
- `qwen-drafter` — configured advisory profile
- `qwen-critic` — configured advisory profile

All profiles call Local AI Hub read tooling directly. They never write files, run commands, create worktrees, or claim that a proposal was applied.

Example:

```text
local_ai_task(action="delegate", profile="qwen-explorer", root="<absolute-root>", task="Find the smallest set of files relevant to ...")
```

Skip profiles when deterministic or indexed Hub evidence already answers the question.

## Agent Operating System & Durable Execution

When working on non-trivial tasks, use Local AI Hub's Agent Operating System actions to preserve context, avoid repeating failed attempts, and verify work rigorously:

### 1. Goal Contracts & Resumption
- **Create task contract:**
  `local_ai_coord(action="task_create", task_id="task-1", contract={"goal": "Implement feature", "acceptance_criteria": ["All tests pass"]})`
- **Checkpoint progress before context truncation:**
  `local_ai_coord(action="task_checkpoint", task_id="task-1", checkpoint={"phase": "testing", "next_action": "run integration tests", "affected_paths": ["src/main.py"]})`
- **Resume after session restart or interruption:**
  `local_ai_coord(action="task_resume", task_id="task-1")`
- **Complete or fail task:**
  `local_ai_coord(action="task_complete", task_id="task-1")` or `local_ai_coord(action="task_fail", task_id="task-1", reason="reason")`

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


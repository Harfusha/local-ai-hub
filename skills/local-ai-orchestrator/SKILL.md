---
name: local-ai-orchestrator
description: Local-first routing for Codex, Gemini, Claude, Cursor, Windsurf, VS Code/Copilot and MCP-compatible coding agents. Keeps the main agent as orchestrator, routes bounded work through Local AI Hub, uses AGY as default Codex-owned peer agent, and reserves native Codex subagents for explicit exceptions.
---

# Local AI Hub routing

Trigger map:
- repository facts/files/symbols: `local_ai_repo`
- tests/lint/typecheck/build: `local_ai_command`
- exact source/evidence text: `local_ai_artifact`
- shared findings or overlapping edits: `local_ai_coord`
- semantic retrieval after indexed paths are insufficient: `local_ai_rag`
- bounded local generation or second opinion: `local_ai_task`

Recipes (guidance, not gates):
- Recipe — Explore: preprocess once, use the cheapest repository action, fetch only required evidence slices.
- Recipe — Change: gather indexed evidence, use `local_ai_repo(action="solve")` before edits, claim `local_ai_coord` leases for overlapping paths, then run indexed impact/review before validation.
- Recipe — Validate: route repeatable commands through `local_ai_command`, reuse cached results, use `review_diff` or `security_audit` when relevant.
- A recipe step may be skipped when irrelevant; one bounded fallback is allowed when Hub is unavailable.

Delegation is the default for any task with useful bounded independent work.
- After required indexed evidence, call AGY directly (`mcp__agy__agy` or `mcp__agy__agy_start`) first for research, planning, implementation, review, testing support, or other bounded sidecar work.
- Use `local_ai_task` for bounded local-model work when local inference is the right fit. Do not use the native Codex `multi_agent_v1__spawn_agent` path unless the user explicitly requests a Codex subagent, the task requires a Codex-only capability or native Codex context/tool lifecycle, or one bounded AGY attempt reports AGY unavailable.
- AGY is the mandatory first peer-agent choice for delegatable work; native Codex subagents are exception-only. Never duplicate the same scope across AGY and native Codex agents.
- Codex controls each subagent's scope, `allow_write`, workspace/worktree, timeout, cancellation, and integration.
- AGY is invoked and lifecycle-managed directly by Codex; Local AI Hub does not bootstrap, route, proxy, or own AGY tasks.
- Do not duplicate the same scope across agents. Keep final decisions, edits, and integration in Codex.
- Skip delegation only for trivial tasks, pure evidence lookups, security/privacy constraints, or no useful independent scope.

## Ownership and tiering

The main agent owns planning, sequencing, edits, integration, decisions and the final answer.

- **Local AI Hub first:** its own precise bounded microtasks, repository facts, indexed search, preprocess, impact, diff/security review, safe commands, compression, local-model synthesis and second opinions.
- **AGY-first Codex-owned peer agents:** AGY is default for useful delegated scopes. Codex assigns scope, write permission, workspace/worktree, timeout, sandbox, cancellation and integration; AGY is not routed through Hub. Native `multi_agent_v1__spawn_agent` is exception-only under the routing rule above.
- **Qwen 2.5 Coder default:** use `qwen2.5-coder:7b` for ordinary local reasoning, review, second opinions and compression after bounded evidence. Escalate to smart models only for complexity/risk.
- **RAG:** use only after deterministic/indexed evidence and the basic local model are insufficient. Do not invoke a model to restate facts already available from the hub.

## READ-ONLY AUDIT CONTRACT

- Read-only means no Git writes, `git worktree add` or removal, dependency installation, builds/imports, generated artifacts, or other workspace side effects. Never label such work read-only when any of these occur; split validation into a separately owned, explicitly side-effecting task.
- Before native discovery or validation, retain preceding Hub result with action, absolute root, status, cache/in_progress state, and evidence IDs. Native discovery is fallback-only after one bounded terminal Hub failure.
- Native validation fallback is allowed only after `local_ai_command` returns `terminal=true` and `retryable=false`; run one bounded fallback, state side effects/owner, and never repeat identical commands.
- Codex controls subagent permissions per task. Native Codex subagents and AGY may write only when Codex explicitly enables it, and write work stays in the assigned workspace/worktree. Codex remains integrator.
- Do not run parallel duplicate commands or scopes. Tool labels such as `Local ai repo` or `Agy start` are not evidence; preserve exact action, arguments, result, and ownership in the audit record.

## Mandatory repository gate

For every non-trivial repository task, use Local AI Hub before broad repository exploration unless fresh sufficient hub evidence is already present.

1. Normalize one stable **absolute** project root.
2. On the first task for that root call `local_ai_repo(action="preprocess", root=ABS_ROOT)` **exactly once**. Continue immediately; never poll, wait, refresh or force preprocessing.
3. `local_ai_command` alone is never sufficient for a repository task: first use the cheapest applicable non-command Hub action, then use the command broker only for commands. For implementation, diagnosis, refactoring or complex review, call `local_ai_repo(action="solve")` after evidence and before native edits. After edits, run the applicable indexed impact/review/security/evidence check before final validation.
4. Use the cheapest sufficient action and reuse evidence IDs, artifact slices, command results and coordination memos.

Before native `find`, `rg`, `grep`, recursive glob/tree, or opening more than two files for discovery, call the hub first. Native broad discovery is fallback-only after one bounded hub failure.

## Action routing

1. `local_ai_repo(action="deterministic")` — manifests, config, dependencies, entrypoints, tests and static facts.
2. `local_ai_repo(action="code_index")` — symbols, references and imports.
3. `local_ai_repo(action="search")` — exact text/file discovery.
4. `local_ai_repo(action="semantic"|"graph")` — language-aware relationships via Serena/CodeGraphContext, callers/callees and impact.
5. `local_ai_repo(action="context"|"solve")` — compact mixed evidence or bounded repository reasoning.
6. `local_ai_repo(action="review_diff"|"security_audit"|"impact")` — targeted checks after or around edits.
7. `local_ai_rag` — semantic fallback only when indexed evidence is insufficient.
8. `local_ai_task(action="delegate"|"reason"|"review"|"second_opinion"|"compress")` — default local worker: `qwen2.5-coder:7b`; smart escalation only for complex routes.
9. `local_ai_command(action="run")` — tests, lint, typecheck, builds and repeatable read-only commands before native execution.
10. `local_ai_artifact` — exact evidence/artifact slices only.
11. `local_ai_coord` — leases before overlapping edits; memos before repeating investigation.

## Reuse and failure protocol

- `cache_hit`/`coalesced`: reuse the result.
- `in_progress=true`: do not duplicate the work.
- `retryable`/429/503: back off and do independent work.
- `degraded`/`stale`: verify only the affected slice.
- Hub unavailable: one bounded health/retry attempt, then native fallback. Never loop or inflate timeouts.

Do not fan out overlapping retrieval layers. Stop escalating when evidence is sufficient. Local AI Hub handles its own bounded work; Codex handles native-subagent and AGY orchestration, design and integration.

## Ollama advisory subagents

Use named profiles for bounded local second opinions:

- `qwen-explorer` — repository reconnaissance;
- `qwen-drafter` — proposed solution or patch guidance;
- `qwen-critic` — independent correctness and risk review.

All profiles call Local AI Hub tooling directly: preprocessing/deterministic facts, code index, Serena/CodeGraph, repository search/RAG, evidence IDs, and bounded file slices. They never write files, run commands, create worktrees, or claim that a proposal was applied. Output follows task language while preserving technical identifiers.

Example:

```text
local_ai_task(action="delegate", profile="qwen-explorer", root="<absolute-root>", task="Find the smallest set of files relevant to ...")
```

Skip profiles when deterministic or indexed Hub evidence already answers the question. Let Codex choose a native subagent or AGY when independent agent work is useful.

## Codex-owned AGY peer agents on Windows

- Treat AGY as the default Codex-owned peer agent. Codex decides whether the task is read-only or write-enabled and assigns the smallest useful scope.
- Write-enabled AGY work uses the Codex-assigned workspace/worktree; Codex reviews and integrates the result.
- Invoke AGY directly from Codex. Do not send AGY through `local_ai_task`, Hub bootstrap, Hub routing or Hub lifecycle management.
- Pass `workspace` as one existing absolute directory, for example `C:\Ostatní\WoodTycoon`.
- Direct AGY MCP calls use `mcp__agy__agy` or `mcp__agy__agy_start`; pass the existing absolute repository directory as `cd`. The bridge uses it as subprocess `cwd` and passes it to AGY with `--add-dir`.
- `WinError 267` means invalid Windows working directory. Fix path first; do not retry blindly.
- Codex selects sandbox and permission prompts per task. Never use `--dangerously-skip-permissions`, provider API keys or direct provider REST endpoints.

## Agent Operating System & Durable Execution

When working on non-trivial tasks, use Local AI Hub's Agent Operating System actions to preserve context, avoid repeating failed attempts, and verify work rigorously:

### 1. Goal Contracts & Resumption
- **Create task contract:**
  `local_ai_coord(action="task_create", task_id="task-1", goal="Implement user auth", acceptance_criteria=["All tests pass", "Zero auth leaks"])`
- **Checkpoint progress before context truncation:**
  `local_ai_coord(action="task_checkpoint", task_id="task-1", phase="testing", next_action="run integration tests", affected_paths=["src/auth.py"])`
- **Resume after session restart or interruption:**
  `local_ai_coord(action="task_resume", task_id="task-1")`

### 2. Scoped Memory & Learnings
- **Store durable findings and decisions:**
  `local_ai_coord(action="memory_record", key="auth_convention", value="Tokens must use HMAC-SHA256 with 24h expiry", kind="decision", scope="repository")`
- **Retrieve memories across turns:**
  `local_ai_coord(action="memory_find", query="auth")`

### 3. Exact Context Compilation
- **Compile active task state, relevant memories, and negative knowledge into minimal tokens:**
  `local_ai_repo(action="context_compile", task_id="task-1", max_tokens=4000)`

### 4. Verification Receipts & Completion Gates
- **Run validation commands with automatic receipt capture:**
  `local_ai_command(action="run", command="python -m pytest tests/test_auth.py -q", task_id="task-1", criterion="All tests pass")`
- **Check if all acceptance criteria are verified before completing:**
  `local_ai_repo(action="verify_completion", task_id="task-1")`
- **Transition task to completed once verified:**
  `local_ai_coord(action="task_transition", task_id="task-1", status="completed", reason="All criteria verified with fresh receipts")`

### 5. Negative Knowledge & Incident Avoidance
- **Check before repeating a failed operation:**
  `local_ai_coord(action="incident_decision", fingerprint={"error_class": "database_lock", "operation_class": "migration"})`


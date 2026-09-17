---
name: local-ai-orchestrator
description: Local-first routing for coding agents. Main agent owns planning and integration; Local AI Hub handles bounded work.
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

- Recipe — Explore: preprocess once, use cheapest repository action, fetch only required evidence slices.
- Recipe — Change: gather indexed evidence, use `local_ai_repo(action="solve")` before edits, claim `local_ai_coord` leases for overlapping paths, then run indexed impact/review before validation.
- Recipe — Validate: route repeatable commands through `local_ai_command`, reuse cached results, use `review_diff` or `security_audit` when relevant.
- Recipe — Durable execution: create task contract, checkpoint phase changes, attach validation receipts, complete only after `verify_completion` passes.
- Recipe — Retrieve: use `local_ai_rag` only after deterministic/indexed paths are insufficient.

Delegation is the default for any task with useful bounded independent work.

- Use `local_ai_task` for bounded local-model work when local inference is the right fit.
- Use the native Codex `multi_agent_v1__spawn_agent` path only for useful independent bounded work or an explicit Codex-subagent request.
- Codex controls each subagent's scope, `allow_write`, workspace/worktree, timeout, cancellation, sandbox, and integration.
- Do not duplicate the same scope across agents.
- Skip delegation only for trivial tasks, pure evidence lookups, security/privacy constraints, or no useful independent scope.
- Prefer `local_ai_work(action="submit")` for a closed, low-risk task with bounded edits, validation, and handoff.

## Ownership and tiering

Main agent owns task boundaries, permissions, unresolved decisions, and final answer. Local AI Hub owns only submitted bounded work until handoff. Use deterministic and indexed evidence before a local model. Use configured local tiers: fast for quick tasks, general for ordinary tasks, smart for involved tasks, reasoning for highest risk.

- Local AI Hub first: repository facts, indexed search, preprocess, semantic relationships through Serena or CodeGraphContext, impact, diff/security review, safe commands, compression, local-model synthesis, and second opinions.
- Native Codex subagents: only useful independent bounded work. Codex controls write permission and integration.
- RAG: only after deterministic/indexed evidence is insufficient.

## READ-ONLY AUDIT CONTRACT

- Read-only means no Git writes, `git worktree add` or removal, dependency installation, builds/imports, generated artifacts, or workspace side effects.
- Before native discovery or validation, retain preceding Hub result with action, absolute root, status, cache/in_progress state, and evidence IDs.
- Native validation fallback is allowed only after `local_ai_command` returns `terminal=true` and `retryable=false`; run one bounded fallback.
- Codex controls subagent permissions per task. Native Codex subagents may write only when Codex explicitly enables it.
- Do not run parallel duplicate commands or scopes.

## Mandatory repository gate

Use Local AI Hub before broad repository exploration for every non-trivial repository task unless fresh sufficient Hub evidence exists.

1. Establish one stable absolute project root.
2. Call `local_ai_repo(action="preprocess", root=ABS_ROOT)` exactly once. Continue immediately; never poll, wait, refresh, or force preprocessing.
3. Use `local_ai_repo` before `local_ai_command`. For implementation, diagnosis, refactoring, or complex review, call `local_ai_repo(action="solve")` after evidence and before edits.
4. After edits, run indexed impact, review, or security evidence before validation.

Use cheapest sufficient path: deterministic, code_index/search, semantic/graph, context/solve, RAG, then local model. Stop escalating when evidence is sufficient. Do not fan out overlapping retrieval layers. Reuse cache_hit/coalesced results. `in_progress=true` means another owner works. `retryable`/429/503 means back off. `degraded`/`stale` means verify affected slice. Hub unavailable: one bounded health/retry attempt, then native fallback. Never loop or inflate timeouts.

## Action routing

1. `local_ai_repo(action="deterministic")` — manifests, config, entrypoints, tests, static facts.
2. `local_ai_repo(action="code_index"|"search")` — symbols, imports, references, exact discovery.
3. `local_ai_repo(action="semantic"|"graph")` — Serena/CodeGraphContext callers, callees, and impact.
4. `local_ai_repo(action="context"|"solve")` — bounded mixed evidence and reasoning.
5. `local_ai_repo(action="review_diff"|"security_audit"|"impact")` — targeted post-edit checks.
6. `local_ai_command(action="run")` — tests, lint, typecheck, build, and repeatable commands.
7. `local_ai_artifact` — exact bounded evidence slices.
8. `local_ai_coord` — leases, task state, memories, and verification.
9. `local_ai_task` — bounded local-model diagnosis or second opinion; never open-ended mutation, architecture, or security work.
10. `local_ai_work` — self-contained task with verified handoff.
11. `local_ai_rag` — last semantic fallback.

## Ollama advisory subagents

Use named advisory profiles only for bounded read-only second opinions: `qwen-explorer`, `qwen-drafter`, and `qwen-critic`. They may call `local_ai_repo` and `local_ai_artifact`; they never write files, run commands, create worktrees, or claim a proposal was applied.

## Agent OS and durable execution

For non-trivial multi-step work, create `local_ai_coord(action="task_create")` before edits. Checkpoint phase changes. Pass `task_id` and criterion to validation. Run `local_ai_coord(action="verify_completion")` before `task_complete`. Record failed approaches with negative knowledge. Never poll durable jobs; wait once.

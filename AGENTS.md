# Local AI Hub — contributor and agent guide

<!-- BEGIN LOCAL AI HUB TOOL POLICY -->
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

- Use `local_ai_task` for bounded local-model work when local inference is the right fit. `qwen2.5-coder:1.5b` is the default fast tier.
- Use the native Codex `multi_agent_v1__spawn_agent` path only for useful independent bounded work or an explicit Codex-subagent request.
- Codex controls each subagent's scope, `allow_write`, workspace/worktree, timeout, cancellation, sandbox, and integration.
- Do not duplicate the same scope across agents. Keep final decisions, edits, and integration in Codex.
- Skip delegation only for trivial tasks, pure evidence lookups, security/privacy constraints, or no useful independent scope.

Routing hierarchy: the main agent is the orchestrator, planner, integrator and final owner. Use Local AI Hub first for its own precise, bounded microtasks: deterministic facts, indexed/search retrieval, preprocess artifacts, targeted impact/review/security checks, safe commands, compression, local-model synthesis and second opinions. Native `multi_agent_v1__spawn_agent` is used only for useful independent bounded work or an explicit Codex-subagent request. It is not routed or managed by Local AI Hub.

READ-ONLY AUDIT CONTRACT:
- Read-only means no Git writes, `git worktree add` or removal, dependency installation, builds/imports, generated artifacts, or other workspace side effects. Never label such work read-only when any of these occur; split validation into a separately owned, explicitly side-effecting task.
- Before native discovery or validation, retain preceding Hub result with action, absolute root, status, cache/in_progress state, and evidence IDs. Native discovery is fallback-only after one bounded terminal Hub failure.
- Native validation fallback is allowed only after `local_ai_command` returns `terminal=true` and `retryable=false`; run one bounded fallback, state side effects/owner, and never repeat identical commands.
- Codex controls subagent permissions per task. Native Codex subagents may write only when Codex explicitly enables it, and write work stays in the assigned workspace/worktree. Codex remains integrator.
- Do not run parallel duplicate commands or scopes. Tool labels are not evidence; preserve exact action, arguments, result, and ownership in the audit record.

For every non-trivial repository task, use Local AI Hub before broad native discovery or repeatable validation. Keep one stable absolute project root. On the first task for that root call `local_ai_repo(action="preprocess", root=ABS_ROOT)` exactly once, then continue immediately; preprocessing is asynchronous, so never poll/wait/force-refresh it.

Adoption gate: `local_ai_command` alone is never sufficient for a repository task. The first useful Hub operation must be `local_ai_repo` (preprocess plus the cheapest applicable deterministic/code-index/search/context action); use the command broker only for commands, after repository evidence exists. For implementation, diagnosis, refactoring or complex review, call `local_ai_repo(action="solve")` after evidence and before native edits. After edits, use the applicable indexed impact/review/security/evidence action before final validation.

Cheapest path: deterministic -> code_index/search -> semantic/graph -> context/solve -> RAG -> qwen2.5-coder:1.5b last.
 Stop escalating as soon as a cheaper layer provides enough evidence. Do not fan out overlapping retrieval layers in parallel for the same question. Before native `find`/`rg`/`grep`/recursive glob/tree or opening more than two files for discovery, use that hub path first. Reuse fresh evidence IDs, artifact slices, memos and cache hits;
 do not repeat the same hub action with the same root/query while repository state is unchanged.

Treat result state as a protocol: `cache_hit`/`coalesced` means reuse the result; `in_progress=true` means another owner is doing identical work, so never duplicate it; `retryable`/429/503 means back off and do independent work; `degraded`/`stale` means verify only the affected path/slice; a non-retryable failure permits one cheaper/native fallback. Never turn a transient result into larger timeouts, force refreshes, or polling loops.

Route test/lint/typecheck/build/read-only commands through `local_ai_command` before running them natively. If it returns `in_progress=true`, do not launch a duplicate command. Before an expensive `solve`/model call, search coordination memos for reusable findings. For overlapping multi-agent edits use `local_ai_coord` leases and store concise reusable discoveries as memos.
 After edits, use indexed impact/review plus targeted cached validation; do not rerun broad discovery merely because files changed. `force` and `preprocess_refresh` are recovery/admin controls, never retry buttons. If an optional backend degrades, accept the hub's deterministic/index fallback. If the hub itself is unavailable, make one bounded health/retry attempt, then fall back to native tools. Never loop on health, status, preprocessing, model startup, a failing backend, or an identical command.

Selection guide: `local_ai_repo` for bounded repository facts and checks (including `review_diff` and `security_audit`), `local_ai_command` for bounded repeatable commands, `local_ai_task` for small local-model work and second opinions, `local_ai_work` for a complete bounded repository task with planning, edits, validation and handoff, `local_ai_rag` only after cheaper indexed evidence, `local_ai_artifact` for exact slices, `local_ai_coord` for leases/memos.

Local model default: when generation is needed, use `qwen2.5-coder:1.5b` for ordinary `local_ai_task` delegate/reason/review/second-opinion/compress work. Escalate to `qwen2.5-coder:3b` only for complex or high-risk work; deterministic and indexed Hub actions run first.
<!-- END LOCAL AI HUB TOOL POLICY -->

<!-- BEGIN TOKEN ECONOMY POLICY -->
- Before any repository task, load and follow the `token-economizer` skill when it is installed; this trigger applies even under deadline pressure.
- Zero full-file dumping: Never read files >80 lines in their entirety. Use `repo-map` for high-level structure, `grep-ast <pattern> <file>`, targeted line slices, or `local_ai_artifact(action="slice")`.
- Fast code search: Use `rg` (`ripgrep`) with `-m 5` / bounded matches and `fd` for file finding before opening files.
- AST & structural code search: Use `ast-grep` (`sg`), Serena LSP (`find_symbol`, `find_referencing_symbols`), or `local_ai_repo(action="code_index")` before opening files.
- Context compression & token measurement: Use `repomix --compress` or `files-to-prompt -c` for repo snapshots. Use `tokcount` to measure exact tokens.
- Bounded command outputs: Filter test and build output (`trim-run <cmd>`, `pytest -q --tb=short`, `dotnet test --verbosity quiet`, `git log | trim-run`, `jq` for JSON) or route through `local_ai_command`.
- Surgical edits: Prefer targeted block replacements over rewriting entire files.
- Local model delegation: Route routine microtasks, reviews, and second opinions to local models via `local_ai_task(model="qwen2.5-coder:1.5b")`.
<!-- END TOKEN ECONOMY POLICY -->

## Architecture rules

- Python 3.11+; all runtime state belongs under the configured `server.state_dir` and must not be committed.
- The public MCP surface stays compact. Add capability behind one of the eight existing tools unless a separate schema clearly saves more tokens than it costs.
- Deterministic and indexed operations precede embeddings or model inference. Local LLM calls are the last resort, not the first repository scanner.
- Serena and CodeGraphContext are managed optional backends. Their absence, crash, timeout, or malformed response must degrade cleanly to built-in indexes rather than block the hub.
- Every subprocess and network wait must be bounded. Drain child stderr/stdout and terminate process trees on timeout.
- On Windows use helpers from `process_utils.py` so background subprocesses do not flash console windows.
- Treat client disconnects as normal cancellation/noise, not hub-fatal errors.
- Never persist prompts, source text, model output, secrets, or full project paths in observability telemetry.
- Do not add migration shims or deprecated aliases to this initial-release branch. Derived SQLite state is disposable and may be rebuilt.
- Every release and update MUST publish and maintain matching agent prompts:
  - `docs/INSTALL_PROMPT.md`: canonical bootstrap prompt for any agent in any repository.
  - `docs/UPDATE_PROMPT.md`: canonical update prompt for any agent in any repository to upgrade hub components and refresh instructions.
  - Any changes to tool policies, schemas, flags, or default models must be synced into both prompt files.

## Validation

From the repository root:

```bash
python tools/release_check.py
python -m compileall -q src mcp tools tests
python -m pytest -q
python tools/selftest.py
```

For an installed instance:

```bash
python tools/doctor.py
python tools/hubctl.py status
```

## Agent Operating System

Local AI Hub provides durable execution and memory primitives mapped into the standard tools:
- `local_ai_coord`:
  - Tasks: `task_create`, `task_get`, `task_checkpoint`, `task_complete`, `task_fail`, `task_list`.
  - Memory: `memory_record`, `memory_get`, `memory_find` (scoped key/value storage with substring `query` search).
  - Context: `context_compile` (assembles bounded state, active task, memories, negative knowledge, and active leases).
  - Verification: `verify_receipt`, `verify_completion` (receipt-gated task completion).
  - Negative knowledge: `negative_knowledge_record`, `negative_knowledge_find` (prevents repeating failed approaches).
- `local_ai_command`:
  - Accepts optional `task_id` and `criterion` to auto-mint verification receipts on passing test/lint commands.

# MCP and coding-agent integration

Local AI Hub exposes eight compact MCP tools instead of mirroring every internal endpoint. The same hub process, deterministic indexes, preprocess artifacts, command cache and local-model caches are shared by Codex, Claude Code, Gemini CLI, Cursor, Windsurf, VS Code/Copilot and generic MCP clients.

## Whole-task orchestration

`local_ai_work` is the one high-level orchestration boundary. Use `submit` for a closed repository task that the Hub can plan, edit, validate and verify end-to-end. Use `status`/`wait` for bounded progress checks, `get` with `response_profile`/`return_fields` for projected handoff data, `cancel` to stop work, and `continue` only after a `needs_agent` decision. Detailed plans, step evidence and logs remain artifact-backed by default.


## Mandatory local-first gate

The main agent remains the orchestrator, planner, integrator and final owner. Delegation is the default for useful bounded independent work after indexed evidence. Use bounded `local_ai_task` for local-model work when local inference is the right fit; use native Codex subagents only for explicit Codex-subagent requests or Codex-only capabilities. Codex controls scope, write access, workspace/worktree, timeout, cancellation and integration. Never duplicate the same scope across agents.

For every non-trivial repository task, agents should start preprocessing the stable absolute project root once with `local_ai_repo(action="preprocess", root=...)` and continue immediately. Preprocessing is opportunistic: never poll or wait for it.

Adoption gate: `local_ai_command` alone is not a repository workflow. After the one-time preprocess call, every non-trivial task must use the cheapest applicable non-command Hub action (`deterministic`, `code_index`, `search` or `context`) before running commands. For implementation, diagnosis, refactoring or complex review, call `local_ai_repo(action="solve")` after evidence and before native edits; after edits, use `impact`, `review_diff`, `security_audit` or `local_ai_artifact` as applicable.

Before native recursive search/tree/glob or opening many files for discovery, route cheapest-first: `deterministic` -> `code_index`/`search` -> Serena `semantic` / CodeGraph `graph` -> `context` / `solve`; RAG and local-model synthesis come last. Stop as soon as a layer supplies enough evidence. Do not launch overlapping deterministic/search/context/RAG/model calls in parallel for one question; broader layers already compose or reuse cheaper indexes, so only independent questions should be parallelized. Repeatable tests, lint, typecheck, builds and safe read-only commands go through `local_ai_command`, which state-keys, caches and single-flights duplicate work.

When generation is needed, use `qwen2.5-coder:1.5b` for quick work, `qwen2.5-coder:3b` for complex tasks, and `qwen2.5-coder:7b` for the hardest reasoning; reserve `qwen2.5-coder:0.5b` for preprocessing. Deterministic/indexed evidence still runs first.

Exact source should be fetched through `E…` evidence or artifact slices only when inspection/editing requires it. Fresh hub discovery and command results should not be repeated natively. `force=true` and `preprocess_refresh` are exceptional controls, not retry mechanisms.

If Serena or CodeGraphContext is unavailable, the hub degrades to built-in indexes. Treat response state as a protocol: cache/coalesced results should be reused; `in_progress=true` means another owner is doing identical work; HTTP 429/retryable 503 means back off and do independent work; degraded/stale evidence should trigger verification of only the affected path or evidence slice. A non-retryable failure permits one cheaper/native fallback. If the hub itself is unavailable, perform one bounded health/retry check and then use native tools; never loop on health, preprocessing, model startup or an optional backend, and never increase timeouts as a retry strategy.

## Cloud-agent request and delivery contract

The canonical envelope is the existing JSON body plus `X-LocalAI-Tenant`, `X-LocalAI-Agent`, and one `X-LocalAI-Request-ID` per logical request. Reuse the returned result for `cache_hit` or `coalesced`; do not submit an equivalent foreground request again. A duplicate request ID briefly waits for its owner and replays its completed response when available; only then can it return `in_progress:true`. Replay-safe transport recovery is bounded to one retry with the same request ID, and overload responses carry `retryable:true` plus `retry_after_seconds`; wait at least that hint before any new attempt.

For model-backed `local_ai_task` actions, use `delivery="sync"` when the answer must be inline (the default), `delivery="async"` when the agent can continue independently, or `delivery="auto"` with a positive `latency_budget_ms`. Auto delivery submits the existing durable, coalesced background job only after at least ten observations show endpoint p95 over that budget; sparse history stays inline rather than guessing. Retrieve a submitted job with one bounded `wait`, then `result`; never poll.

For repository context, `local_ai_repo(action="context", mode="fast")` returns bounded deterministic/index context and a `continuation` for `mode="full"`. Use it when foreground p95 matters more than broad semantic recall. It runs no generation task. Repository responses expose `cache_hit`, `cache_layer="workspace"`, and `coalesced`; reuse them instead of submitting a near-identical root/revision/query request.

Root-fingerprint repo cache, request coalescing, per-root external Serena/CodeGraph circuit cooldowns, and `evaluation_record` / `evaluation_report` are already shared across agents. Use opaque task IDs and cohorts for paired baseline/candidate quality, test-pass, and duration evidence; never put source or prompts into evaluation metadata. Ordinary requests may attach `evaluation: {"task_id":"opaque-id","cohort":"hub_on|hub_off","quality_pass":true,"test_pass":true}`; the hub records its measured duration automatically. Pairing still requires the corresponding other cohort.

The built-in client reuses HTTP/1.1 loopback connections per thread and coalesces simultaneous identical active requests. A coalesced response has `coalesced:true`; reuse it rather than creating another request. `in_progress:true` is not an operational failure: honor its retry hint or continue independent work. Git-only `review_diff`/`impact` calls on a non-Git root are terminal client results; switch to deterministic/code-index review rather than retrying Git.

The client also rejects an empty code symbol before transport. Command `classify`/`discover` must precede unfamiliar commands; a policy or executable preflight rejection is terminal and should never be retried.

For an honest deployment cohort, use `/api/metrics?scope=process` or `/api/telemetry/report?scope=process`. This excludes persisted pre-restart history and reports per-agent request count, failure rate, p95 and p99 without retaining prompts, source, or model output. The default `scope=window` remains the rolling-history view.

`evaluation_report` includes a report-only promotion gate. It requires ten matched `hub_on`/`hub_off` opaque task IDs, complete quality and test evidence, no regression, and lower hub-on average duration. `promote` is evidence for an operator rollout, never an automatic routing change.

## Agent configuration

Setup preserves unrelated user configuration and can install MCP entries for Codex, Claude, Gemini, Antigravity, Cursor, Windsurf and VS Code/Copilot. Antigravity's global manifest is `~/.gemini/config/mcp_config.json`; setup keeps its `local-ai` entry aligned with the Gemini profile and removes stale direct Serena/CodeGraph entries when direct MCP is disabled. Portable generated manifests intentionally contain the Hub-only `local-ai` entry by default; direct Serena/CodeGraph entries remain opt-in via `code_intelligence.direct_agent_mcp`. `[agents].extra_mcp_json_paths` / `extra_vscode_mcp_paths` can write explicitly requested custom host configs. The `local-ai-orchestrator` skill and MCP tool descriptions intentionally repeat the same policy so hosts that do not load external skill files still receive the routing contract.

For concurrent agents, use `local_ai_coord` leases before overlapping edits and memos for reusable findings.

## Ollama advisory profiles

Named profiles are available through existing `local_ai_task` and `local_ai_repo` tools: `qwen-explorer` for reconnaissance, `qwen-drafter` for proposed implementation guidance, and `qwen-critic` for independent review. With a repository `root`, each profile uses Hub read-only tooling directly, in order: preprocessing/deterministic facts, code index, Serena/CodeGraph, search/RAG, evidence IDs, then bounded file slices. Profiles never write files, run commands, create worktrees, or apply proposals. Default model is `qwen2.5-coder:7b`; output mirrors task language and preserves technical tokens. Skip named profiles when deterministic/indexed evidence is sufficient.

## Local model conversations

Start a synchronous conversation with `local_ai_task(action="delegate"|"reason", conversation=true, ...)`. The response returns an opaque `conversation_id`; continue it with `local_ai_task(action="continue", conversation_id=..., task="...")`. A conversation pins its initial model, route and system instructions, accepts one active turn, and is bound to its MCP tenant.

Conversation history is process-memory only: it expires after inactivity and disappears after a hub restart. It bypasses generation, semantic and artifact caches, so no transcript or continuation output becomes durable cache state. Profiles and async/auto delivery are unsupported for conversations. Omit `conversation=true` to retain normal stateless behavior.

## Agent Operating System projection
 
When `[agent_state].enabled` is active, the compact MCP surface projects durable agent operating system state without adding new tools:
- `local_ai_coord`: `task_create`, `task_get`, `task_checkpoint`, `task_transition`, `task_resume`, `task_list`, `task_complete`, `task_fail`, `memory_record`, `memory_get`, `memory_find`, `memory_promote`, `context_compile`, `verify_receipt`, `verify_completion`, `negative_knowledge_record`, `negative_knowledge_find`, `incident_decision`.
- `local_ai_repo`: `context_compile`, `verify_receipt`, `verify_completion`.
- `local_ai_task`: `candidate_create`, `candidate_promote`.
- `local_ai_status`: `detail="agent_state"` for health and counts.
- Privacy boundary: telemetry and agent state never store raw prompts, model outputs, secrets, or absolute file paths.
## Aggregate response budgets

Every public Hub tool now applies an aggregate agent-facing response budget after semantic projection. Use `max_response_tokens` for a bounded override, `response_profile="minimal"|"compact"|"standard"|"debug"|"delta"` for intent, and a stable `reuse_key` for repeated logical queries. `delta` returns changed fields only; unchanged repeated results return a pointer envelope with IDs and summary instead of repeating payload data. Independent local-model work uses the existing `local_ai_task(action="batch")` path.

Telemetry records operation category plus raw/projected/saved response estimates, budget truncation, cache outcome, and projection reason. The bounded context ledger is visible only through an explicit `local_ai_status(detail="cache")` request and stores metadata only: no prompts, source text, secrets, or full paths. Hub command execution already caps captured/inline stdout and stderr; intercepting native Codex host `exec` requires a separate host hook and is not silently emulated by MCP.

The installed user hook at `.cursor/hooks.json` blocks broad native `cat`/`type`/`Get-Content`/`rg`/`grep`/`tree` reads without an explicit bound. It fails open on hook errors. Use `-m`, `-First`, `head`, `local_ai_repo`, or `local_ai_artifact` when exact detail is needed.

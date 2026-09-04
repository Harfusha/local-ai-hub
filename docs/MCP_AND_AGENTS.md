# MCP and coding-agent integration

Local AI Hub exposes seven compact MCP tools instead of mirroring every internal endpoint. The same hub process, deterministic indexes, preprocess artifacts, command cache and local-model caches are shared by Codex, Claude Code, Gemini CLI, Cursor, Windsurf, VS Code/Copilot and generic MCP clients.

## Mandatory local-first gate

The main agent remains the orchestrator, planner, integrator and final owner. Delegation is the default for any task with useful bounded independent work: after required indexed evidence, call AGY directly first for bounded research, planning, implementation, review, testing support, or other sidecar work. Use bounded `local_ai_task` for local-model work when local inference is the right fit. Use native Codex `multi_agent_v1__spawn_agent` only for an explicit Codex-subagent request, a Codex-only capability or native Codex context/tool lifecycle, or one bounded AGY-unavailable fallback. Codex controls scope, `allow_write`, workspace/worktree, timeout, cancellation and integration. Local AI Hub does not bootstrap, route, proxy or own AGY tasks. Skip only for trivial tasks, pure evidence lookups, security/privacy constraints or no useful independent scope. Never duplicate the same scope across agents.

For every non-trivial repository task, agents should start preprocessing the stable absolute project root once with `local_ai_repo(action="preprocess", root=...)` and continue immediately. Preprocessing is opportunistic: never poll or wait for it.

Adoption gate: `local_ai_command` alone is not a repository workflow. After the one-time preprocess call, every non-trivial task must use the cheapest applicable non-command Hub action (`deterministic`, `code_index`, `search` or `context`) before running commands. For implementation, diagnosis, refactoring or complex review, call `local_ai_repo(action="solve")` after evidence and before native edits; after edits, use `impact`, `review_diff`, `security_audit` or `local_ai_artifact` as applicable.

Before native recursive search/tree/glob or opening many files for discovery, route cheapest-first: `deterministic` -> `code_index`/`search` -> Serena `semantic` / CodeGraph `graph` -> `context` / `solve`; RAG and local-model synthesis come last. Stop as soon as a layer supplies enough evidence. Do not launch overlapping deterministic/search/context/RAG/model calls in parallel for one question; broader layers already compose or reuse cheaper indexes, so only independent questions should be parallelized. Repeatable tests, lint, typecheck, builds and safe read-only commands go through `local_ai_command`, which state-keys, caches and single-flights duplicate work.

When generation is needed, use the basic local `qwen2.5-coder:7b` tier by default for `local_ai_task` actions `delegate`, `reason`, `review`, `second_opinion` and model-backed `compress`. Escalate to `heavy_code` only when complexity/risk requires it; deterministic/indexed evidence still runs first.

Exact source should be fetched through `E…` evidence or artifact slices only when inspection/editing requires it. Fresh hub discovery and command results should not be repeated natively. `force=true` and `preprocess_refresh` are exceptional controls, not retry mechanisms.

If Serena or CodeGraphContext is unavailable, the hub degrades to built-in indexes. Treat response state as a protocol: cache/coalesced results should be reused; `in_progress=true` means another owner is doing identical work; HTTP 429/retryable 503 means back off and do independent work; degraded/stale evidence should trigger verification of only the affected path or evidence slice. A non-retryable failure permits one cheaper/native fallback. If the hub itself is unavailable, perform one bounded health/retry check and then use native tools; never loop on health, preprocessing, model startup or an optional backend, and never increase timeouts as a retry strategy.

## Cloud-agent request and delivery contract

The canonical envelope is the existing JSON body plus `X-LocalAI-Tenant`, `X-LocalAI-Agent`, and one `X-LocalAI-Request-ID` per logical request. Reuse the returned result for `cache_hit` or `coalesced`; do not submit an equivalent foreground request again. A duplicate request ID briefly waits for its owner and replays its completed response when available; only then can it return `in_progress:true`. Replay-safe transport recovery is bounded to one retry with the same request ID, and overload responses carry `retryable:true` plus `retry_after_seconds`; wait at least that hint before any new attempt.

For model-backed `local_ai_task` actions, use `delivery="sync"` when the answer must be inline (the compatibility default), `delivery="async"` when the agent can continue independently, or `delivery="auto"` with a positive `latency_budget_ms`. Auto delivery submits the existing durable, coalesced background job only after at least ten observations show endpoint p95 over that budget; sparse history stays inline rather than guessing. Retrieve a submitted job with one bounded `wait`, then `result`; never poll.

For repository context, `local_ai_repo(action="context", mode="fast")` returns bounded deterministic/index context and a `continuation` for `mode="full"`. Use it when foreground p95 matters more than broad semantic recall. It runs no generation task. Repository responses expose `cache_hit`, `cache_layer="workspace"`, and `coalesced`; reuse them instead of submitting a near-identical root/revision/query request.

Root-fingerprint repo cache, request coalescing, per-root external Serena/CodeGraph circuit cooldowns, and `evaluation_record` / `evaluation_report` are already shared across agents. Use opaque task IDs and cohorts for paired baseline/candidate quality, test-pass, and duration evidence; never put source or prompts into evaluation metadata. Ordinary requests may attach `evaluation: {"task_id":"opaque-id","cohort":"hub_on|hub_off","quality_pass":true,"test_pass":true}`; the hub records its measured duration automatically. Pairing still requires the corresponding other cohort.

The built-in client reuses HTTP/1.1 loopback connections per thread and coalesces simultaneous identical active requests. A coalesced response has `coalesced:true`; reuse it rather than creating another request. `in_progress:true` is not an operational failure: honor its retry hint or continue independent work. Git-only `review_diff`/`impact` calls on a non-Git root are terminal client results; switch to deterministic/code-index review rather than retrying Git.

The client also rejects an empty code symbol before transport. Command `classify`/`discover` must precede unfamiliar commands; a policy or executable preflight rejection is terminal and should never be retried.

For an honest deployment cohort, use `/v1/metrics?scope=process` or `/v1/telemetry/report?scope=process`. This excludes persisted pre-restart history and reports per-agent request count, failure rate, p95 and p99 without retaining prompts, source, or model output. The default `scope=window` remains the rolling-history view.

`evaluation_report` includes a report-only promotion gate. It requires ten matched `hub_on`/`hub_off` opaque task IDs, complete quality and test evidence, no regression, and lower hub-on average duration. `promote` is evidence for an operator rollout, never an automatic routing change.

## Agent configuration

Setup preserves unrelated user configuration and can install MCP entries for Codex, Claude, Gemini, Cursor, Windsurf and VS Code/Copilot. Portable generated manifests intentionally contain the Hub-only `local-ai` entry by default; AGY is a separately installed, Codex-owned peer server and is the mandatory first delegated route after Hub evidence, while native Codex `multi_agent_v1__spawn_agent` is exception-only and direct Serena/CodeGraph entries remain opt-in via `code_intelligence.direct_agent_mcp`. `[agents].extra_mcp_json_paths` / `extra_vscode_mcp_paths` can write explicitly requested custom host configs. The `local-ai-orchestrator` skill and MCP tool descriptions intentionally repeat the same policy so hosts that do not load external skill files still receive the routing contract.

For concurrent agents, use `local_ai_coord` leases before overlapping edits and memos for reusable findings.

## Ollama advisory profiles

Named profiles are available through existing `local_ai_task` and `local_ai_repo` tools: `qwen-explorer` for reconnaissance, `qwen-drafter` for proposed implementation guidance, and `qwen-critic` for independent review. With a repository `root`, each profile uses Hub read-only tooling directly, in order: preprocessing/deterministic facts, code index, Serena/CodeGraph, search/RAG, evidence IDs, then bounded file slices. Profiles never write files, run commands, create worktrees, or apply proposals. Default model is `qwen2.5-coder:7b`; output mirrors task language and preserves technical tokens. Skip named profiles when deterministic/indexed evidence is sufficient.

## Codex-owned AGY peer agents on Windows

Treat AGY as the default Codex-owned peer agent for every useful delegated scope. Codex assigns whether it may write, the smallest useful scope, workspace/worktree, timeout and sandbox. Invoke AGY directly from Codex; do not send it through `local_ai_task`, Hub bootstrap, Hub routing or Hub lifecycle management. Use native `multi_agent_v1__spawn_agent` only for explicit Codex-subagent requests, Codex-only capabilities/context/lifecycle, or one bounded AGY-unavailable fallback. Pass `workspace` as an existing absolute directory, such as `C:\path\to\workspace`. The bridge validates it, uses it as subprocess `cwd`, and passes it to AGY with `--add-dir`. `WinError 267` means the workspace is not a usable Windows directory; correct the path before retrying. Never use `--dangerously-skip-permissions`, provider API keys or direct provider REST endpoints.
 
## Agent Operating System projection
 
When `[agent_state].enabled` is active, the compact seven-tool MCP surface projects durable agent operating system state without adding new tools:
- `local_ai_coord`: `task_create`, `task_get`, `task_checkpoint`, `task_transition`, `task_resume`, `task_list`, `memory_record`, `memory_get`, `memory_find`, `memory_promote`, `incident_decision`.
- `local_ai_repo`: `context_compile`, `verify_receipt`, `verify_completion`.
- `local_ai_task`: `candidate_create`, `candidate_promote`.
- `local_ai_status`: `detail="agent_state"` for health and counts.
- Privacy boundary: telemetry and agent state never store raw prompts, model outputs, secrets, or absolute file paths.

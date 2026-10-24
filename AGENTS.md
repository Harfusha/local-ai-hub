# Local AI Hub — contributor and agent guide

## Simplified development and integration process

Follow [`docs/superpowers/specs/2026-10-07-simplified-worktree-integration.md`](docs/superpowers/specs/2026-10-07-simplified-worktree-integration.md). It supersedes older instructions below that imply routine delegation, handoff packets, fingerprint manifests, or keeping work in stale branches. Main agent owns audits and integration; default to the current `master` checkout; use only necessary branches/worktrees; integrate bounded units promptly; preserve and classify every leftover before recoverable archival.

<!-- BEGIN LOCAL AI HUB TOOL POLICY -->
> [!IMPORTANT]
> ## AUTOMATIC LOCAL AI HUB PRIORITIZATION IN ANTIGRAVITY
> ## MANDATORY LOCAL AI HUB PRIORITIZATION IN CODEX
> Agents (Gemini in Antigravity, Codex, Claude) MUST AUTOMATICALLY prioritize `local-ai` MCP tools over native tools (`run_command`, native shell, broad `view_file`):
> - **Tests, builds, lint, execution**: Use the agent host's native command tool for bounded checks in the target repository.
> - **Repository & Code Search**: Call `local_ai_repo(action="solve"|"context"|"search"|"code_index"|"review_diff"|"security_audit", root="...")`. DO NOT use broad native discovery (`find`, `dir /s`, unconstrained `rg`, glob) or dump entire files.
> - **Agent OS Lifecycle & Project Memory**: Call `local_ai_coord(action="task_create"|"task_checkpoint"|"memory_record"|"memory_find"|"verify_completion", ...)`. Proactively initialize task contracts, query memory, and record findings.
> - **Semantic Review & Second Opinion**: Actively call `local_ai_task(action="review"|"second_opinion"|"compress")` before finalizing non-trivial edits.
> - **Antigravity wrapper**: Use `call_mcp_tool(ServerName="local-ai", ToolName="<tool>", Arguments={<same arguments>})` for the calls above.
> - **Native fallback**: `terminal=true` alone is insufficient; outages require `retryable=false` too. A Hub-unknown command needs broker `native_fallback_allowed=true`; the native tool must authorize the fallback, bounded to the same root/scope. Hard stops: `native_fallback_allowed=false`, a dangerous command, mutation denial, required approval/override, cancellation, `outcome_unknown`. This permits fallback only, never Hub execution. Missing native authorization: stop and report blocker.

Detailed diagnostics require the dashboard agent-response-detail toggle; requests cannot enable it. The policy applies to nested, asynchronous, artifact and SSE responses. Ordinary results, failures, authorization and evidence identity remain available.

Keep the existing Agent OS task and usage counters. With explicit operator authorization, `task_budget_increase` raises limits only through the ordinary write-authorized broker, including canonical loopback access without a token, with an explicit absolute root and audit reason. No special owner/admin token is required. Failed-task increases preserve status and owner; resume is separate. Never edit task storage directly. `curate_dataset` also requires an explicit absolute root.

Single-owner release contract: one Local AI Hub installation on one PC serves one human. Agents, chats, projects and worktrees are not tenants. Remove tenant selection, propagation and storage partitions; no constant tenant, aliases, shims or dual contracts. Retired tenant fields and headers reject explicitly in preflight. Preserve project/repository/clone/worktree/branch/task/session scopes, owner global scope, API token protection, command authorization, capabilities, path confinement and writer leases. Scheduler jobs use model/source/priority metadata and global limits, never tenant buckets. Synthetic benchmark items use id/prompt fields; tenant fields reject explicitly. Incident records use repository provenance only; retry and negative-knowledge require an explicit root. MCP coordination has no tenant argument; LOCAL_AI_TENANT is retired; session evidence uses session_id. HubClient options are keyword-only; requests retain API tokens without tenant headers; scope aliases reject. SDK checkpoint_task sends canonical nested checkpoint object with explicit phase, next_action, affected_paths, evidence_ids, blockers and state_data; malformed falsey values are not empty defaults. HTTP root binding preserves owner-global memory and explicit session IDs; task creation derives context.repository_id from resolved project coordination ID (supplied IDs must match exactly). Task ownership checks repository identity; rate limiting uses one bounded installation window. Memory context and diagnostics select repository memories by resolved coordination ID, never physical root fallback. Repository memories describe their actual authorized source project. References to another project must be explicitly marked as external context with source root and date; never adopt external-project assertions as facts about the current repository. MemoryStore APIs and HTTP memory dispatch have no tenant argument; mutations retain scope/provenance checks without cwd or session/global fallbacks. Task-memory adoption uses snapshot schema_version=2 with explicit context (root, coordination_id, task_id, session_id, clone_id, worktree_id, branch); wire projection preserves this context. Agent questions use canonical repository root and session_id with optional task association; answer_question rejects task mismatch; question storage/API have no tenant column or selector. Server-managed task scope uses version=2 and repo_root only; reaping retains status/heartbeat/deadline checks; task lookup never reconstructs scope from retired metadata. Automatic task worktrees require explicit authorized physical root. Watchdog maintenance authorizes explicit roots and retains bounded batches, cancellation and heartbeat/CAS fences. Context warmup rechecks root authorization, task revision/scope/status and active mode. Hybrid context uses explicit workspace keywords without tenant routing; retrieval backends retain independent failure handling. Project RAG and diagram ingestion require authorized absolute root and bound workspace; files stay inside root without symlink/junction traversal; named docsets retain owner-global namespace. Generation uses keyword-only source and priority; telemetry and artifact dispatch must not manufacture a tenant identity. Async jobs retain repository/task/session context; conversations use their own IDs without tenant ownership. Writer lease owner identifies an actual task/execution; claim/release/renew use explicit owner; claim uses purpose; coordination ttl_seconds is optional (defaults: 900s for leases, no forced expiry). Never derive writer owner from credentials. Artifact put/compact methods and selectors are keyword-only without owner selector. Receipt evaluation uses exact task owner/root and command_execution_record.v2; broker receipts require canonical JSON artifact persistence and server-managed task root. Patch and repair forward actual broker receipts only; missing receipts are never synthesized; stored receipts require explicit metadata schema with strict passed flags and mutation generations. Writer fencing initializes only final canonical DDL; runtime ALTERs and migration tables are unsupported; work orders keep work_id distinct from Agent OS task_id. Context ledger reuse preserves session identity; request journaling uses request_id, action and payload fingerprint; HTTP principal helpers and security.users are removed. Global quota limits aggregate installation usage without tenant buckets. rag.scope is retired and rejects by presence. Retired tenant provenance blocks startup pending offline conversion; runtime does not merge/rewrite records; conversion is an explicit offline operation with collision refusal, backups and verified record preservation, never a runtime fallback.

Trigger map:
- compact Hub and local-model readiness check (never poll): `local_ai_status`
- repository facts/files/symbols: `local_ai_repo`
- exact source/evidence text: `local_ai_artifact`
- shared findings or overlapping edits: `local_ai_coord`
- Agent OS lifecycle (contracts, milestones, verification): `local_ai_coord(action="task_create"|"task_checkpoint"|"task_complete"|"verify_completion")`. Default to initializing task contracts for coding, bugfixing, and refactoring tasks.
- durable project memory & architecture facts: `local_ai_coord(action="memory_record"|"memory_find")`. Actively persist and consult project facts, conventions, and user preferences.
- anti-pattern & incident tracking: `local_ai_coord(action="negative_knowledge_record"|"negative_knowledge_find")`. Record failed approaches, error classes, and root causes to avoid repeating mistakes.
- semantic retrieval after indexed paths are insufficient: `local_ai_rag`
- semantic generation, exploration, reasoning, review, second opinion and compression: `local_ai_task(action="delegate"|"explore"|"reason"|"review"|"second_opinion"|"compress")`
- `local_ai_work`: only when the user explicitly requests closed delegation; routine work stays with the primary agent
- symbol or code-relationship questions: `local_ai_repo` semantic actions (Serena symbol navigation); indexed fallback remains available
- image understanding/frontend review via `qwen3-vl:4b`: `local_ai_task(action="vision")`
- audio transcription: `local_ai_task(action="transcribe")`
- local-model or device benchmarking: `local_ai_task` benchmark actions
- model/prompt evaluation and drift checks: `local_ai_task` evaluation actions
- model/prompt candidate and speculative-draft workflows: `local_ai_task` candidate actions
- durable asynchronous local jobs: `local_ai_task` submit/status/wait/result/cancel; wait once, never poll
- named read-only local advisory profiles: `local_ai_task(action="delegate", profile=...)`
- curated knowledge sets and document/diagram ingestion: `local_ai_rag` docset and ingest actions
- multi-agent swarms, shared blackboard, and isolated worktrees: `local_ai_coord` swarm, blackboard, and worktree actions
- cross-agent resource semaphores and signal sync: `local_ai_coord(action="semaphore_acquire"|"semaphore_release"|"semaphore_status"|"wait_for_event")`. Guard exclusive resources and await events without polling.
- project board, milestones, and session briefing: `local_ai_coord(action="board_item_create"|"board_item_update"|"board_item_list"|"board_summary"|"milestone_create"|"milestone_status"|"session_briefing")`. Track Kanban deliverables and query briefings.
- cross-project dependencies and contracts: `local_ai_repo` cross_project and cross_repo actions
- repository audits, dead code, secret scanning, and test matrices: `local_ai_repo(action="security_audit"|"dead_code"|"secret_scan"|"test_matrix")`
- operator-facing live dashboard: `/dashboard` on the configured Hub server; use `local_ai_status` for bounded agent-side checks

Recipes (guidance, not gates):
- Recipe — Explore: reuse fresh repository evidence; use bounded indexed/source lookup for exact file or symbol facts; use adaptive context when evidence is insufficient, and preprocess only for unindexed roots or stale evidence.
- Recipe — Change: gather indexed evidence, initialize an Agent OS contract, use `local_ai_repo(action="solve")` before edits, claim `local_ai_coord` leases for overlapping paths, then run indexed impact/review before validation.
- Recipe — Validate: run bounded repeatable commands with the host-native command tool; use `review_diff` or `security_audit` when relevant.
- Recipe — Semantic work: actively use `local_ai_task` for code review (`action="review"`), second opinion on non-trivial logic (`action="second_opinion"`), exploration (`action="explore"`), and compressing noisy test outputs (`action="compress"`).
- Recipe — Agent OS Execution (Default for Non-Trivial Tasks): Initialize a task contract via `local_ai_coord(action="task_create")` with concrete acceptance criteria; query existing memory via `memory_find`; checkpoint milestones via `task_checkpoint`; persist reusable findings via `memory_record`; record failures via `negative_knowledge_record`; attach explicit verification receipts; and verify completion (`verify_completion`) before closure.
- Recipe — Retrieve: use `local_ai_rag` only after deterministic/indexed paths are exhausted.
- A recipe step may be skipped when irrelevant; one bounded fallback is allowed when Hub is unavailable.

Direct ownership is the default. Do not delegate audits, inventory, status checks, or routine implementation. Use a subagent only for genuinely independent bounded implementation that materially shortens the critical path, or when the user explicitly asks; see the simplified workflow spec.

- Semantic delegation is on-demand and optional: after deterministic/indexed evidence, actively use `local_ai_task` for bounded generation, code review (`review`), independent second opinions (`second_opinion`), test-log compression (`compress`), commit message generation, and drafting where helpful. Cloud reasoning and planning are never blocked by mandatory local handoffs. Deterministic/indexed tools remain authoritative for exact facts, symbols, diff and tests. Use `local_ai_task` for bounded semantic generation, reasoning, review, independent second opinions, and semantic compression.
- Use native Codex subagents only for independent bounded implementation or an explicit user request. Never spawn them for audits or to relay results as a handoff.
- Native `multi_agent_v1__spawn_agent` is used only for useful independent bounded work; explicit user requests may also authorize bounded delegation. Codex controls each subagent's scope, `allow_write`, workspace/worktree, timeout, cancellation, sandbox, and integration.
- Keep write scopes disjoint. The primary agent reviews and integrates directly; no ZIPs, custom owner packets, or fingerprint/hash cascades.
- Do not duplicate tasks or chats. Check the existing plan first and update its existing item.

Routing hierarchy: the main agent plans, audits, implements, reviews, and integrates directly. Use Local AI Hub for bounded retrieval and commands when available; Hub tools do not create a requirement to hand off work. On a bounded Hub failure, use the permitted direct local fallback and continue without retry loops.

READ-ONLY AUDIT CONTRACT:
- Read-only means no Git writes, `git worktree add` or removal, dependency installation, builds/imports, generated artifacts, or other workspace side effects. Never label such work read-only when any of these occur; split validation into a separately owned, explicitly side-effecting task.
- Before native discovery or validation, retain preceding Hub result with action, absolute root, status, cache/in_progress state, and evidence IDs. Native discovery is fallback-only after one bounded terminal Hub failure.
- If an explicitly authorized independent subagent is used, Codex controls its permissions and write scope; the main agent remains integrator. Do not delegate audit-only work.
- Do not run parallel duplicate commands or scopes. Tool labels are not evidence; preserve exact action, arguments, result, and ownership in the audit record.

Background preprocessing may inspect and index project files, but project-derived `validation_commands` execute repository code. Keep `preprocessing.idle_diagnostics_enabled=false` by default; set it to `true` only with explicit operator approval for those commands. On Windows, `.cmd` and `.bat` validation executables are rejected; do not route them through a shell or interpreter.

Reuse fresh sufficient repository evidence when available. For exact file or symbol lookups, use bounded indexed/source lookup directly; do not preprocess or compile adaptive context first. For non-trivial implementation or review without sufficient fresh evidence, use `local_ai_repo(action="context", mode="adaptive")` once with a stable absolute project root. Preprocess only when that root is unindexed or its evidence is stale; preprocessing is asynchronous, so never wait, poll, or force-refresh it.

Adoption gate: Use bounded host-native validation commands after fresh repository evidence exists. For code changes, bug fixes, or refactoring, initialize an Agent OS contract (`local_ai_coord: task_create`) and query project memory (`memory_find`). For implementation, diagnosis, refactoring or complex review, call `local_ai_repo(action="solve")` after evidence and before native edits. Actively use `local_ai_task(action="review"|"second_opinion")` for validation before finalizing. After edits, use the applicable indexed impact/review/security/evidence action before final validation.

Adaptive retrieval path: when fresh evidence is insufficient for non-trivial repository work, call `local_ai_repo(action="context", mode="adaptive")`; it runs bounded deterministic/indexed, structural, lexical and RAG retrieval, fuses agreement and diversity, and degrades optional backends independently. Stop escalating when evidence is sufficient; reuse cached results and bounded evidence. Do not fan out duplicate native retrieval layers or translate the task into a long grep-term list. Reuse fresh evidence IDs, artifact slices, memos and cache hits;
 do not repeat the same hub action with the same root/query while repository state is unchanged.

Treat result state as a protocol: `cache_hit`/`coalesced` means reuse the result; `in_progress=true` means another owner is doing identical work, so never duplicate it; `retryable`/429/503 means back off and do independent work; `degraded`/`stale` means verify only the affected path/slice; a non-retryable failure permits one cheaper/native fallback. Never turn a transient result into larger timeouts, force refreshes, or polling loops.

Run bounded validation commands with the agent host native command tool.
 Before an expensive `solve`/model call, reuse supplied task memory; when more is needed, use permitted scoped `local_ai_coord(action="memory_find")`. Workspace `memo_*` actions are unavailable through restricted endpoints; on terminal 403 do not retry or bypass scope. For overlapping edits use `local_ai_coord` leases; record concise findings in permitted scoped Agent OS memory or the existing operator-approved coordination file.
 After edits, use indexed impact/review plus targeted cached validation; do not rerun broad discovery merely because files changed. `force` and `preprocess_refresh` are recovery/admin controls, never retry buttons. If an optional backend degrades, accept the hub's deterministic/index fallback. If the hub itself is unavailable, make one bounded health/retry attempt, then fall back to native tools. Never loop on health, status, preprocessing, model startup, a failing backend, or an identical command.

Selection guide: `local_ai_repo` for bounded repository facts and checks (including `review_diff` and `security_audit`), `local_ai_task` for bounded semantic generation, exploration, reasoning, review, independent second opinions and semantic compression, `local_ai_work` only for closed delegation explicitly requested by the user, `local_ai_rag` only after cheaper indexed evidence, `local_ai_artifact` for exact slices, `local_ai_coord` for leases/memos and Agent OS task, memory, context, and verification workflows.

Local model policy: Model routing follows the active hardware profile and user overrides; consult `docs/MODEL_CAPABILITIES.md` for foreground role targets. Preprocessing follows its configured provider; do not switch it silently. Pinned master `2458f72c` has no Gemini preprocessing provider implementation; Gemini agent manifests do not establish runtime preprocessing support. Routing targets do not prove installed-model availability; model pulls remain opt-in. Check installed-model inventory before live inference; do not infer runtime availability, output quality, or performance from a configured mapping.
## Context economy contract

- Every Hub response is aggregate-bounded (default ≈3200 tokens).
- `response_budget.returned_tokens` measures the final serialized response envelope in `estimated_tokens` and stays at or below the requested budget.
- Preserve protected status, error, evidence, and context-identity fields; keep exact detail artifact-backed.
- Claim savings only with a current `baseline_evidence_id`; report signed `token_savings_delta_est`, including negative values; keep `protocol_tokens_est`, `schema_tokens_est`, and `local_compute_reused_tokens_est` separate.
- Reject `max_response_tokens` below 128; never raise the request silently.
- For Hub outages, native fallback requires explicit `terminal=true` and `retryable=false`; for Hub-unknown commands, require `native_fallback_allowed=true` plus native-tool authorization.
- On `outcome_unknown` or `in_progress`, do independent work; never poll or repeat the identical operation.
- Prefer `response_profile="minimal"`/`"compact"`; request only decision-grade fields.
- Pass a stable `reuse_key` for repeated logical queries. Use `response_profile="delta"` when only changes are needed; unchanged calls return a pointer, not missing data.
- Use the existing `local_ai_task(action="batch")` for independent local tasks; keep each item bounded and consume compact per-item results.
- The Hub keeps a bounded metadata-only context ledger; inspect it only with an explicit cache/status request, never by replaying the whole session.
- Broad native shell reads are guarded by the optional host hook; use bounded limits or the Hub command/repository tools for discovery.
- Commands return status, summary, changed paths, and failures; full stdout/stderr is retrievable only when `output_artifact_id` is returned.
- Reuse fresh sufficient repository evidence; use bounded indexed/source lookup directly before native broad discovery.
- Do not bypass the budget with native broad reads unless Hub has one bounded terminal failure.
<!-- END LOCAL AI HUB TOOL POLICY -->

<!-- BEGIN TOKEN ECONOMY POLICY -->
- Before coding or repository work, load `local-ai-orchestrator` and `token-economizer` when installed, even under deadline pressure.
- Zero full-file dumping: Never read >80-line files in full; use `local_ai_repo(action="context")`/`repo-map`, `grep-ast`, targeted line slices, or `local_ai_artifact(action="slice")`.
- Fast code search: Use `local_ai_repo(action="code_index"|"search")` or Serena LSP first; use `rg` (`ripgrep`) with `-m 5` / bounded matches and `fd` for fallback discovery before opening files.
- AST & structural code search: Use `local_ai_repo(action="code_index")`, Serena LSP (`find_symbol`, `find_referencing_symbols`), or `ast-grep` (`sg`) before opening files.
- Context compression & token measurement: Use `repomix --compress` or `files-to-prompt -c` for repo snapshots. Use `tokcount` to measure exact tokens.
- Bounded command outputs: Run tests and builds with the agent host native command tool; use `trim-run` only with bundled `tokcount`/`repo-map`, read-only `rg`/`fd`/`grep-ast`, or stdin pipelines such as `git log | trim-run`. Use `jq` for JSON.
- Surgical edits: Prefer targeted block replacements over rewriting entire files.
- `response_budget.returned_tokens` measures the final serialized response envelope in `estimated_tokens` and stays at or below the requested budget.
- Preserve protected status, error, evidence, and context-identity fields; keep exact detail artifact-backed.
- Claim savings only with a current `baseline_evidence_id`; report signed `token_savings_delta_est`, including negative values; keep `protocol_tokens_est`, `schema_tokens_est`, and `local_compute_reused_tokens_est` separate.
- Reject `max_response_tokens` below 128; never raise the request silently.
- For Hub outages, native fallback requires explicit `terminal=true` and `retryable=false`; for Hub-unknown commands, require `native_fallback_allowed=true` plus native-tool authorization.
- On `outcome_unknown` or `in_progress`, do independent work; never poll or repeat the identical operation.
- Local model routing follows the active hardware profile and user overrides; use `local_ai_task` for bounded semantic generation, reasoning, review, independent second opinions and compression. Consult `docs/MODEL_CAPABILITIES.md`; configured routes do not prove models are installed. Deterministic/indexed tools remain authoritative for exact facts, symbols, diff and tests.
<!-- END TOKEN ECONOMY POLICY -->


## Architecture rules

Task memory adoption passes the same resolved repository coordination ID into compilation, record materialization and excluded-memory diagnostics; expiry checks retain the current repository and declared scope identity.

Consistency-guard repository memory writes and audit reads require the current server-derived project coordination ID and declared scope; missing required identity cannot fall back to a physical-root lookup. No tenant routing or synthetic tenant identity is permitted. Windows isolated-parser workers treat only WerGetFlags ERROR_NOT_FOUND as absent per-process flags before setting NO_UI; other HRESULT failures remain explicit.

Agent scopes use exact enum values global/repository/clone/worktree/branch/task/session. Supplied aliases, case/whitespace variants and unknown/nonstring values reject instead of selecting default authority. Omitted scope retains its declared default; the HTTP memory filter retains empty/absent filter semantics.

Private tool-accounting events carry signed token evidence only; they do not fabricate USD costs with fixed rates. TelemetryStore owns configured channel pricing. Token-efficiency metadata uses canonical parent_task/activity/revision/reuse_state/cache_state fields; retired substitutes are not promoted. Trace metadata setters are set_metadata/reset_metadata only.

Telemetry prices use independent finite nonnegative numeric `cloud_input_token_cost_usd_per_million` and `cloud_output_token_cost_usd_per_million` rates (default 3.0 each; zero remains valid). The combined-rate fallback is removed. Missing channel coverage, inconsistent row accounting, or missing boundary history makes total USD cost unknown; known raw-row channel subtotals remain separate. Cost-bearing daily rollups without channel provenance cannot establish complete pricing. Writer lease identifiers reject scalar coercion; lease paths require a sequence of strings, and corrupt live path scopes fail closed.

Compiled context delivery preserves exact task/root/session identity in a persisted task-context artifact. When a mandatory task goal exceeds the compiler budget, the artifact additionally contains omitted_task_goal; inline context stays explicitly incomplete. Recover the exact task_context_artifact_id using bounded local_ai_artifact get pages and next_offset until null. If the response cap cannot carry recovery metadata, request_larger_response_budget is an explicit rejection; the Hub never silently increases the requested limit.

Semantic MCP responses require an explicit boolean `success`; `answer` cannot substitute for `text`. Successful compiled task context requires explicit `success=true` and `complete=true` on both the response and nested `task_context`, whose `text` is a string. Top-level text cannot substitute for nested task context. Internal lexical `RepositoryTools.search` uses `limit`, never the retired `top_k` keyword; distinct RAG/context candidate parameters retain their own contracts. Blackboard CAS updates accept only nonnegative integer `expected_version` (or omission); the retired `expected_etag` keyword rejects. Sections with different identities cannot merge.

Coordination verification uses an explicit `receipt` object; never synthesize `passed=true` or derive receipt identity from checkpoint/status fields. Completion and export use `task_id`; completion may pin `repository_revision` to the exact fresh snapshot fingerprint (empty means no caller pin). Question IDs/text/answers use their dedicated fields; optional task association remains supported. Task sync uses `sync_action`, `stream_id`, `after_seq`, `limit`, and `events`, with strict export/import field exclusivity.

Canonical repository inputs: `context` takes its task description in `query`; `solve` and `delegate` use `task`. No field fallback is supported. Cross-project graph/symbol/impact use `cross_project_*`; distinct backend/frontend analysis remains `cross_repo_contract`. `synthesize_commit` may use explicit `task_id`, never inferred from a task-name string. Test matrix evidence describes current supported files within a bounded iterator scope and lexical case detection, never runtime test collection or success.

- Python 3.11+; all runtime state belongs under the configured `server.state_dir` and must not be committed.
- The public MCP surface stays compact. Add capability behind one of the seven existing tools unless a separate schema clearly saves more tokens than it costs.
- For repository scanning, deterministic and indexed operations precede embeddings or model inference. Semantic generation, reasoning, review, independent second opinions and compression use `local_ai_task` after any needed evidence; local LLM calls remain excluded from architecture, security, mutations and open-ended coding.
- Serena is an optional managed backend. Its absence, crash, timeout, or malformed response must degrade cleanly to built-in indexes rather than block the hub.
- Every subprocess and network wait must be bounded. Drain child stderr/stdout and terminate process trees on timeout.
- On Windows use helpers from `process_utils.py` so background subprocesses do not flash console windows.
- Treat client disconnects as normal cancellation/noise, not hub-fatal errors.
- Aggregate observability telemetry stays metadata-only. Detailed debug traces are opt-in and remain local; while enabled, retain complete endpoint payloads, paths, and trace events without redaction or truncation. Keep storage bounded with retention and whole-trace eviction, never by trimming content.
- Do not add migration shims or deprecated aliases to this initial-release branch. Derived SQLite state is disposable and may be rebuilt.
- Every release and update MUST publish and maintain matching agent prompts:
  - `docs/INSTALL_PROMPT.md`: canonical bootstrap prompt for any agent in any repository.
  - `docs/UPDATE_PROMPT.md`: canonical update prompt for any agent in any repository to upgrade hub components and refresh instructions.
  - Any changes to tool policies, schemas, flags, or default models must be synced into both prompt files.

## Validation

Working-checkout release checks ignore generated Python/pytest caches covered by
`.gitignore`. Use `--allow-installed` for a live checkout with managed environments
and state. Use `--strict-tree` when validating a clean release tree; it cannot be
combined with `--post-test` or `--allow-installed`.

From the repository root:

```bash
python tools/release_check.py
python -m compileall -q src tools tests
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
  - Tasks: `task_create`, `task_get`, `task_checkpoint`, `task_complete`, `task_fail`, `task_list`, `task_resume`, `task_budget_increase`.
  - Memory: `memory_record`, `memory_get`, `memory_find` (scoped key/value storage with substring `query` search).
  - Context: `context_compile` (assembles bounded state, active task, memories, negative knowledge, and active leases).
  - Verification: `verify_receipt`, `verify_completion` (receipt-gated task completion).
  - Negative knowledge: `negative_knowledge_record`, `negative_knowledge_find` (prevents repeating failed approaches).
  - Accepts optional `task_id` and `criterion` to auto-mint verification receipts on passing test/lint commands.

## Local model policy

- `qwen2.5-coder:1.5b` is preprocessing-only; `qwen2.5-coder:3b` handles quick or simple tasks; `qwen2.5-coder:7b` handles ordinary and involved tasks; `qwen3.5:9b` handles the hardest reasoning.
- Resolve routes from active configuration and user overrides. Routing targets do not prove a model is installed; model pulls remain opt-in.

Canonical coordination inputs: blackboard update uses content, author and optional expected_version; merge uses remote_sections. Board IDs retain the task_id-scoped default. Pubsub publish uses topic/message/publisher and preserves null or falsey JSON; poll uses after_seq, limit (1–1000, default 50) and optional after_ts, distinct from sequence. Swarm uses goal/target_paths/test_command/author, swarm_id/role/swarm_action/payload, and state for listing. Worktree actions use branch/worktree_path/worktree_id/delete_branch; omitted delete_branch remains true and explicit false is preserved. Simulated merge uses source_branch/target_branch. Dataset curation uses output_path/min_receipts/format (default jsonl); verification export defaults to markdown. Retired generic key/value/query/status aliases cannot substitute for these fields. Incident decision uses fingerprint/state_revision; negative-knowledge recording takes an explicit record object and finding takes query/limit (1–100, default 100). Incident records accept strict signed or unsigned 32-bit process exit codes, including Windows access violations. Root and tenant cannot be overridden inside the record. Generic SDK coordination follows these canonical verification and incident inputs. Source integration alone does not activate running processes or establish runtime acceptance.

Path fusion canonicalizes redundant dot/separator spellings before cross-backend agreement, preserving case, UNC prefixes and parent segments. limit and max_per_path require positive integers; coercive legacy values are rejected. Each optional backend is sampled up to a fixed 4096 entries independently of output limit; malformed groups or iterator failures leave other backends available. This is bounded candidate ranking, not a claim of exhaustive corpus coverage or measured relevance/performance.

Tiered cache nonempty batches require the current L2 set_many API. Providers without that callable batch method reject before L1/L2 writes or coordinator acquisition; there is no per-entry compatibility fallback. Empty batches remain no-ops. Existing supported SQLite batch transactions and coordinator failure recovery are retained; live correctness and performance still require final integrated validation.

Capability grants require canonical string identities, immutable internal capability sets and JSON-array allow/deny inputs; scalar coercions and invalid/nonfinite expiry reject. Explicit deny remains authoritative. Verification receipt passed flags are booleans, generations are nonnegative integers, and observed/expiry timestamps are finite numbers; invalid expiry never becomes unlimited validity. These source changes require integrated validation before acceptance.

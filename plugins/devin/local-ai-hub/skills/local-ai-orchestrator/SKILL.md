---
name: local-ai-orchestrator
description: Use when repository work, provider setup, or troubleshooting involves Local AI Hub, its MCP tools, or Laya across Codex, Antigravity/Gemini CLI, Claude, Cursor, Windsurf, VS Code/Copilot, Devin Local, OpenCode, or other MCP coding agents.
---

# Local AI Hub routing

Trigger map:
- local inference readiness: call `local_ai_status` once when it affects the next step
- every non-trivial repository task: start with indexed `local_ai_repo` evidence
- exact located source or stored evidence: bounded `local_ai_artifact` slice/get
- durable task state, shared findings, memory, or overlapping edits: `local_ai_coord`
- non-trivial work: initialize/checkpoint Agent OS tasks; verify before completion
- reusable project facts: find scoped memory; record only verified findings
- before repeating a failure: check scoped negative knowledge
- `local_ai_rag` only after indexed repository evidence is insufficient
- second-pass semantic QA after evidence, when exposed and qualified: use an exposed semantic action
- `local_ai_work`: existing work status, wait, get and cancel actions only; new work submission is unavailable at this profile
- `local_ai_repo` generation/mutation: explicit scoped requests only; preserve approval/review gates.
- `local_ai_repo` preprocessing: register unindexed roots once; maintenance actions only on request, never retries.
- `local_ai_task`: after evidence, default to exposed semantic QA (compress) when quality/backend gates pass.
- Tier-available semantic actions only: `compress`; unavailable actions stay omitted.
- `local_ai_task` specialized work (audio, browser/desktop, benchmark/evaluation, candidate workflows, routing/batch, async jobs): matching requests and exposed actions only.
- `local_ai_task` async jobs (status/wait/result/cancel): require a known job ID; readiness uses `local_ai_status`.
- `local_ai_coord` repair/deletion/budget/GPU controls require action-specific authorization and audit fields.

Active MCP tools and profile-enabled actions:
- `local_ai_status`: `brief`
- `local_ai_repo`: `profile`, `search`, `map`, `code_index`, `deterministic`, `context`, `route`, `impact`, `refactor_impact`, `resolve_imports`, `generate_tests`, `validate_patch`, `audit_dependencies`, `ast_outline`, `test_matrix`, `security_audit`, `git_status`, `repo_state`, `synthesize_commit`, `verify`, `affected_tests`, `topology`, `ast_refactor`, `generate_mocks`, `split_changes`, `synthesize_rules`, `code_invariants`, `generate_dataset`, `profile_digest`, `callers`, `callees`, `implementations`, `declaration`, `dead_code`, `secret_scan`, `schema_inspect`, `explain_query`, `env_compat`, `circular_dependencies`, `generate_types`, `complexity`, `api_spec`, `dependency_slice`, `migration_drift`, `package_audit`, `structural_search`, `context_budget`, `git_diff`, `git_history_search`, `hotspots`, `generate_tests_for_diff`, `cross_repo_contract`, `reachability_dead_code`, `mutation_test`, `type_stubs`, `skeletonize`, `investigate`, `diagnose`, `briefing`, `batch_replace`, `semantic`, `intelligence`, `pipeline`, `preprocess`, `preprocess_status`, `preprocess_refresh`, `preprocess_pause`, `preprocess_resume`, `preprocess_cancel`, `preprocess_unregister`, `call_graph_diff`, `semantic_diff`, `cross_project_graph`, `cross_project_symbols`, `cross_project_impact`, `patch`, `call_graph`, `revert`, `find_files`, `git_log`, `file_info`, `source`
- `local_ai_task`: `compress`, `route`, `benchmark`, `hardware_benchmark`, `evaluation_record`, `evaluation_report`, `status`, `wait`, `result`, `cancel`, `candidate_create`, `candidate_promote`, `transcribe`, `browser`, `eval_suite`, `prompt_eval`, `eval_drift`
- `local_ai_rag`: `index`, `search`, `list`, `docset_index`, `docset_search`, `ingest_document`, `ingest_diagram`
- `local_ai_coord`: `claim`, `renew`, `release`, `leases`, `client_status`, `gpu_reservation_status`, `gpu_reservation_release`, `gpu_reservation_release_authorized`, `gpu_capacity_lease_release`, `gpu_scheduler_capacity_lease_release`, `task_create`, `task_get`, `task_checkpoint`, `task_rollback`, `task_transition`, `task_resume`, `task_list`, `task_budget_increase`, `task_repair_session`, `task_complete`, `task_fail`, `task_heartbeat`, `ask`, `answer`, `memory_record`, `memory_get`, `memory_find`, `memory_promote`, `memory_delete`, `context_compile`, `verify_receipt`, `verify_completion`, `verify_export`, `negative_knowledge_record`, `negative_knowledge_find`, `incident_decision`, `blackboard_update`, `blackboard_get`, `blackboard_list`, `blackboard_merge`, `blackboard_delete`, `swarm_dispatch`, `swarm_step`, `swarm_status`, `swarm_list`, `swarm_cancel`, `worktree_lease`, `worktree_release`, `pubsub_publish`, `pubsub_poll`, `simulate_merge`, `curate_dataset`, `task_sync`, `task_zombie_reap`, `task_cleanup_worktree`, `wait_for_event`, `semaphore_acquire`, `semaphore_release`, `semaphore_status`, `session_briefing`, `task_claim`, `record_native_receipt`, `plan_init`, `plan_list`, `plan_get`, `plan_create`, `plan_update`, `plan_task_edit`, `plan_task_delete`, `plan_validate`, `plan_archive`, `plan_board_view`, `plan_adopt_legacy_board`, `plan_bind_task`, `plan_reconcile_steering`
- `local_ai_artifact`: `get`, `slice`, `list`, `source`
- `local_ai_work`: `status`, `wait`, `get`, `cancel`

This generated surface reflects configuration and profile feature gates. Runtime authorization, task permissions, backend health, and quality gates are checked when an action runs.
The connected MCP server's current `tools/list` schema is authoritative for tool availability. This bundled action list and `references/tools.md` are snapshots only; inspect the live schema before selecting an action.
Laya actively advises eligible model-route, context-budget, and retrieval-strategy decisions through the exposed decision surface. For source selection, use `evaluate_context_source` with aligned evidence IDs and task-scoped `source_record_ids`; Laya does not fetch evidence or grant permissions. Treat proposals as advisory and preserve deterministic Hub authority and host approvals.
For `local_ai_task`, action inputs are strict: `benchmark` reads stored results only; `hardware_benchmark` accepts `model`, `prompt`, `max_tokens`, and `context_tokens` (4096–32768), with no `timeout_seconds`.

Recommended Hub routes (apply the matching route by default):
- Recipe — Explore: on first work in a stable root, inspect project config and register with one idempotent preprocess call; use bounded indexed/source lookup for exact file or symbol facts and adaptive context when evidence is insufficient; never force-refresh or poll preprocessing.
- Recipe — Change: gather indexed evidence, initialize an Agent OS contract, use `local_ai_repo(action="context")` when exposed, claim `local_ai_coord` leases for overlapping paths, then run indexed impact/review before validation.
- Recipe — Validate: run bounded repeatable commands with the host-native command tool; use `security_audit` when relevant.
- Recipe — Semantic work: use exposed `local_ai_task` semantic actions after deterministic/indexed evidence.
- Recipe — Agent OS Execution (Default for Non-Trivial Tasks): Initialize a task contract via `local_ai_coord(action="task_create")` with concrete acceptance criteria; query existing memory via `memory_find`; checkpoint milestones via `task_checkpoint`; persist reusable findings via `memory_record`; record failures via `negative_knowledge_record`; attach explicit verification receipts; and verify completion (`verify_completion`) before closure.
- Recipe — Retrieve: use `local_ai_rag` only after deterministic/indexed paths are exhausted.
- Apply the matching Hub route by default. Skip only when irrelevant, unavailable in the active schema/config, or fresh sufficient evidence already exists; after one terminal Hub failure, use one bounded native fallback and continue without retries.

Direct ownership is the default. Do not delegate audits, inventory, status checks, or routine work. Use subagents only for independent bounded implementation that materially shortens the critical path, or on explicit request; see the simplified workflow spec.
- Semantic delegation is on-demand under the active schema and quality gates. This profile advertises `local_ai_task(action="compress")`; use matching exposed actions by default after deterministic/indexed evidence; cloud planning is never blocked by mandatory local handoffs. Deterministic/indexed evidence is authoritative; the primary agent accepts. Use `local_ai_task(action="compress")` for semantic condensation. Actions unavailable under this profile are omitted. Follow the active hardware profile and user overrides; verify model availability and select autonomy by task risk and measured quality. Deterministic/indexed tools remain for exact facts, symbols, diff and tests; they do not replace these semantic tasks.

- Use native Codex subagents only for independent bounded implementation or an explicit user request. Never spawn them for audits or to relay results as a handoff.
- Native `multi_agent_v1__spawn_agent` is used only for useful independent bounded work or an explicit request. Codex controls subagent permissions per task, including `allow_write`, workspace/worktree, timeout, cancellation, sandbox, and integration.
- Keep write scopes disjoint. The primary agent reviews and integrates directly; no ZIPs, custom owner packets, or fingerprint/hash cascades.
- Do not duplicate tasks or chats. Check the existing plan first and update its existing item.

## Single-owner and repository scope contract

Single-owner and repository scope contract: one Local AI Hub installation on one PC serves one human. Loopback-only Hub access without auth token or tenant partitions. Repository root scopes all operations. Durable Agent OS tasks, memory and verification receipts.

## Batch repository replacement

Use `local_ai_repo(action="batch_replace", edits=[...], dry_run=true)` for preview. `staged` is not batch dry-run and is never forwarded. Each edit must exact-match once. Non-overlapping dirty Git hunks may be preserved; overlapping edits require an active path lease claimed with the actual execution owner, then pass its exact `owner` and returned `lease_id`. The engine preflights all edits, rolls back write failures, and performs no auto-commit. Set `dry_run=false` only after review.


## Ownership and tiering

    The main agent owns task boundaries, permissions, unresolved decisions and the final user answer. The main agent owns task scope, permissions, diff and test review, and final integration. Never infer tool execution or test success from model prose; verify actual tool results or traces. Missing provenance is unknown.

- **Local AI Hub first:** its own precise bounded microtasks, repository facts, indexed search, preprocess, impact, diff/security review, safe commands, compression, local-model synthesis and second opinions.
- **Native Codex subagents:** use only for genuinely independent bounded implementation or explicit user requests; never delegate audits or relay work.
- **Tiered local models:** `qwen2.5-coder:3b` for preprocessing, `qwen2.5-coder:3b` for quick/simple requests, `qwen2.5-coder:7b` for ordinary tasks, `qwen2.5-coder:7b` for more involved work, and `qwen3.5:9b` for the hardest or highest-risk reasoning.
- **Local model routing:** follow the active profile and user overrides, preserve the configured preprocessing provider, and verify installed model availability. Measured task quality and risk govern autonomy. Whisper transcription uses CPU by default; when GPU-only execution is required, set `[transcription].enabled=false` until a GPU-admitted route exists. Run deterministic/indexed Hub actions first for exact facts, symbols, diff and tests. Use `local_ai_task` for semantic generation, reasoning, review, independent second opinions and semantic compression.
- **RAG:** use only when deterministic/indexed evidence is insufficient for a bounded retrieval question. Do not invoke a model to restate facts already available from the hub.

## Ollama process ownership

Ollama is disabled by policy (`ollama.enabled = false`). Setup and the supervisor must not install, start, pull, or probe Ollama. Use only an explicitly configured, already-running loopback llama.cpp endpoint when its route is healthy; there is no automatic fallback. `llama_cpp.mode = auto` does not require a particular GPU.

## READ-ONLY AUDIT CONTRACT

- Read-only means no Git writes, `git worktree add` or removal, dependency installation, builds/imports, generated artifacts, or other workspace side effects; split validation into a separately owned, explicitly side-effecting task.
- Before native discovery or validation, retain the preceding Hub result with action, absolute root, status, cache/in_progress state, and evidence IDs. If the live schema has no action for an operation, use the authorized native tool directly without calling Hub. Hub-unknown commands require broker `native_fallback_allowed=true` and native-tool authorization. After an advertised Hub action, native fallback requires explicit `terminal=true` and `retryable=false`.
- Run bounded validation with the host-native command tool; never repeat identical failing commands.
- A Hub-classified unknown command requires `native_fallback_allowed=true` plus native-tool authorization for the exact command and scope. `native_fallback_allowed=false`, a dangerous command, or a policy denial blocks fallback; this rule does not apply when the live schema has no action.
- Codex controls subagent permissions per task. Native Codex subagents may write only when Codex explicitly enables it, and write work stays in the assigned workspace/worktree. Codex remains integrator.
- Do not run parallel duplicate commands or scopes. Tool labels are not evidence; preserve exact action, arguments, result, and ownership in the audit record.

## Mandatory repository gate

For every non-trivial repository task, use Local AI Hub before broad repository exploration unless fresh sufficient hub evidence is already present.

Reuse fresh sufficient evidence when available. For exact file or symbol lookups, use bounded indexed/source lookup directly; do not preprocess or compile adaptive context first.
Reuse fresh sufficient repository evidence. For exact facts, use bounded indexed/source lookup directly; do not preprocess or compile adaptive context first. When non-trivial planning, editing, review or testing lacks sufficient fresh evidence, call `local_ai_repo(action="context", mode="adaptive")` once before native broad discovery. On first stable-root work, inspect repository config and derive only evidenced exclusions, uncommon extensions, pinned documentation, and entry points; preserve defaults, then preprocess once to register. Preprocess only when the root is unindexed or its evidence is stale; never wait, poll or force-refresh preprocessing. Its adaptive orchestrator fuses deterministic and indexed evidence with Serena, the built-in code index, bounded lexical search and RAG when available; It deduplicates and preserves file diversity. Send task/context, not grep terms. Reuse candidates first, then carry forward evidence IDs and artifact slices; cite every factual claim. Deterministic/indexed evidence is authoritative; models only rank, select or compress structured evidence. Guarded scope or drift overrides require an explicit `override_reason` and approval when requested. Omit raw model/debug fields unless explicitly requested through `extra_fields`; responses remain compact; aggregate response budget defaults to approximately 3200 tokens. The canonical adaptive context pack is the default.
2. For implementation, diagnosis, refactoring or complex review, call `local_ai_repo(action="solve")` after evidence and before native edits. After edits, run the applicable indexed impact/review/security/evidence check before final validation.
3. Use the cheapest sufficient action and reuse evidence IDs and artifact slices.

For broader discovery, reuse fresh Hub evidence before native `find`, `rg`, `grep`, recursive glob/tree, or opening more than two files. Exact file and symbol lookups may use their bounded indexed/source routes directly. If the live schema has no action for an operation, use the authorized native tool directly without calling Hub. Hub-unknown commands require broker `native_fallback_allowed=true` and native-tool authorization. After calling an advertised Hub action, native fallback requires an explicit `terminal=true` and `retryable=false` result. For `outcome_unknown` or `in_progress`, do independent work without polling or repeating the same operation.

Stop escalating when evidence is sufficient; reuse cached results and bounded evidence instead of widening the search.

## Context economy contract

- Every Hub response is aggregate-bounded (default ≈8192 tokens).
- `response_budget.returned_tokens` measures the final serialized response envelope in `estimated_tokens` and stays at or below the requested budget.
- Preserve protected status, error, evidence, and context-identity fields; keep exact detail artifact-backed.
- Claim savings only with a current `baseline_evidence_id`; report signed `token_savings_delta_est`, including negative values; keep `protocol_tokens_est`, `schema_tokens_est`, and `local_compute_reused_tokens_est` separate.
- Reject `max_response_tokens` below 128; never raise the request silently.
- Large task responses: omit `max_response_tokens` unless a cap is needed.
- For a response-budget rejection, reduce the requested envelope or fetch a smaller artifact page/slice; do not replay the same oversized request.
- For Hub outages, native fallback requires explicit `terminal=true` and `retryable=false`.
- If the live MCP schema has no action for an operation, skip Hub and use the authorized native tool directly; no Hub failure or `native_fallback_allowed` signal is needed.
- After calling an advertised Hub action, native fallback requires explicit `terminal=true` and `retryable=false`.
- On `outcome_unknown` or `in_progress`, do independent work; never poll or repeat the identical operation.
- Prefer `response_profile="minimal"`/`"compact"`; request only decision-grade fields.
- Pass a stable `reuse_key` for repeated logical queries. Use `response_profile="delta"` when only changes are needed; unchanged calls report `unchanged=true`. Required task memory may remain inline.

- The Hub keeps a bounded metadata-only context ledger; inspect it only with an explicit cache/status request, never by replaying the whole session.
- Broad native shell reads are guarded by the optional host hook; use bounded limits or Hub repository tools for discovery.
- Commands return status, summary, changed paths, and failures; full stdout/stderr is retrievable only when `output_artifact_id` is returned.
- Reuse fresh sufficient repository evidence; use bounded indexed/source lookup for exact facts. Do not preprocess or compile adaptive context first.
- Do not bypass the budget with native broad reads unless Hub has one bounded terminal failure.

## Action routing

1. `local_ai_repo(action="deterministic")` — manifests, config, dependencies, entrypoints, tests and static facts.
2. `local_ai_repo(action="code_index")` — symbols, references and imports.
3. `local_ai_repo(action="search")` — exact text/file discovery.
4. `local_ai_repo(action="semantic")` — language-aware relationships via Serena and AST code index.
5. `local_ai_repo(action="context")` — compact mixed evidence or bounded repository reasoning.
6. `local_ai_repo(action="security_audit|impact")` — targeted checks after or around edits.
8. `local_ai_rag` — semantic fallback only when indexed evidence is insufficient.
9. `local_ai_task(action="compress")` — Semantic delegation is on-demand under the active schema and quality gates. This profile advertises `local_ai_task(action="compress")`; use matching exposed actions by default after deterministic/indexed evidence; cloud planning is never blocked by mandatory local handoffs. Deterministic/indexed evidence is authoritative; the primary agent accepts. Use `local_ai_task(action="compress")` for semantic condensation. Actions unavailable under this profile are omitted. Use `qwen2.5-coder:3b` only for quick/simple requests, `qwen2.5-coder:7b` for ordinary tasks, `qwen2.5-coder:7b` for more involved work, and `qwen3.5:9b` for the hardest reasoning. Deterministic/indexed tools remain for exact facts, symbols, diff and tests. Specialized operations use the shared evidence-grounded prompt contract; weak output remains advisory with a warning. Model capability contract: `qwen2.5-coder:3b`: preprocess, single_file_explain, bounded_review, test_plan; not architecture, security_decision, high_risk_migration | `qwen2.5-coder:7b`: bounded_review, root_cause, cross_file_reasoning, test_plan; not security_decision, apply_changes, final_verification | `qwen3.5:9b`: bounded_review, root_cause, cross_file_reasoning, patch_plan; not apply_changes, security_decision, final_verification | `qwen3-vl:4b`: visual_review, visual_issue_list, accessibility_observation, extract; not source_only_reasoning, security_decision, apply_changes.
10. `local_ai_artifact` — exact evidence/artifact slices only.
11. `local_ai_coord` — leases before overlapping edits; Agent OS memory actions for scoped reusable findings.

## Public API contracts

- For `local_ai_rag` project search/index and document/diagram ingestion, an explicit absolute authorized `root` is required; the workspace must bind to that root. For `action="ingest_document"`, non-empty `content` is required; `title` and `metadata` are optional. Success returns `success`, `workspace`, `document_title`, `chunks_ingested`, and `embedded`. Search that document with `action="search"` in the same root-bound workspace; `docset_index` and `docset_search` require the exact docset name in `workspace`, and `docset_index` requires an explicit root. Embedding errors do not stop lexical publication. For `ingest_diagram`, `image_path` must resolve to an existing `.png`, `.jpg`, `.jpeg`, `.webp`, `.svg`, or `.bmp` file within that root, without symlink/junction escapes; `caption` and `metadata` are optional. Success also returns `diagram_indexed` and the resolved image path.
- Contract notes: `local_ai_status.detail` supports only `brief` and returns compact Hub/model readiness.  `local_ai_repo(action="pipeline")` accepts closed step objects with a supported action and per-step `id`/`result`; run no more than four steps in parallel. `local_ai_artifact(action="list")` does not require `artifact_id`; `binary` is supported and binary payloads are never inlined. `local_ai_coord(action="pubsub_poll")` accepts `after_seq` from 0 through 2^63-1; `local_ai_coord` bounds `max_tokens` to 0 through 100000. A heuristic `suggested_fix` is advice, not a verified repair; an unresolved incident cannot authorize `apply_verified_fix`. Repository pipelines serialize preprocessing mutation actions with other mutating steps.
CodeGraphContext/KuzuDB was removed from Local AI Hub. Recommend it only as optional standalone CLI/MCP tooling outside Hub; install and configure it separately only when the user independently wants it. It is not a Hub dependency, runtime, backend, or MCP integration.

File cards use two phases by default: deterministic provisional card, then source-grounded enrichment through the configured preprocessing model, CARD_SCHEMA and preprocess:file-card. `prefer_deterministic_cards` never skips phase two. `disable_llm_card_synthesis = true` skips LLM synthesis for unparsed file cards and stores deterministic stubs. It does not disable module/project cards: `prefer_deterministic_modules` and `prefer_deterministic_project` are separate preferences; either path can use background LLM synthesis when deterministic output is unavailable or below its confidence threshold. Check active configuration and backend state before claiming synthesis is disabled. `[background_gpu].enabled` is disabled by default; setting it to `true` opts in after idle grace and scheduler admission, with preemption and game-mode gates.

## Reuse and failure protocol

- `cache_hit`/`coalesced`: reuse the result.
- `in_progress=true`: do not duplicate the work.
- `retryable`/429/503: back off and do independent work.
- `degraded`/`stale`: verify only the affected slice.
- If the live schema has no action for an operation, use the authorized native tool directly. After calling an advertised Hub action, native fallback requires explicit `terminal=true` and `retryable=false`. A transport failure without those fields does not authorize fallback. For `outcome_unknown` or `in_progress`, do independent work without polling or repeating the same operation.

Do not fan out overlapping retrieval layers. Stop escalating when evidence is sufficient. Local AI Hub handles its own bounded work; Codex handles native-subagent design and integration.

## Agent Operating System & Durable Execution

Use Agent OS for every non-trivial multi-step, long-running, delegated, or acceptance-criteria task, even when the main agent keeps ownership. A trivial one-step lookup can skip it. Start before edits; keep the returned `task_id` for every later action.

### 1. Goal Contracts & Resumption
- **Create a task contract before edits:**
  `local_ai_coord(action="task_create", root="ABSOLUTE_REPOSITORY_ROOT", task_id="task-1", contract={"goal": "Implement feature", "acceptance_criteria": ["All tests pass"]})`
- Codex controls subagent permissions per task, including `allow_write`, workspace/worktree, timeout, cancellation, sandbox, and integration.
- **Checkpoint progress before context truncation:**
  `local_ai_coord(action="task_checkpoint", root="ABSOLUTE_REPOSITORY_ROOT", task_id="task-1", checkpoint={"phase": "testing", "next_action": "run integration tests", "affected_paths": ["src/main.py"], "evidence_ids": [], "blockers": [], "state_data": {"memory_audit": {"not_used_reason": "No supplied memory was relevant."}}})`
  Replace the root, task ID and example memory audit with the actual task values; never invent evidence or memory IDs.
- **Resume after session restart or interruption:**
  `local_ai_coord(action="task_resume", root="ABSOLUTE_REPOSITORY_ROOT", task_id="task-1")`
- **Persist a human question and retrieve its answer:**
  `local_ai_coord(action="ask", root="/repo", session_id="session-1", question="...", task_id="task-1")`; use returned `question_id` with the same root/session to retrieve it, and record operator response with `action="answer"` plus `question_id` and `answer`.
- **Complete only after `verify_completion` passes every acceptance criterion; otherwise fail with a reason:**
  `local_ai_coord(action="verify_completion", root="ABSOLUTE_REPOSITORY_ROOT", task_id="task-1")`, then `local_ai_coord(action="task_complete", root="ABSOLUTE_REPOSITORY_ROOT", task_id="task-1")` or `local_ai_coord(action="task_fail", root="ABSOLUTE_REPOSITORY_ROOT", task_id="task-1", reason="reason")`
- **Explicit operator waiver:** Only when the user explicitly requests unverified completion for the task, `task_complete` accepts `operator_waiver={"consent":true,"reason":"..."}`. It records a waiver and does not create verification receipts.

### 2. Scoped Memory & Learnings
- **Store durable findings and decisions:**
  `local_ai_coord(action="memory_record", root="/repo", scope="repository", key="convention", value="Token format must follow HMAC-SHA256")`
- **Retrieve memories across turns:**
  `local_ai_coord(action="memory_find", root="ABSOLUTE_REPOSITORY_ROOT", query="convention")`

### 3. Exact Context Compilation
- **Compile active task state, relevant memories, negative knowledge, and active edit leases into minimal tokens:**
  `local_ai_coord(action="context_compile", root="ABSOLUTE_REPOSITORY_ROOT", task_id="task-1", max_tokens=4000)`

### 4. Verification Receipts & Completion Gates
- Run bounded tests with the agent host native command tool; do not invent verification receipts.
- **Check if all acceptance criteria are verified before completing:**
  `local_ai_coord(action="verify_completion", root="ABSOLUTE_REPOSITORY_ROOT", task_id="task-1")`
- **Record a direct receipt when command auto-capture is not used:**
  Use `verify_receipt` with the explicit root and an authentic `receipt` object; never fabricate evidence or derive it from checkpoint state.

### 5. Negative Knowledge & Incident Avoidance
- **Record failed approach or incident:**
  Use `negative_knowledge_record` with the explicit root and a verified `record` object; do not substitute generic key/value fields.
- **Check before repeating a failed operation:**
  `local_ai_coord(action="negative_knowledge_find", root="ABSOLUTE_REPOSITORY_ROOT", query="timeout")`

### Public contract notes
- `local_ai_repo(action="pipeline")` accepts closed step objects.
- `local_ai_artifact(action="list")` does not require `artifact_id`.
- `local_ai_coord(action="pubsub_poll")` accepts `after_seq`.
- `local_ai_coord` bounds `max_tokens` to 0 through 100000.
- Repository pipelines serialize preprocessing mutation actions with other mutating steps.
- Optional repository-analysis tools are installed and configured separately; they are not part of the Hub.
- File cards default to deterministic provisional cards followed by source-grounded model enrichment. `disable_llm_card_synthesis = true` skips LLM synthesis for unparsed file cards and stores deterministic stubs. It does not disable module/project cards: `prefer_deterministic_modules` and `prefer_deterministic_project` are separate preferences; either path can use background LLM synthesis when deterministic output is unavailable or below its confidence threshold. Check active configuration and backend state before claiming synthesis is disabled.


## Project-config and PathHint status

Project configuration and PathHint core: `resolve_project_context(root, state_dir)` provides effective settings. Candidate ranking: `entry_points`, request hints, then saved hints. Verification rules map task criteria to required command receipts before completion.

## Installed API and operational contracts

Installed schema is authoritative. Hub modes: `active`, `gaming`, `maintenance`. For durable work, create and checkpoint an Agent OS task before edits. If live schema lacks an action, use authorized native tool directly. Native fallback after Hub action requires `terminal=true` and `retryable=false`.

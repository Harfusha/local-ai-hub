# MCP routing card

The active tool surface reflects your configuration:

- `local_ai_repo`: deterministic, code index/search, semantic, context/solve, preprocess, impact, review_diff, security_audit, patch validation and repository checks.
- `local_ai_work`: bounded implementation for explicit closed delegation after `features.bounded_local_work=true` and task-specific evaluation; caller-defined scope, permissions and limits plus primary-agent review and integration remain required.
- `local_ai_task`: exposed local actions (delegate|explore|reason|continue|review|second_opinion|compress|route|batch|benchmark|hardware_benchmark|evaluation_record|evaluation_report|submit|status|wait|result|cancel|candidate_create|candidate_promote|speculative_draft|vision|transcribe|browser|eval_suite|prompt_eval|eval_drift|complete_code|scaffold|automation), including semantic generation, review, independent second opinions, semantic compression; follow the active profile and verify model availability. Use deterministic/indexed tools for exact facts, symbols, diff and tests.
- `local_ai_repo(action="solve")` preserves one bounded local pass for explicit semantic requests even when exact evidence is strong.
- `local_ai_rag`: semantic fallback only after deterministic/indexed retrieval.
- `local_ai_artifact`: exact `E...` evidence or artifact slices.
- `local_ai_coord`: edit leases, Agent OS task lifecycle, scoped memory/relations, context, verification, negative knowledge, and coordination primitives.
- `local_ai_status`: bounded health/cache/telemetry/debug-trace, Agent OS task/incident state inspection; no polling loops.
- For semantic task triggers and action-specific input fields, follow the required contract in Action routing above.

## Categorized Operational Triggers (Prioritize over shell / raw reads)

### 1. Code Navigation & AST Discovery (`local_ai_repo`)
- **Callers & Inbound References**: Trace callers across codebase -> `local_ai_repo(action="callers", query="<name>", root=ABS_ROOT)`
- **Callees & Outbound Calls**: Trace function dependencies -> `local_ai_repo(action="callees", query="<name>", root=ABS_ROOT)`
- **AST Outline**: Class/function signature summary without dumping source -> `local_ai_repo(action="ast_outline", path="<relpath>", root=ABS_ROOT)`
- **Declarations & Implementations**: Find declarations/subclasses -> `local_ai_repo(action="declaration"|"implementations", query="<name>", root=ABS_ROOT)`
- **Structural AST Search**: Query code patterns by syntax -> `local_ai_repo(action="structural_search", query="<pattern>", root=ABS_ROOT)`
- **Fast Symbols & Text**: Bounded symbols/lexical search -> `local_ai_repo(action="code_index"|"search", query="<term>", root=ABS_ROOT)`

### 2. Impact Analysis & Test Scaffolding (`local_ai_repo`)
- **Affected Tests**: Pinpoint tests impacted by a changed file -> `local_ai_repo(action="affected_tests", path="path/to/file.py", root=ABS_ROOT)`
- **Refactoring Blast Radius**: Evaluate symbol usage before edits -> `local_ai_repo(action="refactor_impact", query="<name>", root=ABS_ROOT)`
- **Test Generation**: Scaffold test cases for diff or file -> `local_ai_repo(action="generate_tests_for_diff", root=ABS_ROOT)`

### 3. Code Health, Auditing & Security (`local_ai_repo`)
- **Security & Secret Scan**: Audit code for CVEs, credentials, and risks -> `local_ai_repo(action="security_audit", root=ABS_ROOT)`
- **Dead Code Detection**: Find unused functions and unreachable code -> `local_ai_repo(action="dead_code", root=ABS_ROOT)`
- **Circular Dependencies**: Detect module import loops -> `local_ai_repo(action="circular_dependencies", root=ABS_ROOT)`
- **Complexity & Churn Hotspots**: Rank high-complexity and hotspot files -> `local_ai_repo(action="complexity", root=ABS_ROOT)`

### 4. Git Inspection & Commits (`local_ai_repo`)
- **Git Status & Diffs**: Inspect working tree state without shell git -> `local_ai_repo(action="git_status"|"git_diff", root=ABS_ROOT)`
- **Synthesize Commit**: Draft standardized commit message from verified diff -> `local_ai_repo(action="synthesize_commit", root=ABS_ROOT)`

### 5. Planning & Agent OS Coordination (`local_ai_coord`)
- **Mandatory First Entrypoint**: Inspect active plan, status and `spec_refs` -> `local_ai_coord(action="plan_board_view"|"plan_list", root=ABS_ROOT)`
- **Milestone Progress**: Record checkpoint with affected paths -> `local_ai_coord(action="task_checkpoint", task_id="...", checkpoint={...})`
- **Project Memory**: Query or store verified project learnings -> `local_ai_coord(action="memory_find"|"memory_record", root=ABS_ROOT, ...)`
- **Negative Knowledge**: Check known failure modes before repeating mistakes -> `local_ai_coord(action="negative_knowledge_find", query=...)`

### 6. Semantic Tasks & Review (`local_ai_task`)
- **Adversarial Code Review**: Skeptical review of changes before commit -> `local_ai_task(action="review", ...)`
- **Local Reasoning / 2nd Opinion**: Bounded local reasoning or alternative perspective -> `local_ai_task(action="reason"|"second_opinion", ...)`
- **Evidence Compression**: Compress voluminous logs/evidence -> `local_ai_task(action="compress", ...)`

### 7. Exact Slices & Artifacts (`local_ai_artifact`)
- **Bounded File Slice**: Read line ranges without full-file dumping -> `local_ai_artifact(action="slice", path="<relpath>", start_line=N, end_line=M, root=ABS_ROOT)`
- **Exact Source**: Use `action="source"` with explicit absolute `root=ABS_ROOT` and `path="<relpath>"`; source roots are never inferred.



## Agent OS trigger and lifecycle

Use this for non-trivial multi-step, long-running, delegated, or acceptance-criteria work, even when the main agent retains ownership. Create a task contract before edits, keep the returned task ID, checkpoint phase changes, compile context when resuming or when state is scattered, and attach validation receipts. Run `verify_completion` before `task_complete`. Trivial one-step lookups can skip this workflow.


## Context economy contract

- Preserve protected status, error, evidence, and context-identity fields; keep exact detail artifact-backed.
- Reject `max_response_tokens` below 128; never raise the request silently.
- Large task responses: omit `max_response_tokens` unless a cap is needed.
- If a requested response is too large, fetch a smaller artifact page/slice; do not repeat the same oversized request.
- For Hub outages, native fallback requires explicit `terminal=true` and `retryable=false`.
- If the live MCP schema has no action for an operation, skip Hub and use the authorized native tool directly; no Hub failure or `native_fallback_allowed` signal is needed.
- After calling an advertised Hub action, native fallback requires explicit `terminal=true` and `retryable=false`.
- On `outcome_unknown` or `in_progress`, do independent work; never poll or repeat the identical operation.
- Prefer `response_profile="minimal"`/`"compact"`; request only decision-grade fields.
- Pass a stable `reuse_key` for repeated logical queries. Use `response_profile="delta"` when only changes are needed; unchanged calls report `unchanged=true`. Required task memory may remain inline.
- Use `local_ai_task(action="batch")` for bounded independent tasks.
- The Hub keeps a bounded metadata-only context ledger; inspect it only with an explicit cache/status request, never by replaying the whole session.
- Broad native shell reads are guarded by the optional host hook; use bounded limits or Hub repository tools for discovery.
- Commands return status, summary, changed paths, and failures; full stdout/stderr is retrievable only when `output_artifact_id` is returned.
- Reuse fresh sufficient repository evidence; use bounded indexed/source lookup for exact facts. Do not preprocess or compile adaptive context first.
- Do not bypass the budget with native broad reads unless Hub has one bounded terminal failure.

    Keep assignments bounded. The main agent retains final acceptance; The main agent owns planning, edits, review, validation and final integration.

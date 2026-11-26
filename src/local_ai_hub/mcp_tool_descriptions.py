from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any


def describe_status(specialized_note: Callable[[str], str]) -> str:
    return (
        "Compact Hub and local-model readiness: online state, active model, and VRAM pressure. detail supports only brief."
        " Use once when Hub or local inference availability affects the next action; skip routine checks."
        f"{specialized_note('local_ai_status')}"
    )


def describe_rag(
    features: Any,
    lean_schemas: bool,
    actions_note: Callable[[tuple[str, ...]], str],
    specialized_note: Callable[[str], str],
) -> str:
    if lean_schemas:
        return (
            "Semantic RAG and documentation search with aggregate-bounded responses; response controls: max_response_tokens, response_profile (minimal, compact, delta), reuse_key, extra_fields for additional safe response fields. Actions: search, index, list, docset_index, docset_search, ingest_document, ingest_diagram."
            " Project search/index and ingestion require an explicit absolute authorized root and root-bound workspace. Search ingested documents with action=search in that workspace; docset_index and docset_search require the exact non-empty docset name in workspace, with no default. docset_index also requires root. Document ingestion requires non-empty content; diagram files stay inside that root."
            " Use when: cheaper indexed repository paths cannot answer a bounded semantic retrieval question."
            " Skip when: deterministic/indexed evidence is sufficient or RAG is disabled."
        )
    if not features.rag:
        return (
            "Semantic retrieval — RAG backend is disabled on this installation (`features.rag=false`)."
            " All actions return unsupported=true. Enable RAG in config.toml to activate."
            " Skip when: always (RAG disabled). Use when: never."
        )
    return (
        "Fallback semantic retrieval for the main agent only after deterministic, code_index, search"
        " and preprocessed evidence are insufficient."
        " Keep queries bounded and use it only for bounded semantic retrieval, not open-ended agent orchestration."
        f"{actions_note(features.supported_rag_actions())}"
        f"{specialized_note('local_ai_rag')}"
        " Response controls: max_response_tokens; response_profile minimal|compact|delta; reuse_key; extra_fields selects additional safe response fields retained by the compact projector."
        " Index is file-incremental and query-cached."
        " Do not trigger index repeatedly for a fresh stable workspace."
        " Use when: cheaper indexed repository paths cannot answer a bounded semantic retrieval question."
        " Skip when: deterministic/indexed evidence is sufficient. Native subagent ownership does not affect direct retrieval endpoint use."
        " Project search/index and ingestion require an explicit absolute authorized root and root-bound workspace. Search ingested documents with action=search in that workspace; docset_index and docset_search require the exact non-empty docset name in workspace, with no default. docset_index also requires root. Document ingestion requires non-empty content; diagram files stay inside that root."
    )


def describe_task(
    features: Any,
    lean_schemas: bool,
    actions_note: Callable[[tuple[str, ...]], str],
    semantic_handoff_contract: Callable[[bool, bool], str],
    specialized_note: Callable[[str], str],
) -> str:
    local_enabled = features.tasks and features.has_any_model()
    supported_actions = features.supported_task_actions()
    semantic_actions = set(supported_actions) & {
        "delegate", "explore", "reason", "review", "second_opinion", "compress"
    }
    action_note = actions_note(tuple(supported_actions))
    semantic_labels = []
    if semantic_actions & {"delegate", "explore", "reason"}:
        semantic_labels.append("semantic generation, exploration and reasoning")
    if "review" in semantic_actions:
        semantic_labels.append("review")
    if "second_opinion" in semantic_actions:
        semantic_labels.append("independent second opinions")
    if "compress" in semantic_actions:
        semantic_labels.append("semantic compression")
    semantic_summary = ", ".join(semantic_labels)
    semantic_inputs = {
        "delegate": '`delegate`: `task`',
        "explore": '`explore`: `task`',
        "reason": '`reason`: `problem` and concise `context`',
        "review": '`review`: `code` and optional review instruction in `task`',
        "second_opinion": '`second_opinion`: `question` with candidate/evidence in `context`',
        "compress": '`compress`: source in `text`, optional instruction in `task`',
    }
    semantic_input_note = (
        " Action-specific inputs: "
        + "; ".join(semantic_inputs[action] for action in ("delegate", "explore", "reason", "review", "second_opinion", "compress") if action in semantic_actions)
        + "."
        if semantic_actions else ""
    )
    benchmark_hints = []
    if "benchmark" in supported_actions:
        benchmark_hints.append("`benchmark` reads stored results only")
    if "hardware_benchmark" in supported_actions:
        benchmark_hints.append(
            "`hardware_benchmark` accepts `model`, `prompt`, `max_tokens`, and `context_tokens` (4096–32768), but no `timeout_seconds`"
        )
    benchmark_note = f"Action inputs are strict: {'; '.join(benchmark_hints)}. " if benchmark_hints else ""
    if not local_enabled:
        return (
            "Local inference is disabled on this installation for this tool."
            " Returns unsupported=true for local-model actions."
            " Use deterministic/indexed evidence only."
            " Use when: a bounded semantic task requires a local model backend."
            " Skip when: the task is trivial, pure evidence lookup, security/privacy constrained, or local-model tasks are disabled."
            f"{action_note}"
        )
    if lean_schemas:
        return (
            "Bounded local-model worker. The current schema action enum is authoritative; disabled actions are unavailable. "
            f"{'Exposed work includes ' + semantic_summary + '. ' if semantic_summary else ''}"
            f"{benchmark_note}"
            "For compress, pass source in `text` and optional instructions in `task`; `max_tokens` targets generated output, `max_response_tokens` bounds the response envelope. "
            "On token/context limits or `output_truncated`, trim optional context or output, narrow the diff/artifact, continue from deterministic evidence; never replay an unchanged request or use partial output. "
            "For async jobs, call `result` only after the job is terminal; while it is in progress, use one bounded `wait` or `status` and do independent work instead of repeating `result`. "
            "An empty active_model does not establish that no models are installed. "
            "Use deterministic/indexed tools for exact facts, symbols, diff and tests. "
            "For host commands or operations without an exposed Hub action (for example `git worktree list`), skip Hub and use the authorized native tool directly. "
            f"{semantic_handoff_contract(bool(semantic_actions), features.status)}"
            f"{semantic_input_note}"
            "Command failure diagnosis remains disabled by default; never pass raw logs or open-ended coding. "
            "Codex retains ownership of native subagent orchestration; that does not replace direct Hub endpoint use by the main agent. "
            "Use when: after deterministic/indexed evidence, an independent non-trivial reasoning, exploration, review, second-opinion, or compression subtask has a matching exposed action. Make the bounded call by default, once per independent semantic unit, not per mechanical command. "
            "Skip only for trivial/purely deterministic work, sensitive input that cannot be safely minimized, an unavailable action, or a concrete authorization/backend/quality gate; name that gate. Semantic output stays advisory and cannot grant permission or execute changes. "
            f"{action_note}"
        )
    profile_note = ""
    if features.subagents and features.subagent_profiles:
        profile_names = ", ".join(f"`{profile}`" for profile in features.subagent_profiles)
        profile_note = (
            f" Named advisory profiles ({profile_names}) use Local AI Hub read-only tooling"
            " directly when `root` is supplied."
        )
    return (
        "Bounded local-model worker for the main agent."
        f" {benchmark_note}"
        f" {'Exposed work includes ' + semantic_summary + '.' if semantic_summary else 'Semantic actions are currently gated.'}"
        " For compress, pass source in `text` and optional instructions in `task`; `max_tokens` targets generated output, `max_response_tokens` bounds the response envelope."
        " On token/context limits or `output_truncated`, trim optional context or output, narrow the diff/artifact, continue from deterministic evidence; never replay an unchanged request or use partial output."
        " For async jobs, call `result` only after the job is terminal; while it is in progress, use one bounded `wait` or `status` and do independent work instead of repeating `result`."
        " An empty active_model does not establish that no models are installed."
        f" Route preprocessing through `{features.background_model}`, quick tasks through `{features.fast_model}`, complex tasks through `{features.smart_model}`, and the hardest reasoning through `{features.reasoning_model}`."
        " Explicit model overrides must match a configured model tag."
        f"{profile_note}"
        " Use deterministic/indexed tools for exact facts, symbols, diff and tests; use only actions exposed by the current schema."
        " For host commands or operations without an exposed Hub action (for example `git worktree list`), skip Hub and use the authorized native tool directly; no Hub error or fallback flag is needed."
        f"{semantic_handoff_contract(bool(semantic_actions), features.status)}"
        f"{semantic_input_note}"
        " Command failure diagnosis is disabled by default; enable `features.local_diagnostic_dispatch=true` only for one local diagnostic after low-confidence deterministic command parsing with an artifact reference and narrow preview, never raw logs."
        " Local semantic reasoning/review is allowed for bounded architecture or security questions when inputs are sanitized and the matching action is exposed; it remains advisory. Never let the model execute mutations, bypass approval, perform host commands, or replace deterministic validation. Open-ended coding stays with the primary agent unless a separately authorized bounded code action is exposed."
        " Codex manages native subagents directly; the main agent still calls Hub endpoints when applicable, and a Hub call does not imply delegation."
        f"{action_note}"
        f"{specialized_note('local_ai_task')}"
        " `delivery=sync` preserves the foreground contract; `async` returns a durable job now;"
        " `auto` requires a positive `latency_budget_ms` and only defers after sufficient endpoint history shows p95 above it."
        " Evaluation stores only opaque ids, booleans, and numeric metadata; it never stores prompts or source text."
        " Async wait is bounded to 90 seconds; never poll loops."
        " Start a short-lived conversation with `conversation=true` on delegate or reason, then use `continue` with its opaque `conversation_id`; conversations are sync-only and process-memory only."
        " Use when: after deterministic/indexed evidence, a matching exposed semantic action fits an independent non-trivial subtask; call by default and once per independent semantic unit."
        " Skip only for trivial/purely deterministic work, sensitive input that cannot be safely minimized, unavailable action, or a concrete authorization/backend/quality gate; state the gate."
    )


def describe_work(
    features: Any,
    lean_schemas: bool,
    action_lookup: Callable[..., Sequence[str]],
    specialized_note: Callable[[str], str],
) -> str:
    actions = action_lookup("local_ai_work", features)
    submit_enabled = "submit" in actions
    bounded = ""
    if submit_enabled:
        bounded = (
            " For bounded mode, use only for explicit closed delegation when profile high is active and task-specific model quality is evaluated."
            " Supply exact allowed files, approved commands, permissions, finite time and acceptance criteria."
            " The primary agent must review the diff, actual tests and integration; a handoff is not task completion."
            " For work owned by the responding process, timed_out=true with in_progress=true is not a terminal result or permission to retry; cancellation is cooperative."
        )
    action_note = f" Actions: {', '.join(actions)}." if actions else " No actions are enabled."
    intro = (
        "Delegate one closed, low-risk work item to Local AI Hub and return a compact handoff."
        if submit_enabled
        else "Manage existing Local AI Hub work; new submissions are unavailable under the active profile or quality gates."
    )
    if lean_schemas:
        suitability = " Use only for self-contained repository outcomes; skip micro-edits and live discussion." if submit_enabled else ""
        use_when = (
            " Use when: submitting a qualified closed work item or checking its existing handoff."
            if submit_enabled
            else " Use when: checking, waiting on, retrieving, or cancelling existing work."
        )
        skip_when = " Skip when: the task is micro-edits/live discussion, requires an unresolved decision, or submission gates are unmet."
        return intro + bounded + suitability + use_when + skip_when + f"{specialized_note('local_ai_work')}" + " Common controls: max_response_tokens, response_profile (minimal, compact, delta), reuse_key, extra_fields for additional safe response fields. Work projection controls: return_fields selects top-level fields; max_output_tokens bounds handoff text; work profiles are minimal, compact, standard, debug." + action_note
    return (
        intro
        + bounded
        + action_note
        + " Common response controls: max_response_tokens, response_profile=minimal|compact|delta, reuse_key, extra_fields; work projection profile=minimal|compact|standard|debug; return_fields selects only needed top-level fields; "
        + "max_output_tokens bounds the handoff while full details remain artifact-backed. Use when: the task can be delegated as a self-contained repository outcome. "
        + "Skip when: the agent must make an unresolved product decision, credentials/network are required, only one tiny lookup is needed, or work is micro-edits/live discussion."
        + specialized_note("local_ai_work")
    )


def describe_artifact(
    lean_schemas: bool,
    action_lookup: Callable[[str], Sequence[str]],
    specialized_note: Callable[[str], str],
) -> str:
    if lean_schemas:
        actions = ", ".join(action_lookup("local_ai_artifact"))
        return (
            f"Fetch an exact source or log slice or bounded binary artifact metadata; binary retrieval never inlines payloads; optional max_response_tokens, response_profile, reuse_key. Actions: {actions}."
            " Source: action=source requires explicit absolute root and path plus optional line_start/line_end; root-confined, file/range/output bounded with SHA-256 provenance."
            " Use when: exact source or evidence text is required after indexed discovery."
            " Skip when: no source slice is needed or the existing compact result is sufficient."
            f"{specialized_note('local_ai_artifact')}"
        )
    return (
        "Fetch one exact source or log slice or bounded binary artifact metadata. Source reads require an explicit absolute root and path. Binary payloads are never inlined in MCP responses. Evidence IDs start with E."
        " Use when: exact source or evidence text is required after indexed discovery."
        " Skip when: no source slice is needed or the existing compact result is sufficient."
        f"{specialized_note('local_ai_artifact')}"
    )


def describe_coord(
    features: Any,
    lean_schemas: bool,
    actions_note: Callable[[tuple[str, ...]], str],
    plan_coord_note: Callable[[], str],
    specialized_note: Callable[[str], str],
) -> str:
    supported = set(features.supported_coord_actions())
    argument_note = (
        " Action arguments are strict despite the shared schema: `plan_list` requires `root` and defaults to five results; set `limit` or narrow with `query` for a bounded wider lookup; `plan_get` requires `root` and `plan_id`; for large plans prefer `plan_board_view` with the exact task ID; after a response-budget rejection, narrow the query or page, or raise `max_response_tokens` for the same exact-task read; never replay the unchanged oversized request or repeat the same rejected cap;"
        " `task_checkpoint` requires `root`, `task_id`, and `checkpoint`; use the Agent OS `task_id` returned by `task_create` for the same root, never a plan task ID. When supplied memory has items or warnings, `checkpoint.state_data.memory_audit.used_ids` must list IDs actually used; if none were used, `checkpoint.state_data.memory_audit.not_used_reason` must be nonempty. A reason elsewhere fails validation. Omit `max_response_tokens` unless the complete memory receipt is known to fit. A budget rejection means persistence did not start; do not replay the same capped request."
        " `task_create` requires a `contract` object with a non-empty `goal`; scope belongs inside the contract, and `in_progress` is not a task status. `plan_task_edit.task_id` must be the exact ID from `plan_board_view`, never a title or slug. `plan_bind_task` requires an execution task with a persisted real `session_id`; do not invent one or bind before persistence."
        " `plan_task_edit` requires `root`, `plan_id`, `task_id`, `task_data`, and `expected_revision`;"
        " `task_data` accepts only title, description, kind, work_status, depends_on, clarifications, acceptance_criteria, next_action, blocker, order, accountable_role, work_phase, spec_refs, scope, results, and deliveries; it has no free-form `notes` field."
        " On a revision conflict, reload with `plan_get`, reapply the intended changes, and use its current revision; never resend the stale payload. If a `plan_task_edit` response has `mutation_applied=true` with `projection_incomplete` or a response-budget error, the edit already happened: do not retry it; read the current plan and verify its `file_revision` matches before another edit. Omit `blocker` when there is no blocker, and `clarifications` entries must be objects, not strings."
        " `plan_board_view` requires `root`, takes `plan_id`, and uses `query` for the exact task ID. Do not send generic `phase` or `summary`."
        " `plan_reconcile_steering` requires a matching persisted task session; pass `task_id`, `steering_id`, current `expected_revision` and `expected_spec_revision`, `spec_rel_path`, `spec_content`, and `acceptance_criteria` (`summary` is optional). Do not call it before the real task/session binding exists."
        " For plan data, `lifecycle` is draft|active|paused|completed|cancelled|archived; each `spec_refs` item needs `path` and a verified `revision` shaped as `{kind:'git_commit',commit:<40-or-64-lowercase-hex>}` or `{kind:'working',content_sha256:<64-lowercase-hex>}`; each `depends_on` item is `{plan_id,task_id}`. Do not invent revision hashes."
        " If no exposed coordination action covers the requested operation, skip Hub and use the authorized native tool directly; do not call a nearby Hub action to check support."
    )
    laya_note = (
        " Request-scoped typed Laya inference uses local_ai_coord(action='laya_decision', root, laya_operation={action:'evaluate_decision'|'evaluate_context_source'|'runtime_status', ...}) and POST /api/laya/decision. It does not require Agent OS or task_id; task_id is accepted only when a real task is supplied. Ordinary model-route, context-budget, retrieval-strategy, next-step, bounded-delegation, and subagent-budget advice requires current evidence verified for the authorized repository plus a server-derived deterministic baseline. Lifecycle, completion, and watchdog decisions still require a real task. Request-only decisions emit operational telemetry, not supervised candidates. Active routing accepts only validated low-risk advisory suggestions."
        " Repository solve and explicit decomposition requests may return subagent_budget advice: single_agent, parallel_split, or swarm, with single_agent deterministic baseline. The result is request-scoped metadata only and never launches agents or bypasses explicit delegation/profile gates."
        " For an unresolved context gap, evaluate_context_source uses laya_operation={action:'evaluate_context_source',evidence:{gap_code:'unresolved_evidence_gap',source_codes,freshness_codes,coverage_codes,evidence_ids,source_record_ids?,training_content?}}. Source/status/evidence arrays must align; taskless memory choices require matching repository-scoped source_record_ids, while task-scoped memory is available only with a verified task. Hub verifies repository, optional task/session, and evidence provenance. This result is advisory only: retrieve the selected source through its authorized path and keep host permission checks. Laya does not fetch sources or grant access."
        " curate_dataset remains for candidate capture and lifecycle; candidate creation requires an actual task and verified evidence."
        if "laya_decision" in supported else ""
    )
    if lean_schemas:
        actions = sorted(supported)
        reservation_note = (
            " GPU reservation status is owner-global and takes no root; gpu_reservation_release requires consent=true, generation and audit_reason, then expiry or confirmed owner death. gpu_reservation_release_authorized requires explicit consent=true and audit_reason, without a generation or owner-liveness preflight. It releases a valid reservation, including capacity leases for that exact generation, or records a durable operator-release marker when the reservation file is already missing, allowing the scheduler to clear only stale in-memory external admission. gpu_capacity_lease_release requires exact lease_id, owner, generation, consent=true and audit_reason; it releases only an unreserved Laya runtime lease after the owner PID is confirmed absent, with a durable audit entry. Other generations are preserved; release can interrupt GPU work using the released generation. Malformed metadata and symlinks remain fail-closed."
            if {"gpu_reservation_status", "gpu_reservation_release", "gpu_reservation_release_authorized", "gpu_capacity_lease_release"}.issubset(actions)
            else ""
        )
        scheduler_release_note = (
            " gpu_scheduler_capacity_lease_release requires exact scheduler-job lease identity, consent=true and audit_reason; it releases only a lease created before this Hub run when the matching job is absent and Ollama confirms no loaded runner. Probe failures, active jobs/runners, reservation-bound leases and changed generations fail closed; releases are audited."
            if "gpu_scheduler_capacity_lease_release" in actions else ""
        )
        purpose = (
            "Agent OS coordination for task contracts, ownership, checkpoints, and verification receipts"
            if features.agent_os else "Coordination for leases"
        )
        return (
            f"{purpose} with aggregate-bounded responses; optional max_response_tokens, response_profile, reuse_key."
            f"{actions_note(actions)}"
            f"{argument_note}"
            f"{reservation_note}"
            f"{scheduler_release_note}"
            f"{plan_coord_note()}"
            f"{laya_note}"
            " Use when: any non-trivial task benefits from durable state/verification, or Hub workers share edit paths or reusable findings."
            " Skip when: task is a trivial one-step lookup with no shared state to preserve."
            f"{specialized_note('local_ai_coord')}"
        )
    if features.agent_os:
        agent_os_note = (
            " For non-trivial multi-step, long-running, delegated, or acceptance-criteria work, create an Agent OS task contract first;"
            " checkpoint meaningful phases, search/record durable memory as useful, compile context when resuming,"
            " and gate task completion on verification receipts."
        )
        usage_note = (
            " Use when: any non-trivial task benefits from durable state/verification, or Hub workers share edit paths or reusable findings."
            " Skip when: task is a trivial one-step lookup with no shared state to preserve."
        )
    else:
        agent_os_note = ""
        usage_note = (
            " Use when: Hub workers share edit paths, leases, or reusable findings."
            " Skip when: work is isolated and no shared Hub state or memo is involved."
        )
    return (
        "Cross-agent coordination for ownership, checkpoints, and verification receipts."
        f"{actions_note(features.supported_coord_actions())}"
        f"{argument_note}"
        f"{plan_coord_note()}"
        f"{laya_note}"
        f"{agent_os_note}"
        " Claim overlapping edit paths before concurrent Hub work."
        " Use scoped Agent OS memory_find/memory_record for reusable findings; workspace memo actions are operator-only and unavailable through this tool."
        " Native peer subagents are coordinated by Codex rather than by this Hub tool."
        f"{usage_note}"
        f"{specialized_note('local_ai_coord')}"
    )


def describe_repo(
    features: Any,
    lean_schemas: bool,
    tier_repo_description: Callable[[str], str],
    actions_note: Callable[[tuple[str, ...]], str],
    semantic_handoff_contract: Callable[[bool, bool], str],
    specialized_note: Callable[[str], str],
) -> str:
    local_enabled = features.tasks and features.has_any_model()
    argument_note = (
        " Action arguments are strict despite the shared schema: `solve` takes `task`, `context` takes `query`,"
        " `find_symbol` takes `query` with optional `limit`/`offset` like `code_index`; `definition` requires `query` and accepts optional `path` like `declaration`; `git_diff` takes `path` or revision fields;"
        " `solve` accepts only `root`, `task`, `workspace`, `mode`, `max_tokens`, `base`, `staged`, and optional real Agent OS `task_id`. Do not pass `phase`, `focus`, `evidence`, or `context` to `solve`; put the complete semantic request in `task`."
        " do not pass `focus` or `changed_paths` unless that action allows them."
        " Laya automatically advises eligible repository solve/delegate/review/reason/second_opinion/review_diff/generate_tests/speculative_draft requests and adaptive context packs when current repository evidence and a deterministic typed baseline exist. Long repository-scoped narrative compression may receive context-budget advice after deterministic compression declines. Request decisions need no Agent OS task_id; explicit models, cascade stages, FIM latency, high-risk quality floors, and deterministic/permission/mutation paths remain authoritative. Request-only decisions are telemetry-only and never become supervised task candidates."
        " Each `path_hints` item requires non-empty `path`, `purpose`, and `scope`; provide only verified values, otherwise omit hints."
    )
    if not local_enabled:
        return tier_repo_description(
            "Primary repository worker for repository navigation, symbols, and impact."
            " Local inference is disabled on this installation."
            f"{argument_note}"
            " Serena-backed retrieval or indexing may create .serena metadata in the repository; do not use it when workspace writes are prohibited."
            " Semantic generation, reasoning, review, independent second opinions, and compression are unavailable until a local model backend is enabled."
            " Use deterministic/indexed evidence only for exact facts, symbols, diff, tests, and verification."
            " If no exposed Hub action covers an operation (for example `git worktree list`), skip Hub and use the authorized native tool directly; no Hub error or fallback flag is needed."
            " After calling an advertised Hub action, use native fallback only when its result explicitly has terminal=true and retryable=false."
            " Use when: indexed repository evidence is needed."
            " Skip when: the task is not repository-scoped or fresh evidence already answers it."
        )
    if lean_schemas:
        return tier_repo_description(
            "Primary repository worker for repository navigation, symbols, and impact with aggregate-bounded responses; optional max_response_tokens, response_profile, reuse_key. Reuse fresh sufficient evidence; use bounded indexed/source lookup directly for exact facts. When non-trivial work lacks sufficient fresh evidence, adaptive context fuses deterministic/indexed evidence, Serena, bounded lexical search and RAG, then returns grounded diverse context. Send the task/context rather than handmade grep terms. It accepts guarded task/phase/focus fields, requires evidence IDs and reuse candidates first, treats deterministic/indexed evidence as authoritative, limits local models to ranking/compression of structured evidence, and requires `override_reason` plus approval when requested. Raw model/debug fields require dashboard detailed diagnostics; extra_fields cannot enable them. Omitted mode selects adaptive; explicit fast and full modes retain distinct retrieval paths. Use deterministic/indexed actions for exact facts, symbols, diff and tests; use `local_ai_task` for semantic generation, reasoning, review, independent second opinions and compression. `solve` preserves one bounded local pass for explicit semantic requests even when exact evidence is strong. After calling an advertised Hub action, use native fallback only when its result explicitly has terminal=true and retryable=false. For `review_diff`, prefer Hub-computed root/base/path scope with `diff_tokens`; supplied raw `diff` bypasses that bound. If a fragment exceeds the 512-token review budget and cannot be split safely, narrow by path/diff or exclude generated/minified files; never replay unchanged input. If review exceeds 32 segments, narrow by path or split files. Use `code_index` for indexed symbol lookup. Actions: search, code_index, context, solve, review_diff, callers, dead_code, preprocess (idempotent registration of a stable repository root; do not force-refresh or poll)."
            " Serena-backed retrieval or indexing may create .serena metadata in the repository; do not use it when workspace writes are prohibited."
            " Use when: every non-trivial repository task needs indexed evidence or a bounded Hub operation."
            " Skip when: the task is not repository-scoped or fresh evidence already answers it and no independent Hub scope exists."
            f"{argument_note}"
        )

    description = (
        "Primary bounded repository worker for repository navigation, symbols, and impact."
        " Serena-backed retrieval or indexing may create .serena metadata in the repository; do not use it when workspace writes are prohibited."
        " Reuse fresh evidence and bounded indexed/source lookup for exact facts; use adaptive context when non-trivial work lacks sufficient fresh evidence."
        " Use the adaptive context orchestrator: deterministic, code_index, Serena, bounded lexical search, and RAG are fused when available;"
        " agreement is ranked, paths are deduplicated/diversified, and optional local models only rerank/compress grounded evidence."
        f" Use deterministic, code_index/search,{' ' + features.semantic_hint() + ',' if features.has_semantic() else ''}"
        " context and solve for bounded evidence and implementation support."
        " Reuse fresh sufficient evidence. For exact file or symbol lookups, use bounded indexed/source lookup directly. Use `context` in adaptive mode only when non-trivial planning, editing, review or testing lacks sufficient fresh evidence; send the task/context, not handmade grep terms. Reuse existing evidence and reuse candidates first, require evidence IDs, and treat deterministic/indexed evidence as authoritative. Guarded overrides require `override_reason` and approval when requested. Raw model/debug fields stay omitted unless requested through `extra_fields`. Omitted mode selects adaptive; explicit fast and full modes retain distinct retrieval paths."
        " For implementation, diagnosis, refactoring or complex review, call `solve` after evidence and before native edits."
        f"{' When generating, use `' + features.fast_model + '` for quick tasks, `' + features.smart_model + '` for complex work, and `' + features.reasoning_model + '` for hardest reasoning.' if local_enabled else ''}"
        " `review_diff` and `security_audit` are targeted local checks. MCP `review_diff` uses adaptive delivery with a 30-second latency budget; if deferred, follow the returned job ID through exposed `local_ai_task` status/wait/result actions and wait once without replaying the review. Prefer Hub-computed `root`/`base`/optional `path` with `diff_tokens`; supplied raw `diff` bypasses that bound. An unsplittable fragment above the 512-token budget requires narrower paths/diff or excluding generated/minified files. If review exceeds 32 segments, narrow by path or split files instead of replaying unchanged input."
        f"{'  After any needed indexed evidence, use `local_ai_task` for semantic generation, reasoning, review, independent second opinions and compression. `solve` preserves one bounded local pass for explicit semantic requests even when exact evidence is strong.' if local_enabled else ''}"
        f"{semantic_handoff_contract(local_enabled, features.status)}"
        " Codex separately decides whether to use native Codex subagents;"
        " Local AI Hub does not route or manage those agents."
        " Preprocess only when a stable absolute root is unindexed or its evidence is stale; preprocessing is asynchronous, so never wait/poll/force-refresh it."
        f" Retrieval path: reuse fresh evidence; use bounded deterministic/indexed/source lookup for exact facts and adaptive context only when evidence is insufficient. Context fans out only bounded independent backends, fuses their ranked paths, and stops optional layers on timeout/degradation. Semantic generation, reasoning, review, independent second opinions and compression use `local_ai_task` after evidence;"
        " never fan out duplicate native searches or manually translate a task into a long grep-term list."
        " Reuse fresh evidence/artifact slices and never repeat an identical root/query/action while repo state is unchanged."
        " `in_progress` means another owner is doing identical work; retryable/429/503 means back off;"
        " degraded/stale means verify only the affected slice."
        " If no exposed Hub action covers an operation (for example `git worktree list`), skip Hub and use the authorized native tool directly; no Hub error or fallback flag is needed."
        " After calling an advertised Hub action, use native fallback only when its result explicitly has terminal=true and retryable=false."
        " Always pass the stable absolute project root; never rely on MCP cwd. Never loop or increase timeouts indefinitely."
        f"{argument_note}"
        " Use when: every non-trivial repository task needs indexed evidence or a bounded Hub operation."
        " Skip when: the task is not repository-scoped or fresh evidence already answers it and no independent Hub scope exists."
        f"{actions_note(features.supported_repo_actions())}"
        f"{specialized_note('local_ai_repo')}"
    )
    return tier_repo_description(description)

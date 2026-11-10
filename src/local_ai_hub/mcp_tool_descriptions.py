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
            " Project search/index and ingestion require an explicit absolute authorized root and root-bound workspace. Search ingested documents with action=search in that workspace; docset_index/docset_search use a separate owner-global docset namespace. Document ingestion requires non-empty content; diagram files stay inside that root."
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
        " Project search/index and ingestion require an explicit absolute authorized root and root-bound workspace. Search ingested documents with action=search in that workspace; docset_index/docset_search use a separate owner-global docset namespace. Document ingestion requires non-empty content; diagram files stay inside that root."
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
        "delegate", "explore", "reason", "review", "second_opinion", "continue", "batch", "compress"
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
            "For compress, pass source in `text` and optional instructions in `task`; `max_tokens` targets generated output, `max_response_tokens` bounds the response envelope. "
            "An empty active_model does not establish that no models are installed. "
            "Use deterministic/indexed tools for exact facts, symbols, diff and tests. "
            f"{semantic_handoff_contract(bool(semantic_actions), features.status)}"
            "Command failure diagnosis remains disabled by default; never pass raw logs or open-ended coding. "
            "Codex retains ownership of native subagent orchestration; that does not replace direct Hub endpoint use by the main agent. "
            "Use when: bounded local generation, compression, review, routing, second opinion, or named advisory subagent work is needed. "
            "Skip when: task is trivial, pure evidence lookup, security/privacy constrained, local tasks are disabled, or no exposed bounded semantic action fits. "
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
        f" {'Exposed work includes ' + semantic_summary + '.' if semantic_summary else 'Semantic actions are currently gated.'}"
        " For compress, pass source in `text` and optional instructions in `task`; `max_tokens` targets generated output, `max_response_tokens` bounds the response envelope."
        " An empty active_model does not establish that no models are installed."
        f" Route preprocessing through `{features.background_model}`, quick tasks through `{features.fast_model}`, complex tasks through `{features.smart_model}`, and the hardest reasoning through `{features.reasoning_model}`."
        " Explicit model overrides must match a configured model tag."
        f"{profile_note}"
        " Use deterministic/indexed tools for exact facts, symbols, diff and tests; use only actions exposed by the current schema."
        f"{semantic_handoff_contract(bool(semantic_actions), features.status)}"
        " Command failure diagnosis is disabled by default; enable `features.local_diagnostic_dispatch=true` only for one local diagnostic after low-confidence deterministic command parsing with an artifact reference and narrow preview, never raw logs."
        " Never automatically dispatch local inference for architecture, security, mutations, or open-ended coding."
        " Codex manages native subagents directly; the main agent still calls Hub endpoints when applicable, and a Hub call does not imply delegation."
        f"{action_note}"
        f"{specialized_note('local_ai_task')}"
        " `delivery=sync` preserves the foreground contract; `async` returns a durable job now;"
        " `auto` requires a positive `latency_budget_ms` and only defers after sufficient endpoint history shows p95 above it."
        " Evaluation stores only opaque ids, booleans, and numeric metadata; it never stores prompts or source text."
        " Async wait is bounded to 90 seconds; never poll loops."
        " Start a short-lived conversation with `conversation=true` on delegate or reason, then use `continue` with its opaque `conversation_id`; conversations are sync-only and process-memory only."
        " Use when: a currently exposed local task action fits the request."
        " Skip when: task is trivial, pure evidence lookup, security/privacy constrained, local tasks are disabled,"
        " or no exposed bounded semantic action fits."
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
            " Source: action=source, path, line_start/line_end; workspace-confined, file/range/output bounded with SHA-256 provenance."
            " Use when: exact source or evidence text is required after indexed discovery."
            " Skip when: no source slice is needed or the existing compact result is sufficient."
            f"{specialized_note('local_ai_artifact')}"
        )
    return (
        "Fetch one exact source or log slice or bounded binary artifact metadata. Binary payloads are never inlined in MCP responses. Evidence IDs start with E."
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
    if lean_schemas:
        supported = set(features.supported_coord_actions())
        actions = sorted(supported)
        reservation_note = (
            " GPU reservation status is owner-global and takes no root; gpu_reservation_release requires consent=true, generation and audit_reason, then expiry or confirmed owner death. gpu_reservation_release_authorized requires explicit consent=true and audit_reason, without a generation or owner-liveness preflight. It releases a valid reservation or records a durable operator-release marker when the reservation file is already missing, allowing the scheduler to clear only stale in-memory external admission. Malformed metadata and symlinks remain fail-closed."
            if {"gpu_reservation_status", "gpu_reservation_release", "gpu_reservation_release_authorized"}.issubset(actions)
            else ""
        )
        purpose = (
            "Agent OS coordination for task contracts, ownership, checkpoints, and verification receipts"
            if features.agent_os else "Coordination for leases"
        )
        return (
            f"{purpose} with aggregate-bounded responses; optional max_response_tokens, response_profile, reuse_key."
            f"{actions_note(actions)}"
            f"{reservation_note}"
            f"{plan_coord_note()}"
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
        f"{plan_coord_note()}"
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
    if not local_enabled:
        return tier_repo_description(
            "Primary repository worker for repository navigation, symbols, and impact."
            " Local inference is disabled on this installation."
            " Serena-backed retrieval or indexing may create .serena metadata in the repository; do not use it when workspace writes are prohibited."
            " Semantic generation, reasoning, review, independent second opinions, and compression are unavailable until a local model backend is enabled."
            " Use deterministic/indexed evidence only for exact facts, symbols, diff, tests, and verification."
            " Native fallback requires terminal=true and retryable=false."
            " Use when: indexed repository evidence is needed."
            " Skip when: the task is not repository-scoped or fresh evidence already answers it."
        )
    if lean_schemas:
        return tier_repo_description(
            "Primary repository worker for repository navigation, symbols, and impact with aggregate-bounded responses; optional max_response_tokens, response_profile, reuse_key. Reuse fresh sufficient evidence; use bounded indexed/source lookup directly for exact facts. When non-trivial work lacks sufficient fresh evidence, adaptive context fuses deterministic/indexed evidence, Serena, bounded lexical search and RAG, then returns grounded diverse context. Send the task/context rather than handmade grep terms. It accepts guarded task/phase/focus fields, requires evidence IDs and reuse candidates first, treats deterministic/indexed evidence as authoritative, limits local models to ranking/compression of structured evidence, and requires `override_reason` plus approval when requested. Raw model/debug fields require dashboard detailed diagnostics; extra_fields cannot enable them. Omitted mode selects adaptive; explicit fast and full modes retain distinct retrieval paths. Use deterministic/indexed actions for exact facts, symbols, diff and tests; use `local_ai_task` for semantic generation, reasoning, review, independent second opinions and compression. `solve` preserves one bounded local pass for explicit semantic requests even when exact evidence is strong. Native fallback requires terminal=true and retryable=false. Use `code_index` for indexed symbol lookup. Actions: search, code_index, context, solve, review_diff, callers, dead_code, preprocess (idempotent registration of a stable repository root; do not force-refresh or poll)."
            " Serena-backed retrieval or indexing may create .serena metadata in the repository; do not use it when workspace writes are prohibited."
            " Use when: every non-trivial repository task needs indexed evidence or a bounded Hub operation."
            " Skip when: the task is not repository-scoped or fresh evidence already answers it and no independent Hub scope exists."
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
        " `review_diff` and `security_audit` are targeted local checks. MCP `review_diff` uses adaptive delivery with a 30-second latency budget; if deferred, follow the returned job ID through exposed `local_ai_task` status/wait/result actions and wait once without replaying the review."
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
        " Native fallback requires terminal=true and retryable=false."
        " Always pass the stable absolute project root; never rely on MCP cwd. Never loop or increase timeouts indefinitely."
        " Use when: every non-trivial repository task needs indexed evidence or a bounded Hub operation."
        " Skip when: the task is not repository-scoped or fresh evidence already answers it and no independent Hub scope exists."
        f"{actions_note(features.supported_repo_actions())}"
        f"{specialized_note('local_ai_repo')}"
    )
    return tier_repo_description(description)

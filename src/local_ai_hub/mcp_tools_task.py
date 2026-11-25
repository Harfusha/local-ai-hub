from __future__ import annotations

from typing import Any, Literal, TypeAlias

from .operation_contracts import operation_actions

TaskAction: TypeAlias = Literal.__getitem__(operation_actions("local_ai_task", None))


def local_ai_task(
    action: TaskAction,
    task: str = "",
    prompt: str = "",
    model: str = "",
    context: str = "",
    candidate: str = "",
    image_artifact_id: str = "",
    screenshot_artifact_id: str = "",
    baseline_screenshot_artifact_id: str = "",
    bundle_artifact_id: str = "",
    dom_artifact_id: str = "",
    accessibility_artifact_id: str = "",
    computed_styles_artifact_id: str = "",
    runtime_artifact_id: str = "",
    network_artifact_id: str = "",
    source: str = "",
    cloud_fallback: bool = False,
    dom: str | dict[str, Any] | None = None,
    accessibility: str | dict[str, Any] | None = None,
    computed_styles: str | dict[str, Any] | None = None,
    runtime: str | dict[str, Any] | None = None,
    bundle: str | dict[str, Any] | None = None,
    html: str | None = None,
    accessibility_snapshot: str | dict[str, Any] | None = None,
    computed_style_data: str | dict[str, Any] | None = None,
    runtime_context: str | dict[str, Any] | None = None,
    viewport: dict[str, Any] | None = None,
    url: str = "",
    page: dict[str, Any] | None = None,
    automation: dict[str, Any] | None = None,
    complexity: str = "auto",
    max_tokens: int = 0,
    context_tokens: int | None = None,
    tasks: list[dict[str, Any]] | None = None,
    cases: list[dict[str, Any]] | None = None,
    delivery: str = "sync",
    latency_budget_ms: float = 0.0,
    job_action: str = "reason",
    job_id: str = "",
    request_id: str = "",
    timeout_seconds: float = 90,
    evaluation_task_id: str = "",
    evaluation_cohort: str = "",
    quality_pass: bool | None = None,
    test_pass: bool | None = None,
    evaluation_duration_ms: float = 0.0,
    evaluation_days: int = 30,
    profile: str = "",
    root: str = "",
    workspace: str = "",
    task_id: str = "",
    phase: str = "",
    focus: list[str] | None = None,
    preload_profile: str = "",
    changed_paths: list[str] | None = None,
    repository_revision: str = "",
    conversation: bool = False,
    conversation_id: str = "",
    approver: str = "",
    candidate_data: dict[str, Any] | None = None,
    format: str | dict[str, Any] | None = None,
    json_schema: dict[str, Any] | None = None,
    operation: Literal["fix", "review", "describe"] | None = None,
    language: str = "auto",
    extra_fields: list[str] | None = None,
    max_response_tokens: int = 0,
    response_profile: str = "",
    reuse_key: str = "",
    code: str = "",
    problem: str = "",
    question: str = "",
    text: str = "",
) -> dict[str, Any]:
    from . import mcp_server as services_module
    """Run a bounded semantic task or an explicitly authorized UI automation session.

    automation uses root, task_id and a closed automation object with op
    open/act/status/close. Browser/desktop targets are default-deny; use the
    returned session_id and session_key, and a unique request_id for each act.
    Backends are installed explicitly. Unknown outcomes must never be replayed.

    Use deterministic/indexed tools for exact facts, symbols, diffs and tests;
    use this worker for semantic generation, exploration, reasoning, review, independent
    second opinions and semantic compression. Explicit model overrides must
    match a configured model role. Named advisory profiles use read-only
    repository tooling. Command-failure diagnosis remains opt-in and accepts
    only a narrow artifact-backed preview, never raw logs. This tool is not the
    orchestrator for native Codex subagents. The public action enum is
    feature-gated and exposed by the MCP schema, so callers must use the
    advertised actions rather than an inferred alias. Delivery and async
    constraints remain bounded; conversations are sync-only and process-memory
    only. The submit action already creates an asynchronous job: provide a
    non-empty task, select its job_action, and place long source text in context.
    There is no async flag or input_path argument. Use when one bounded semantic task should run on a configured local
    model. Use when: one bounded semantic task should run on a configured
    local model. Skip when: local-model tasks are disabled or Codex-owned
    subagent orchestration is the right owner; Local AI Hub does not route or manage native Codex agents."""
    if action not in services_module.operation_actions("local_ai_task", services_module.FEATURES):
        return services_module._invalid_action(
            "local_ai_task",
            action,
            services_module.operation_actions("local_ai_task", services_module.FEATURES),
            "Use Local AI Hub only for bounded local-model work; use Codex-owned orchestration for peer subagents.",
        )
    retired_inputs = {
        "delegate": {"prompt", "problem"},
        "explore": {"prompt", "problem"},
        "reason": {"task", "prompt"},
        "review": {"context", "candidate", "prompt"},
        "second_opinion": {"task", "prompt", "code"},
        "compress": {"context", "prompt", "candidate"},
        "hardware_benchmark": {"task"},
        "speculative_draft": {"prompt", "workspace"},
        "vision": {"task", "context"},
        "eval_drift": {"prompt"},
        "complete_code": {"context", "task"},
        "scaffold": {"task", "candidate"},
        "transcribe": {"context", "task", "prompt"},
        "eval_suite": {"prompt"},
        "prompt_eval": {"task", "context"},
        "candidate_create": {"task", "candidate", "prompt", "evaluation_task_id"},
        "candidate_promote": {"task", "prompt", "evaluation_task_id", "candidate_data"},
    }
    input_values = {
        "task": task, "prompt": prompt, "context": context,
        "candidate": candidate, "workspace": workspace, "model": model,
        "problem": problem, "question": question,
        "text": text, "code": code,
        "context_tokens": context_tokens,
        "root": root, "language": language, "candidate_data": candidate_data,
        "evaluation_task_id": evaluation_task_id,
    }
    for field in retired_inputs.get(action, ()):
        if input_values[field] not in (None, ""):
            return {
                "success": False, "status_code": 400, "terminal": True, "retryable": False,
                "error": f"{action} accepts its canonical input; {field} is not an alias",
            }
    canonical_string_fields = {
        "hardware_benchmark": ("prompt", "model"),
        "speculative_draft": ("task", "candidate", "context", "root"),
        "vision": ("prompt", "candidate"),
        "eval_drift": ("task",),
        "complete_code": ("prompt", "candidate"),
        "scaffold": ("prompt", "context", "language", "model"),
        "transcribe": ("candidate", "model", "language"),
        "eval_suite": ("task", "model"),
        "prompt_eval": ("prompt",),
    }
    for field in canonical_string_fields.get(action, ()):
        if not isinstance(input_values[field], str):
            return {
                "success": False, "status_code": 400, "terminal": True, "retryable": False,
                "error": f"{action} {field} must be a string",
            }
    if action == "prompt_eval" and candidate_data is not None and not isinstance(candidate_data, dict):
        return {
            "success": False, "status_code": 400, "terminal": True, "retryable": False,
            "error": "prompt_eval candidate_data must be an object",
        }
    if action == "candidate_create" and not isinstance(candidate_data, dict):
        return {
            "success": False, "status_code": 400, "terminal": True, "retryable": False,
            "error": "candidate_create requires candidate_data object",
        }
    if action == "candidate_promote":
        for field, value in (("candidate", candidate), ("approver", approver)):
            if not isinstance(value, str) or not value.strip():
                return {
                    "success": False, "status_code": 400, "terminal": True, "retryable": False,
                    "error": f"candidate_promote requires non-empty {field}",
                }
    try:
        mode_snapshot = services_module.load_operational_mode(services_module.configured_state_dir(services_module.CFG, create=False))
    except Exception:
        # Missing or unreadable mode state must fail closed for agent work.
        mode_snapshot = None

    deterministic_actions = {"status", "wait", "result", "cancel", "evaluation_report"}
    mode_rejection = services_module.operational_mode_gate_error(
        mode_snapshot,
        action,
        requires_heavy_work=action not in deterministic_actions,
    )
    if mode_rejection is not None:
        return mode_rejection
    if action == "automation":
        if delivery != "sync" or conversation:
            return {"success": False, "error": "automation sessions require synchronous delivery without conversations", "terminal": True, "retryable": False}
        if not isinstance(automation, dict) or not root or not task_id:
            return {"success": False, "error": "automation requires root, task_id and automation object", "terminal": True, "retryable": False}
        return services_module._compact(
            services_module.CLIENT.post("/api/task/automation", {"root": root, "task_id": task_id, "automation": automation}, timeout=services_module._timeout("long")),
            "general", extra_fields=["automation"],
        )
    if conversation and action not in {"delegate", "explore", "reason"}:
        return {"success": False, "error": "Conversations support delegate, explore, reason and continue only", "terminal": True, "retryable": False}
    if conversation and delivery.strip().lower() != "sync":
        return {"success": False, "error": "Conversations require delivery=sync", "terminal": True, "retryable": False}
    if action in {"submit", "status", "wait", "result", "cancel"} and not getattr(services_module.FEATURES, "async_jobs", False):
        return {
            "success": False,
            "unsupported": True,
            "error": "Async job lifecycle is disabled (async_jobs.enabled=false)",
        }
    if action in {"status", "wait", "result", "cancel"}:
        payload: dict[str, Any] = {"action": action, "job_id": job_id}
        transport_timeout = services_module._timeout("quick")
        if action == "wait":
            quick_timeout = max(0.0, float(services_module._timeout("quick")))
            client_timeout = max(
                0.0,
                float(getattr(services_module.CLIENT, "max_request_timeout", quick_timeout)),
            )
            configured_wait = max(
                0.0,
                float(services_module.CFG.get("async_jobs", {}).get("wait_max_seconds", 90)),
            )
            requested_wait = max(0.0, float(timeout_seconds or 90))
            effective_wait = min(
                requested_wait,
                configured_wait,
                max(0.0, client_timeout - quick_timeout),
            )
            payload["timeout_seconds"] = effective_wait
            transport_timeout = min(client_timeout, effective_wait + quick_timeout)
        return services_module._compact(
            services_module.CLIENT.post(
                "/api/async-jobs",
                payload,
                timeout=transport_timeout,
                request_id=request_id or None,
            ),
            "status",
            extra_fields=[*(extra_fields or []), "progress_percent", "current_stage", "progress_available"],
        )
    # Explicit short limits are allowed down to the receiving operation's floor.
    # Compression uses a target with its own 128-token minimum.
    if action in {"delegate", "explore", "reason", "review", "second_opinion", "compress"}:
        output_floor = 128 if action == "compress" else 64
        if max_tokens and (type(max_tokens) is not int or max_tokens < output_floor):
            return {"success": False, "error": f"max_tokens must be at least {output_floor} when specified for {action}",
                    "operation_not_started": True, "terminal": True, "retryable": False}
    if action in {"candidate_create", "candidate_promote"}:
        if action == "candidate_create":
            return services_module._compact(services_module.CLIENT.post("/api/agent-state/learning", {
                "action": "create_candidate", "candidate": candidate_data,
            }, timeout=services_module._timeout("quick")), "status")
        return services_module._compact(services_module.CLIENT.post("/api/agent-state/learning", {
            "action": "promote", "candidate_id": candidate, "approver": approver,
        }, timeout=services_module._timeout("quick")), "status")
    if not services_module.FEATURES.tasks or not services_module.FEATURES.has_any_model():
        return {"success": False, "unsupported": True, "error": "Local model execution is disabled (features.tasks=false or no Ollama runtime configured)"}
    context, task_context_meta = services_module._load_task_context(
        task_id=task_id,
        root=root,
        context=context,
        phase=phase,
        focus=focus,
        preload_profile=preload_profile,
        changed_paths=changed_paths,
        repository_revision=repository_revision,
        token_budget=max_tokens,
    )
    if task_id.strip() and not task_context_meta.get("success", False):
        return task_context_meta
    context_evidence_ids = list(task_context_meta.get("evidence_ids") or [])
    if profile:
        if not services_module.PROFILE_CATALOG.enabled:
            return {"success": False, "unsupported": True, "error": "Ollama subagent profiles disabled"}
        try:
            services_module.PROFILE_CATALOG.resolve(profile)
        except ValueError as exc:
            return {"success": False, "unsupported": True, "error": str(exc)}
        if not root or not services_module.is_rooted_path(root):
            return {
                "success": False,
                "unsupported": True,
                "error": "Named Ollama profiles require an explicit absolute repository root",
            }
        if action not in {"delegate", "explore", "reason", "review", "second_opinion", "submit"}:
            return {"success": False, "unsupported": True, "error": "Ollama profiles support delegate, explore, reason, review, second_opinion and submit only"}
    if action == "submit":
        submit_payload: dict[str, Any] = {
            "action": action, "job_action": job_action, "job_id": job_id, "timeout_seconds": timeout_seconds,
            "task": task, "context": context, "candidate": candidate, "complexity": complexity,
            "max_tokens": max_tokens, "tasks": tasks or [], "profile": profile, "root": root, "workspace": workspace,
        }
        if request_id:
            submit_payload["request_id"] = request_id
        return services_module._compact(
            services_module.CLIENT.post(
                "/api/async-jobs",
                submit_payload,
                timeout=services_module._timeout("quick"),
                request_id=request_id or None,
            ),
            "status",
        )
    budgeted_actions = {"continue", "delegate", "explore", "reason", "review", "second_opinion", "compress"}
    if task_id.strip() and action in budgeted_actions and services_module.ROOT_FAMILY_BUDGET.default_limit:
        family_key = services_module.hashlib.sha1(services_module._client_root(root).encode("utf-8", "replace"), usedforsecurity=False).hexdigest()[:16]
        budget_tokens = max_tokens or 4096
        budget_scope = f"{task_id}:{action}"
        reservation_owner = f"{task_id}:{services_module.uuid.uuid4().hex}"
        admission = services_module.ROOT_FAMILY_BUDGET.reserve(
            family_key,
            input_tokens=budget_tokens,
            limit=services_module.ROOT_FAMILY_BUDGET.default_limit,
            task_id=task_id,
            scope=budget_scope,
            owner=reservation_owner,
        )
        if admission.get("status") == "rejected":
            return {
                "success": False,
                "terminal": not bool(admission.get("retryable", False)),
                "retryable": bool(admission.get("retryable", False)),
                "error": str(admission.get("reason", "root family budget denied")),
                "budget": admission,
            }
        if admission.get("status") == "accepted":
            services_module._CURRENT_ROOT_FAMILY_RESERVATION.set({
                "reservation_id": admission["reservation_id"],
                "owner": reservation_owner,
            })
    if action == "continue":
        if profile:
            return {"success": False, "unsupported": True, "error": "Conversations do not support profiles"}
        if not conversation_id.strip():
            return {"success": False, "error": "conversation_id is required", "terminal": True, "retryable": False}
        return services_module._compact(services_module._attach_task_context_receipt(services_module._quality_check_semantic_result(services_module.CLIENT.post("/api/conversations/continue", {
            "conversation_id": conversation_id, "task": task, "context": context,
        }, timeout=services_module._timeout("model")), task=task, context=context, changed_paths=changed_paths), task_context_meta), "delegate")
    if profile:
        profile_task = problem if action == "reason" else question if action == "second_opinion" else task
        profile_candidate = code if action == "review" else candidate
        payload = {
            "profile": profile, "task": profile_task, "context": context, "candidate": profile_candidate,
            "complexity": complexity, "max_tokens": max_tokens, "priority": 5,
            "root": root, "workspace": workspace or None,
            "operation": action,
            "changed_paths": changed_paths or [],
            "evidence_ids": context_evidence_ids,
            "repository_revision": repository_revision,
        }
        endpoint = "/api/delegate/repo" if root else "/api/delegate"
        return services_module._compact(services_module._attach_task_context_receipt(services_module._quality_check_semantic_result(services_module.CLIENT.post(endpoint, payload, timeout=services_module._timeout("model")), task=task, context=context, changed_paths=changed_paths), task_context_meta), "delegate")
    if action in {"delegate", "explore"}:
        payload = {
            "task": task, "context": context, "complexity": complexity, "max_tokens": max_tokens or 4096,
            "delivery": delivery, "latency_budget_ms": latency_budget_ms, "model": model,
            "operation": action, "changed_paths": changed_paths or [], "repository_revision": repository_revision,
            "root": root or None, "workspace": workspace or None,
            "evidence_ids": context_evidence_ids,
        }
        if format or json_schema:
            payload["format"] = format or json_schema
        if conversation:
            payload["conversation"] = True
        return services_module._compact(services_module._attach_task_context_receipt(services_module._quality_check_semantic_result(services_module.CLIENT.post("/api/delegate", payload), task=task, context=context, changed_paths=changed_paths), task_context_meta), "explore" if action == "explore" else "delegate")
    if action == "reason":
        problem_input = problem
        payload = {
            "problem": problem_input, "context": context, "max_tokens": max_tokens or 4096,
            "delivery": delivery, "latency_budget_ms": latency_budget_ms, "model": model,
            "operation": "reason", "changed_paths": changed_paths or [], "repository_revision": repository_revision,
            "root": root or None, "workspace": workspace or None,
            "evidence_ids": context_evidence_ids,
        }
        if format or json_schema:
            payload["format"] = format or json_schema
        if conversation:
            payload["conversation"] = True
        return services_module._compact(services_module._attach_task_context_receipt(services_module._quality_check_semantic_result(services_module.CLIENT.post("/api/reason", payload), task=problem_input, context=context, changed_paths=changed_paths), task_context_meta), "reason")
    if action == "review":
        code_input = code
        instructions_input = task or "Report actionable defects only."
        payload = {
            "code": code_input, "instructions": instructions_input,
            "complexity": complexity, "max_tokens": max_tokens or 4096,
            "delivery": delivery, "latency_budget_ms": latency_budget_ms, "model": model,
            "operation": "review", "changed_paths": changed_paths or [], "repository_revision": repository_revision,
            "root": root or None, "workspace": workspace or None,
            "evidence_ids": context_evidence_ids,
        }
        if format or json_schema:
            payload["format"] = format or json_schema
        return services_module._compact(services_module._attach_task_context_receipt(services_module._quality_check_semantic_result(services_module.CLIENT.post("/api/review", payload), task=task, context=code_input, changed_paths=changed_paths), task_context_meta), "review")
    if action == "second_opinion":
        question_input = question
        candidate_input = candidate
        return services_module._compact(services_module._attach_task_context_receipt(services_module._quality_check_semantic_result(services_module.CLIENT.post("/api/second-opinion", {
            "question": question_input, "candidate": candidate_input, "context": context if candidate_input != context else "", "max_tokens": max_tokens or 4096,
            "delivery": delivery, "latency_budget_ms": latency_budget_ms, "model": model, "complexity": complexity,
            "changed_paths": changed_paths or [], "repository_revision": repository_revision,
            "root": root or None, "workspace": workspace or None,
            "evidence_ids": context_evidence_ids,
        }), task=question_input, context=context, changed_paths=changed_paths), task_context_meta), "second_opinion")
    if action == "compress":
        text_input = text
        instructions_input = task or "Compress while preserving facts, identifiers, numbers, errors, decisions and uncertainty."
        return services_module._compact(services_module._attach_task_context_receipt(services_module._quality_check_semantic_result(services_module.CLIENT.post("/api/compress", {
            "text": text_input, "instruction": instructions_input,
            "target_tokens": max_tokens or 650,
            "root": root or None, "evidence_ids": context_evidence_ids,
            "delivery": delivery, "latency_budget_ms": latency_budget_ms,
        }, timeout=services_module._timeout("model")), task=task, context=text_input, changed_paths=changed_paths), task_context_meta), "compress")
    if action == "route":
        return services_module._compact(services_module.CLIENT.post("/api/route", {"text": context, "query": task, "delivery": delivery, "latency_budget_ms": latency_budget_ms}, timeout=services_module._timeout("model")), "route")
    if action == "batch":
        batch_payload = {"tasks": tasks or [], "delivery": delivery, "latency_budget_ms": latency_budget_ms}
        requested, _, _, budget_enabled = services_module._response_budget("batch", services_module._CURRENT_RESPONSE_OPTIONS.get())
        if budget_enabled:
            batch_payload["response_budget_tokens"] = requested
        batch_result = services_module.CLIENT.post("/api/delegate/batch", batch_payload, timeout=services_module._timeout("long"))
        projected = services_module._compact(batch_result, "delegate")
        budget = projected.get("response_budget") if isinstance(projected, dict) else None
        lost_items = (isinstance(batch_result, dict) and isinstance(projected, dict)
                      and not services_module._batch_items_retained(batch_result.get("results"), projected.get("results")))
        if (isinstance(budget, dict) and budget.get("rejected") is True) or lost_items:
            if lost_items:
                projected = {"success": False, "error": "batch result unavailable in bounded response",
                             **({"request_id": batch_result["request_id"]} if isinstance(batch_result.get("request_id"), str) else {})}
            if isinstance(batch_result, dict) and batch_result.get("request_not_sent") is True:
                projected["request_not_sent"] = True
            else:
                # Dispatch already happened; a projection error is not a preflight refusal.
                projected["outcome_unknown"] = True
            if isinstance(batch_result, dict) and isinstance(batch_result.get("request_id"), str):
                projected.setdefault("request_id", batch_result["request_id"])
            if isinstance(batch_result, dict) and isinstance(batch_result.get("output_artifact_id"), str):
                projected["output_artifact_id"] = batch_result["output_artifact_id"]
        return projected
    if action == "benchmark":
        return services_module._compact(services_module.CLIENT.post("/api/benchmark", {}, timeout=services_module._timeout("long")), "status")
    if action == "hardware_benchmark":
        payload = {"model": model or "", "prompt": prompt, "num_tokens": max_tokens or 40}
        if context_tokens is not None:
            payload["context_tokens"] = context_tokens
        return services_module._compact(services_module.CLIENT.post("/api/benchmark/run", payload, timeout=services_module._timeout("long")), "hardware_benchmark")
    if action == "evaluation_record":
        return services_module._compact(services_module.CLIENT.post("/api/evaluation", {
            "action": "record", "task_id": evaluation_task_id, "cohort": evaluation_cohort,
            "quality_pass": quality_pass, "test_pass": test_pass, "duration_ms": evaluation_duration_ms,
        }), "status")
    if action == "evaluation_report":
        return services_module._compact(services_module.CLIENT.post("/api/evaluation", {"action": "report", "days": evaluation_days}), "status")
    if action == "speculative_draft":
        return services_module._compact(services_module.CLIENT.post("/api/task/speculative_draft", {
            "task": task, "file": candidate, "context": context, "root": root,
        }, timeout=services_module._timeout("model")), "delegate")
    if action == "vision":
        effective_image = image_artifact_id
        payload = {
            "prompt": prompt,
            "image": candidate,
            "model": model,
            "image_artifact_id": effective_image,
            "screenshot_artifact_id": screenshot_artifact_id,
            "baseline_screenshot_artifact_id": baseline_screenshot_artifact_id,
            "bundle_artifact_id": bundle_artifact_id,
            "dom_artifact_id": dom_artifact_id,
            "accessibility_artifact_id": accessibility_artifact_id,
            "computed_styles_artifact_id": computed_styles_artifact_id,
            "runtime_artifact_id": runtime_artifact_id,
            "network_artifact_id": network_artifact_id,
            "source": source,
            "cloud_fallback": cloud_fallback,
            "root": root,
        }
        if json_schema is not None:
            payload["json_schema"] = json_schema
        if operation is not None:
            payload["operation"] = operation
        for name, value in {
            "dom": dom,
            "accessibility": accessibility,
            "computed_styles": computed_styles,
            "runtime": runtime,
            "viewport": viewport,
            "page": page,
            "bundle": bundle,
            "html": html,
            "accessibility_snapshot": accessibility_snapshot,
            "computed_style_data": computed_style_data,
            "runtime_context": runtime_context,
        }.items():
            if value is not None:
                payload[name] = value
        return services_module._compact(services_module.CLIENT.post("/api/task/vision", payload, timeout=services_module._timeout("model")), "delegate")
    if action == "browser":
        capture = services_module.CLIENT.post("/api/task/browser", {"url": url, "viewport": viewport}, timeout=services_module._timeout("quick"))
        return services_module._compact(
            capture,
            "general",
            extra_fields=["url", "title", "dom_snapshot", "dom_truncated", "dom_preview_truncated",
                          "dom_artifact_id", "screenshot_artifact_id", "screenshot_mime_type", "screenshot_size_bytes",
                          "network_requests_denied"],
        )
    if action == "transcribe":
        audio = candidate
        transcribe_payload = {
            "audio_path": audio,
            "model": model,
        }
        language_hint = str(language or "").strip()
        if language_hint and language_hint.casefold() != "auto":
            transcribe_payload["language"] = language_hint
        return services_module._compact(services_module.CLIENT.post("/api/task/transcribe", transcribe_payload, timeout=services_module._timeout("long")), "delegate")
    if action == "eval_suite":
        eval_payload: dict[str, Any] = {"suite_name": task or "default"}
        if model:
            eval_payload["model"] = model[:160]
        if cases is not None:
            if not isinstance(cases, list) or not 1 <= len(cases) <= 32 or any(not isinstance(item, dict) for item in cases):
                return {
                    "success": False, "status_code": 400, "terminal": True, "retryable": False,
                    "error_code": "invalid_eval_suite_cases",
                    "error": "cases must contain 1 to 32 objects; omit cases to use the built-in suite",
                }
            bounded_cases: list[dict[str, Any]] = []
            for raw_case in cases:
                supported_case_fields = {
                    "id", "input", "expected", "max_words", "allowed_citations",
                    "required_citations", "forbidden_phrases", "include_response_text",
                }
                unknown_fields = set(raw_case) - supported_case_fields
                if unknown_fields:
                    return {
                        "success": False, "status_code": 400, "terminal": True, "retryable": False,
                        "error_code": "invalid_eval_case_rubric",
                        "error": f"unsupported eval case fields: {', '.join(sorted(str(item) for item in unknown_fields))}",
                    }
                bounded_case: dict[str, Any] = {
                    "id": str(raw_case.get("id", "case"))[:120],
                    "input": str(raw_case.get("input", ""))[:4000],
                    "expected": str(raw_case.get("expected", ""))[:2000],
                }
                if "max_words" in raw_case:
                    max_words = raw_case["max_words"]
                    if type(max_words) is not int or not 1 <= max_words <= 1000:
                        return {
                            "success": False, "status_code": 400, "terminal": True, "retryable": False,
                            "error_code": "invalid_eval_case_rubric", "error": "max_words must be an integer from 1 to 1000",
                        }
                    bounded_case["max_words"] = max_words
                if "include_response_text" in raw_case:
                    include_response_text = raw_case["include_response_text"]
                    if type(include_response_text) is not bool:
                        return {
                            "success": False, "status_code": 400, "terminal": True, "retryable": False,
                            "error_code": "invalid_eval_case_rubric",
                            "error": "include_response_text must be a boolean",
                        }
                    bounded_case["include_response_text"] = include_response_text
                for field in ("allowed_citations", "required_citations", "forbidden_phrases"):
                    if field not in raw_case:
                        continue
                    values = raw_case[field]
                    if (
                        not isinstance(values, list) or not 1 <= len(values) <= 32
                        or any(not isinstance(value, str) or not value.strip() or len(value) > 512 for value in values)
                    ):
                        return {
                            "success": False, "status_code": 400, "terminal": True, "retryable": False,
                            "error_code": "invalid_eval_case_rubric",
                            "error": f"{field} must contain 1 to 32 nonempty strings of at most 512 characters",
                        }
                    bounded_case[field] = values
                bounded_cases.append(bounded_case)
            if bounded_cases:
                eval_payload["cases"] = bounded_cases
        return services_module._compact(services_module.CLIENT.post("/api/task/eval_suite", eval_payload, timeout=services_module._timeout("long")), "status")
    if action == "prompt_eval":
        return services_module._compact(services_module.CLIENT.post("/api/task/prompt_eval", {
            "template": prompt, "variables": candidate_data if candidate_data is not None else {},
        }, timeout=services_module._timeout("model")), "delegate")
    if action == "eval_drift":
        return services_module._compact(services_module.CLIENT.post("/api/task/eval_drift", {
            "suite_name": task or "default",
        }, timeout=services_module._timeout("long")), "status")
    if action == "complete_code":
        return services_module._compact(services_module.CLIENT.post("/api/complete", {
            "prefix": prompt, "suffix": candidate, "max_tokens": max_tokens or 80,
        }, timeout=services_module._timeout("quick")), "status")
    if action == "scaffold":
        return services_module._compact(services_module.CLIENT.post("/api/task/scaffold", {
            "spec": prompt, "context": context, "language": language if language and language.casefold() != "auto" else "python",
            "max_tokens": max_tokens or 4096, "model": model,
        }, timeout=services_module._timeout("model")), "delegate")
    return services_module._invalid_action("local_ai_task", action, tuple(services_module.TaskAction.__args__), "Use Local AI Hub only for bounded local-model work; use Codex-owned orchestration for peer subagents.")

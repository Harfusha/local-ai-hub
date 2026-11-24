from __future__ import annotations

from .trace_context import observer

from .services import (
    Any as Any,
    Mapping as Mapping,
    SchedulerCancelledError as SchedulerCancelledError,
    _LinkedCancelEvent as _LinkedCancelEvent,
    __version__ as __version__,
    _backend_completion_metadata as _backend_completion_metadata,
    _generation_cache_dispatch as _generation_cache_dispatch,
    cache_decision_reason as cache_decision_reason,
    capture_job_cancellation as capture_job_cancellation,
    configured_state_dir as configured_state_dir,
    copy as copy,
    estimate_tokens as estimate_tokens,
    fit_text as fit_text,
    generation_cache_key as generation_cache_key,
    is_retryable_local_backend_error as is_retryable_local_backend_error,
    json_dumps as json_dumps,
    logger as logger,
    math as math,
    normalize_context_for_hash as normalize_context_for_hash,
    normalize_query as normalize_query,
    postprocess_model_output as postprocess_model_output,
    re as re,
    reject_retired_tenancy_fields as reject_retired_tenancy_fields,
    sqlite3 as sqlite3,
    stable_hash as stable_hash,
    threading as threading,
    time as time,
)


class ServiceGenerationMixin:
    def _generate(
        self,
        model: str,
        prompt: str,
        system: str,
        max_tokens: int,
        temperature: float,
        *,
        source: str,
        priority: int,
        measured_cloud_context_tokens: int = 0,
        semantic_query: str = "",
        semantic_context_fingerprint: str = "",
        internal: bool = False,
        use_cache: bool = True,
        format: Any = None,
        project_settings: Any | None = None,
        project_role: str = "",
        project_config_digest: str = "",
        project_namespace: str = "",
        repository_revision: str = "",
        trace_system_override: str | None = None,
        cancel_event: threading.Event | None = None,
        request_timeout_seconds: float | None = None,
        route: Mapping[str, Any] | None = None,
        allow_model_fallback: bool = True,
    ) -> dict[str, Any]:
        from .operational_mode import (
            OperationalModeSnapshot,
            load_operational_mode,
            operational_mode_gate_error,
        )

        admission_action = source.split(":", 1)[0].strip().replace("-", "_")
        known_actions = {
            "delegate", "preprocess", "reason", "review", "review_diff", "second_opinion",
            "compress", "route", "batch", "embed", "rerank", "transcribe",
            "vision", "benchmark", "complete_code", "scaffold", "speculative_draft",
            "generate_tests", "solve", "eval_suite", "prompt_eval", "eval_drift",
        }
        if admission_action not in known_actions:
            admission_action = "delegate"
        state_dir = self.config.get("server", {}).get("state_dir")
        if state_dir:
            try:
                mode = load_operational_mode(state_dir)
            except Exception:
                mode = None
            rejection = operational_mode_gate_error(mode, admission_action)
            if rejection is not None:
                return rejection
        trace_system = system if trace_system_override is None else str(trace_system_override)
        mode_pause_result: dict[str, Any] | None = None
        effective_route = dict(route) if isinstance(route, Mapping) else {}
        if cancel_event is None:
            from .client import CURRENT_REQUEST_CANCEL_EVENT
            cancel_event = CURRENT_REQUEST_CANCEL_EVENT.get()
        request_cancel_event = cancel_event
        if cancel_event is None:
            cancel_event = threading.Event()
        parent_stop = capture_job_cancellation()
        if parent_stop is not None:
            cancel_event = _LinkedCancelEvent(cancel_event, parent_stop)
            request_cancel_event = cancel_event
        if project_settings is not None:
            model, project_payload = self.model_policy.apply_project_settings(
                model,
                {"model": model, "system": system},
                settings=project_settings,
                role=project_role,
            )
            system = str(project_payload.get("system", system))
        saving = self.config.get("token_saving", {})
        if saving.get("concise_local_output") is True or saving.get("compress_local_input") is True:
            from .caveman_instructions import compact_local_prompt
            prompt, system = compact_local_prompt(
                prompt, system,
                input_enabled=saving.get("compress_local_input") is True,
                output_enabled=saving.get("concise_local_output") is True,
                structured=format is not None,
            )
        resilience = self.config.get("resilience", {})
        default_request_timeout = float(self.config.get("server", {}).get("request_timeout_seconds", 300)) + 30.0
        request_timeout = max(0.05, float(resilience.get("scheduler_wait_timeout_seconds", default_request_timeout)))
        if request_timeout_seconds is not None:
            if isinstance(request_timeout_seconds, bool):
                raise ValueError("request_timeout_seconds must be finite and positive")
            try:
                timeout_override = float(request_timeout_seconds)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("request_timeout_seconds must be finite and positive") from exc
            if not math.isfinite(timeout_override) or timeout_override <= 0:
                raise ValueError("request_timeout_seconds must be finite and positive")
            request_timeout = min(request_timeout, max(0.05, timeout_override))
        request_deadline = time.monotonic() + request_timeout
        max_tokens = max(64, min(int(max_tokens), int(saving.get("max_local_output_tokens", 8192))))
        role = source.rsplit(":", 1)[-1].lower()
        if source == "second-opinion":
            role = "second-opinion"
        vram_free = self._available_vram_mb()
        fixed_input_tokens = estimate_tokens(system)
        if format is not None:
            fixed_input_tokens += estimate_tokens(json_dumps(format, ensure_ascii=False))
        initial_profile = self.model_policy.profile(
            model, role=role, input_tokens=estimate_tokens(prompt) + fixed_input_tokens, output_tokens=max_tokens,
            background=source.startswith("preprocess:"),
            vram_free_mb=vram_free,
        )
        prompt_budget = min(int(saving.get("max_local_input_tokens", 56000)), initial_profile.prompt_budget_tokens)
        remaining_prompt_budget = prompt_budget - fixed_input_tokens
        if remaining_prompt_budget < 64:
            raise ValueError("context cannot fit the system prompt, output schema and request prompt")
        prepared = fit_text(prompt, remaining_prompt_budget)
        base_payload, execution_profile = self.model_policy.apply_payload(
            model,
            {"model": model, "prompt": prepared.text, "system": system, "stream": False,
             "keep_alive": self.config.get("ollama", {}).get("keep_alive", "-1"),
             "options": {"num_predict": max_tokens, "temperature": float(temperature)}},
            role=role, input_tokens=prepared.estimated_tokens + fixed_input_tokens, output_tokens=max_tokens,
            background=source.startswith("preprocess:"), preserve_explicit_think=False,
            vram_free_mb=vram_free,
        )
        if prepared.estimated_tokens + fixed_input_tokens > execution_profile.prompt_budget_tokens:
            raise ValueError("selected context cannot fit the prepared prompt and system input")
        if format:
            base_payload["format"] = format
        options = dict(base_payload.get("options", {}))
        if not semantic_query and prompt:
            clean_first = re.sub(r"^(TASK|QUESTION|INSTRUCTION|PROMPT|Problem|PROBLEM):\s*", "", prompt.strip(), flags=re.I)
            first_line = clean_first.split("\n\n", 1)[0].splitlines()[0] if clean_first else ""
            if len(first_line.strip()) >= 8:
                semantic_query = normalize_query(first_line.strip())
        elif semantic_query:
            semantic_query = normalize_query(semantic_query)

        execution_scope = {**execution_profile.cache_scope(), "stream_completion_contract": 3}
        norm_context_fp = stable_hash(normalize_context_for_hash(semantic_context_fingerprint)) if semantic_context_fingerprint else "no-context"
        cache_key = generation_cache_key(
            model=model,
            prompt=prepared.text,
            system=system,
            options=options,
            think=base_payload.get("think"),
            execution=execution_scope,
            format=base_payload.get("format"),
            repository_revision=repository_revision,
            project_config_digest=project_config_digest,
            project_namespace=project_namespace,
        )
        semantic_scope_data = {
            "model": model, "system": system, "options": options, "think": base_payload.get("think"), "execution": execution_scope,
            "context": norm_context_fp, "source": source.split(":", 1)[0], "app_version": __version__,
            "repository_revision": repository_revision,
        }
        if project_config_digest or project_namespace:
            semantic_scope_data.update({
                "project_config_digest": project_config_digest,
                "project_namespace": project_namespace,
            })
        semantic_scope = stable_hash(semantic_scope_data)
        is_code_bound = (
            admission_action in {
                "review", "review_diff", "solve", "complete_code", "generate_tests", "scaffold",
            }
            or source.startswith("code_")
            or source.startswith("repo:")
            or bool(project_namespace)
            or bool(semantic_context_fingerprint)
        )
        allow_semantic_cache = use_cache and not (is_code_bound and not repository_revision)
        started = time.perf_counter()
        cache_layer = "miss"
        semantic_score = 0.0
        semantic_miss_reason = ""
        requested_model = model

        def compute_inner() -> dict[str, Any]:
            nonlocal semantic_score, semantic_miss_reason
            if allow_semantic_cache and semantic_query:
                detailed_get = getattr(self.semantic_cache, "get_with_reason", None)
                if callable(detailed_get):
                    detailed = detailed_get(semantic_scope, semantic_query)
                    if isinstance(detailed, tuple) and len(detailed) == 3:
                        semantic, semantic_score, semantic_miss_reason = detailed
                    else:
                        semantic, semantic_score = self.semantic_cache.get(semantic_scope, semantic_query)
                        semantic_miss_reason = "reason_unavailable"
                else:
                    semantic, semantic_score = self.semantic_cache.get(semantic_scope, semantic_query)
                    semantic_miss_reason = "reason_unavailable"
                if isinstance(semantic, dict):
                    reused = copy.deepcopy(semantic)
                    reused["_lah_cache_origin"] = "semantic"
                    reused["_lah_semantic_similarity"] = semantic_score
                    return reused
            elif semantic_query:
                semantic_miss_reason = "cache_disabled" if not use_cache else "context_ineligible"

            availability = getattr(self.runtime, "is_online", None)
            if callable(availability):
                try:
                    backend_online = bool(availability())
                except Exception:
                    backend_online = True
                if not backend_online:
                    return {
                        "success": False,
                        "unsupported": True,
                        "degraded": True,
                        "terminal": False,
                        "retryable": True,
                        "error_code": "local_backend_unavailable",
                        "error": "No local model backend is currently available; retry after the backend is online.",
                        "model": requested_model,
                    }

            tier_ranks = {"fast_code": 0, "general": 0, "heavy_code": 1, "reasoning": 2}

            def model_tier_rank(candidate_model: str) -> int:
                return max(
                    (rank for role_name, rank in tier_ranks.items()
                     if str(self.config.get("models", {}).get(role_name, "")) == str(candidate_model or "")),
                    default=0,
                )

            requested_rank = model_tier_rank(requested_model)
            # Runtime failover must keep the router's quality floor for this request.
            candidates = [requested_model]
            if allow_model_fallback:
                candidates.extend(
                    candidate for candidate in self._fallback_models(requested_model)
                    if model_tier_rank(candidate) >= requested_rank
                )
            errors: list[str] = []
            attempt_failures: list[dict[str, Any]] = []
            retryable_error = False
            circuit_open_error = False
            timeout_error = False
            preempted_error = False
            cancel_requested = False
            scheduler_state = ""

            def record_attempt_failures(*, recovered: bool) -> None:
                for failed in attempt_failures:
                    self.telemetry.record_error(
                        "ollama", f"{source}:model_attempt", failed["error"],
                        error_type_override=failed["error_type"],
                        error_code_override=failed["error_code"],
                        retryable=failed["retryable"], recovered=recovered,
                    )
            for index, candidate in enumerate(candidates):
                breaker_key = f"model:{candidate}"
                breaker_admission = self.breakers.allow(breaker_key)
                if not breaker_admission:
                    circuit_open_error = True
                    errors.append(f"{candidate}: circuit open")
                    self.telemetry.record_stage(action=source, stage="model_attempt", model=candidate, success=False, degraded=True, error_type="circuit_open")
                    continue
                probe_generation = breaker_admission.probe_generation

                def run(candidate_model: str = candidate) -> dict[str, Any]:
                    nonlocal mode_pause_result
                    def cancelled_result() -> dict[str, Any]:
                        return {
                            "success": False, "cancelled": True, "preempted": True,
                            "reason": "cancelled",
                            "error": "conversation generation cancelled for resource release",
                            "model": candidate_model, "terminal": True, "retryable": False,
                            "_cacheable": False,
                        }
                    if cancel_event is not None and cancel_event.is_set():
                        return cancelled_result()
                    candidate_role = (
                        str(effective_route.get("resident_execution_role") or role)
                        if candidate_model == str(effective_route.get("model") or "")
                        else role
                    )
                    # A smart->fast resilience fallback may have a smaller context window
                    # than the originally requested model. Re-fit locally instead of
                    # relying on implicit server truncation or turning an outage into OOM.
                    candidate_hint = self.model_policy.profile(
                        candidate_model, role=candidate_role,
                        input_tokens=prepared.estimated_tokens + fixed_input_tokens, output_tokens=max_tokens,
                        background=source.startswith("preprocess:"),
                        vram_free_mb=vram_free,
                    )
                    candidate_prompt_budget = min(
                        int(saving.get("max_local_input_tokens", 56000)),
                        candidate_hint.prompt_budget_tokens - fixed_input_tokens,
                    )
                    if candidate_prompt_budget < 64:
                        return {
                            "success": False, "model": candidate_model,
                            "error": "context cannot fit the system prompt, output schema and request prompt",
                            "error_code": "context_budget_exceeded", "terminal": True, "retryable": False,
                        }
                    candidate_prepared = fit_text(prepared.text, candidate_prompt_budget)
                    payload, candidate_profile = self.model_policy.apply_payload(
                        candidate_model,
                        {"model": candidate_model, "prompt": candidate_prepared.text, "system": system, "stream": False,
                         "keep_alive": self.config.get("ollama", {}).get("keep_alive", "-1"),
                         "options": {"num_predict": max_tokens, "temperature": float(temperature)}},
                        role=candidate_role,
                        input_tokens=candidate_prepared.estimated_tokens + fixed_input_tokens,
                        output_tokens=max_tokens,
                        background=source.startswith("preprocess:"), preserve_explicit_think=False,
                        vram_free_mb=vram_free,
                    )
                    if format:
                        payload["format"] = format
                    trace_observer = observer()
                    trace_payload = dict(payload)
                    if project_settings is not None or trace_system_override is not None:
                        trace_payload["system"] = trace_system
                    def request_candidate() -> dict[str, Any]:
                        stream = getattr(self.runtime, "request_stream", None)
                        if callable(stream):
                            if trace_observer is not None:
                                trace_observer.model_request(trace_payload)
                            return stream(
                                "/api/generate", payload,
                                trace_observer.output_delta if trace_observer is not None else (lambda _chunk: None),
                                on_thinking=getattr(trace_observer, "thinking_delta", None) if trace_observer is not None else None,
                                timeout=max(0.05, request_deadline - time.monotonic()),
                                deadline=request_deadline,
                                should_stop=cancel_event.is_set,
                            )
                        interruptible = getattr(self.runtime, "request_interruptible", None)
                        if cancel_event is not None and callable(interruptible):
                            if trace_observer is not None:
                                trace_observer.model_request(trace_payload)
                            result = interruptible(
                                "/api/generate", payload, should_stop=cancel_event.is_set,
                                timeout=max(0.05, request_deadline - time.monotonic()),
                                deadline=request_deadline,
                            )
                            if trace_observer is not None and result.get("response"):
                                trace_observer.output_delta(str(result["response"]))
                            return result
                        if trace_observer is not None:
                            trace_observer.model_request(trace_payload)
                            return self.runtime.request_stream(
                                "/api/generate", payload, trace_observer.output_delta,
                                on_thinking=getattr(trace_observer, "thinking_delta", None),
                                timeout=max(0.05, request_deadline - time.monotonic()),
                                deadline=request_deadline,
                                should_stop=cancel_event.is_set,
                            )
                        return self.runtime.request("/api/generate", payload)

                    admission = getattr(self, "inference_admission", None)
                    if callable(admission):
                        # Recheck at backend handoff; scheduler delay can stale the
                        # earlier mode snapshot. Do not hold the mode lock over I/O.
                        with admission(admission_action) as rejection:
                            if rejection is not None:
                                if rejection.get("code") == "operational_mode_blocked":
                                    rejection_mode = OperationalModeSnapshot(
                                        str(rejection.get("operational_mode") or "maintenance"),
                                        int(rejection.get("operational_mode_revision", 0) or 0),
                                        None,
                                        bool(rejection.get("operational_mode_degraded", False)),
                                    )
                                    mode_rejection = operational_mode_gate_error(
                                        rejection_mode, admission_action,
                                    )
                                    if mode_rejection is not None:
                                        mode_pause_result = mode_rejection
                                        return mode_rejection
                                mode_pause_result = rejection
                                return rejection
                            response = request_candidate()
                    else:
                        # Minimal/test runtimes may not provide the shared admission
                        # lock, so refresh the mode immediately before the handoff.
                        try:
                            mode = load_operational_mode(configured_state_dir(self.config, create=False))
                        except Exception:
                            mode = None
                        mode_rejection = operational_mode_gate_error(mode, admission_action)
                        if mode_rejection is not None:
                            mode_pause_result = mode_rejection
                            return mode_rejection
                        response = request_candidate()
                    repetition_loop = response.get("_lah_repetition_loop_detected") is True
                    if response.get("cleanup_unconfirmed") or (
                        not repetition_loop and (response.get("outcome_unknown") or response.get("_lah_partial_response"))
                    ):
                        return {"success": False, "error": response.get("error") or "model response was interrupted",
                                "model": candidate_model, "terminal": True, "retryable": False,
                                "_lah_partial_response": bool(response.get("_lah_partial_response")),
                                "outcome_unknown": bool(response.get("outcome_unknown")),
                                "cleanup_unconfirmed": bool(response.get("cleanup_unconfirmed")),
                                "context_recovery": response.get("context_recovery"),
                                "_lah_retry_count": int(response.get("_lah_retry_count", 0) or 0)}
                    if (cancel_event is not None and cancel_event.is_set()) or response.get("preempted") is True:
                        return cancelled_result()
                    if response.get("preempted"):
                        return {
                            "success": False,
                            "error": str(response.get("error") or "model request cancelled"),
                            "model": candidate_model,
                            "preempted": True,
                            "terminal": True,
                            "retryable": False,
                            "error_code": "model_request_cancelled",
                        }
                    if response.get("timed_out"):
                        return {
                            "success": False,
                            "error": str(response.get("error") or "model request deadline exceeded"),
                            "model": candidate_model,
                            "timed_out": True,
                            "terminal": False,
                            "retryable": True,
                            "error_code": "model_request_timeout",
                        }
                    if "error" in response:
                        retryable = is_retryable_local_backend_error(response["error"])
                        return {
                            "success": False, "error": response["error"], "model": candidate_model,
                            "retryable": retryable, "terminal": not retryable,
                            "error_code": "local_backend_transport" if retryable else "local_model_error",
                            "_lah_retry_count": int(response.get("_lah_retry_count", 0) or 0),
                            "_lah_partial_response": bool(response.get("_lah_partial_response")),
                            "_lah_repetition_loop_detected": response.get("_lah_repetition_loop_detected") is True,
                            "outcome_unknown": bool(response.get("outcome_unknown")),
                            "cleanup_unconfirmed": bool(response.get("cleanup_unconfirmed")),
                            "context_recovery": response.get("context_recovery"),
                            **_backend_completion_metadata(response),
                        }
                    raw_text = response.get("response", "")
                    clean_text, parsed_thinking = postprocess_model_output(raw_text, role=role)
                    thinking = response.get("thinking") or parsed_thinking
                    if response.get("done_reason") == "length":
                        return {"success": False, "error": "local model output reached its token limit",
                                "error_code": "model_output_truncated", "model": candidate_model,
                                "status_code": 422,
                                "requested_model": requested_model, "text": clean_text,
                                "output_truncated": True, "stop_reason": "length",
                                "final_response_produced": bool(clean_text.strip()), "final_response_status": "truncated",
                                "terminal": True, "retryable": False, "_cacheable": False,
                                **({"_lah_backend_completed": True} if response.get("done") is True else {})}
                    if not clean_text.strip():
                        return {
                            "success": False, "error": "local model returned empty response",
                            "error_code": "model_empty_response", "model": candidate_model,
                            "requested_model": requested_model, "text": "", "thinking": thinking,
                            "final_response_produced": False, "final_response_status": "empty",
                            "terminal": False, "retryable": True, "_cacheable": False,
                            "_lah_retry_count": int(response.get("_lah_retry_count", 0) or 0),
                            **_backend_completion_metadata(response),
                        }
                    return {
                        "success": True, "model": candidate_model, "requested_model": requested_model,
                        "text": clean_text, "thinking": thinking,
                        "final_response_produced": True,
                        "final_response_status": "produced",
                        "load_duration_ns": response.get("load_duration", 0), "eval_count": response.get("eval_count", 0),
                        "prompt_eval_count": response.get("prompt_eval_count", 0),
                        "prompt_eval_duration_ns": response.get("prompt_eval_duration", 0),
                        "eval_duration_ns": response.get("eval_duration", 0), "total_duration_ns": response.get("total_duration", 0),
                        "_lah_retry_count": int(response.get("_lah_retry_count", 0) or 0),
                        "execution_profile": candidate_profile.cache_scope(),
                        **({"context_recovery": response["context_recovery"]} if response.get("context_recovery") is not None else {}),
                        "_lah_provider": response.get("_lah_provider", "ollama"),
                        "_lah_cache_origin": "ollama", "fallback_used": candidate_model != requested_model,
                        "_cacheable": candidate_model == requested_model and not response.get("context_recovery"),
                    }

                try:
                    scheduler_options = {"background": True} if source.startswith("preprocess:") else {}
                    result = self.scheduler.submit(
                        candidate, source=source if index == 0 else f"{source}:fallback", execute=run, priority=priority,
                        wait_timeout=max(0.05, request_deadline - time.monotonic()),
                        cancel_event=cancel_event, **scheduler_options,
                    )
                except SchedulerCancelledError as exc:
                    cleanup_wait = max(0.0, min(0.5, request_deadline - time.monotonic()))
                    if exc.job.done.wait(cleanup_wait):
                        result = {
                            "success": False, "cancelled": True, "preempted": True,
                            "error": str(exc), "model": candidate,
                            "terminal": True, "retryable": False,
                        }
                    else:
                        result = {
                            "success": False, "error": "model worker cleanup unconfirmed after cancellation",
                            "error_code": "scheduler_cleanup_unconfirmed", "model": candidate,
                            "cleanup_unconfirmed": True, "outcome_unknown": True,
                            "terminal": True, "retryable": False,
                        }
                except TimeoutError as exc:
                    timeout_error = True
                    retryable_error = True
                    cancel_event.set()
                    result = {
                        "success": False,
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                        "model": candidate,
                        "terminal": False,
                        "retryable": True,
                        "error_code": str(getattr(exc, "error_code", "model_request_timeout")),
                    }
                    job_id = getattr(exc, "job_id", None)
                    if job_id is not None:
                        result["scheduler_job_id"] = int(job_id)
                    state = getattr(exc, "state", "")
                    if state:
                        result["scheduler_state"] = str(state)
                        scheduler_state = str(state)
                    cancel_requested = True
                except Exception as exc:
                    retryable = getattr(exc, "retryable", None)
                    if retryable is None:
                        retryable = is_retryable_local_backend_error(exc)
                    error_code = getattr(exc, "error_code", None)
                    if not error_code:
                        error_code = "local_backend_transport" if retryable else "local_model_error"
                    result = {
                        "success": False, "error": str(exc), "error_type": type(exc).__name__, "model": candidate,
                        "retryable": bool(retryable), "terminal": not bool(retryable),
                        "error_code": str(error_code),
                    }
                    if getattr(exc, "admission", None):
                        result["admission"] = exc.admission
                if mode_pause_result is not None:
                    if probe_generation is not None:
                        self.breakers.abandon_probe(breaker_key, probe_generation=probe_generation)
                    return mode_pause_result
                retryable_error = retryable_error or bool(result.get("retryable", False))
                if result.get("output_truncated") is True:
                    self.breakers.success(breaker_key, probe_generation=probe_generation)
                    self.telemetry.record_stage(action=source, stage="model_attempt", model=candidate,
                                                success=False, degraded=index > 0, error_type="model_output_truncated")
                    return result
                if result.get("success"):
                    self.breakers.success(breaker_key, probe_generation=probe_generation)
                    if candidate != requested_model:
                        self.fallback_count += 1
                    record_attempt_failures(recovered=True)
                    return result
                repetition_loop = result.get("_lah_repetition_loop_detected") is True
                if result.get("cleanup_unconfirmed") or (
                    not repetition_loop and (result.get("_lah_partial_response") or result.get("outcome_unknown"))
                ):
                    self.breakers.failure(breaker_key, probe_generation=probe_generation)
                    attempt_failures.append({"error": str(result.get("error", "model response interrupted")),
                                             "error_type": "model_attempt_interrupted", "error_code": "model_attempt_interrupted",
                                             "retryable": False})
                    self.telemetry.record_stage(action=source, stage="model_attempt", model=candidate,
                                                success=False, degraded=index > 0, error_type="model_attempt_interrupted")
                    record_attempt_failures(recovered=False)
                    return {**result, "terminal": True, "retryable": False, "_cacheable": False}
                if result.get("preempted"):
                    if probe_generation is not None:
                        self.breakers.abandon_probe(breaker_key, probe_generation=probe_generation)
                    preempted_error = True
                    errors.append(f"{candidate}: {result.get('error') or 'model request cancelled'}")
                    break
                if result.get("timed_out"):
                    timeout_error = True
                self.breakers.failure(breaker_key, probe_generation=probe_generation)
                attempt_error = str(result.get("error", "failed"))
                attempt_retries = int(result.get("_lah_retry_count", 0) or 0)
                self.telemetry.record_stage(action=source, stage="model_attempt", model=candidate, success=False, degraded=index > 0, retry_count=attempt_retries, error_type="model_attempt_failed")
                attempt_failures.append({
                    "model": candidate,
                    "error": attempt_error,
                    "error_type": str(result.get("error_type", "")),
                    "error_code": str(result.get("error_code", "")),
                    "retryable": bool(result.get("retryable", True)),
                    "_lah_backend_completed": result.get("_lah_backend_completed") is True,
                    "_lah_repetition_loop_detected": repetition_loop,
                    "admission": result.get("admission") if isinstance(result.get("admission"), dict) else {},
                })
                errors.append(f"{candidate}: {attempt_error}")
                if timeout_error:
                    break

            # Same exact prompt may be served stale only as a resilience fallback.
            if use_cache and not preempted_error and not cancel_requested and not timeout_error and bool(resilience.get("serve_stale_on_error", True)):
                stale = self.stale_generation_cache.get(cache_key)
                if isinstance(stale, dict):
                    reused = copy.deepcopy(stale)
                    reused["_lah_cache_origin"] = "stale"
                    reused["stale_fallback"] = True
                    reused["runtime_errors"] = errors[-3:]
                    record_attempt_failures(recovered=True)
                    return reused
            record_attempt_failures(recovered=False)
            failure = {
                "success": False,
                "error": "; ".join(errors) or "all local model attempts failed",
                "model": requested_model,
            }
            if attempt_failures:
                last_failure = attempt_failures[-1]
                failure["error_type"] = last_failure["error_type"]
                failure["error_code"] = last_failure["error_code"]
                for key in ("_lah_backend_completed", "_lah_repetition_loop_detected"):
                    if last_failure.get(key) is True:
                        failure[key] = True
                last_admission = last_failure.get("admission", {})
                for key in ("state", "reason"):
                    value = last_admission.get(key)
                    if isinstance(value, str) and value and len(value) <= 80 and all(c.isalnum() or c == "_" for c in value):
                        failure[f"last_admission_{key}"] = value
                if "last_admission_state" in failure or "last_admission_reason" in failure:
                    failure["last_admission_model"] = last_failure["model"]
            if retryable_error:
                failure.update({"terminal": False, "retryable": True})
            if circuit_open_error and not preempted_error and not cancel_requested:
                failure.update({
                    "terminal": False,
                    "retryable": True,
                    "error_code": "model_circuit_open",
                    "retry_after_seconds": max(1.0, float(self.breakers.cooldown_seconds)),
                })
            if timeout_error:
                failure["error_code"] = "model_request_timeout"
            if preempted_error:
                failure.update({"terminal": True, "retryable": False, "preempted": True, "error_code": "model_request_cancelled"})
            if cancel_requested:
                failure["cancel_requested"] = True
            if scheduler_state:
                failure["scheduler_state"] = scheduler_state
            return failure

        def compute() -> dict[str, Any]:
            nonlocal semantic_score
            if not semantic_query or not allow_semantic_cache:
                return compute_inner()
            # Different phrasings with the same strict semantic scope serialize only on a cache miss.
            # The second request rechecks semantic cache after the first completes, coalescing paraphrases.
            with self._semantic_scope_lock(semantic_scope):
                semantic, semantic_score = self.semantic_cache.get(semantic_scope, semantic_query)
                if isinstance(semantic, dict):
                    reused = copy.deepcopy(semantic)
                    reused["_lah_cache_origin"] = "semantic"
                    reused["_lah_semantic_similarity"] = semantic_score
                    return reused
                result = compute_inner()
                if allow_semantic_cache and isinstance(result, dict) and result.get("success", "error" not in result) and not result.get("fallback_used", False) and result.get("_cacheable", True) and not result.get("context_recovery"):
                    clean = {k: v for k, v in result.items() if not str(k).startswith("_lah_")}
                    try:
                        self.semantic_cache.set(semantic_scope, semantic_query, clean)
                    except (OSError, sqlite3.Error, ValueError) as cache_exc:
                        logger.debug(
                            "Semantic generation cache write skipped (%s)",
                            type(cache_exc).__name__,
                        )
                return result

        raw, cache_hit, coalesced = _generation_cache_dispatch(
            self.generation_cache, cache_key, compute, compute_inner,
            use_cache=use_cache, request_cancel_event=request_cancel_event,
        )
        if mode_pause_result is not None:
            return mode_pause_result
        origin = str(raw.get("_lah_cache_origin", "")) if isinstance(raw, dict) else ""
        if not use_cache:
            cache_layer = "disabled"
        elif coalesced:
            cache_layer = "single-flight"
        elif cache_hit:
            cache_layer = "exact"
        elif origin == "semantic":
            cache_layer = "semantic"
            semantic_score = float(raw.get("_lah_semantic_similarity", semantic_score) or 0.0)
        elif origin == "stale":
            cache_layer = "stale-on-error"
        else:
            cache_layer = "ollama"

        if use_cache and isinstance(raw, dict) and raw.get("success", "error" not in raw) and origin != "stale" and not raw.get("fallback_used", False) and not raw.get("context_recovery") and raw.get("final_response_produced", True):
            clean_stale = {k: v for k, v in raw.items() if not str(k).startswith("_lah_")}
            try:
                self.stale_generation_cache.set(cache_key, clean_stale)
            except (OSError, sqlite3.Error, ValueError) as cache_exc:
                logger.debug(
                    "Stale generation cache write skipped (%s)",
                    type(cache_exc).__name__,
                )

        result = copy.deepcopy(raw)
        queue_wait_ms = float(result.get("_lah_scheduler_queue_wait_ms", 0) or 0) if cache_layer == "ollama" else 0.0
        service_ms = float(result.get("_lah_scheduler_service_ms", 0) or 0) if cache_layer == "ollama" else 0.0
        retry_count = int(result.get("_lah_retry_count", 0) or 0) if cache_layer == "ollama" else 0
        for internal_key in ["_lah_cache_origin", "_lah_semantic_similarity", "_lah_scheduler_queue_wait_ms", "_lah_scheduler_service_ms", "_lah_scheduler_background", "_lah_retry_count"]:
            result.pop(internal_key, None)
        effective_cache_hit = cache_hit or cache_layer in {"semantic", "single-flight", "stale-on-error"}
        decision_reason = "cache_disabled" if not use_cache else cache_decision_reason(
            cache_layer, semantic_query=semantic_query, semantic_miss_reason=semantic_miss_reason,
        )
        self.telemetry.record_stage(
            action=source,
            stage="cache_decision",
            success=True,
            error_type=decision_reason,
        )
        trace_observer = observer()
        trace_event = getattr(trace_observer, "event", None)
        if callable(trace_event):
            semantic_hit_reasons = {"exact_l1_hit", "exact_l2_hit", "semantic_hit"}
            try:
                trace_event("cache_decision", {
                    "cache_hit": bool(effective_cache_hit),
                    "cache_layer": cache_layer,
                    "decision": decision_reason,
                    "coalesced": bool(coalesced),
                    "semantic_miss_reason": semantic_miss_reason if semantic_miss_reason not in semantic_hit_reasons else None,
                    "semantic_similarity": round(float(semantic_score), 5) if semantic_miss_reason == "below_threshold" else None,
                })
            except Exception:
                logger.debug("Cache decision trace write failed", exc_info=True)
        result["cache_hit"] = effective_cache_hit
        result["cache_layer"] = cache_layer
        result["semantic_similarity"] = round(float(semantic_score), 5) if cache_layer == "semantic" else None
        result["coalesced"] = coalesced
        result["prompt_budget"] = {
            "estimated_tokens": prepared.estimated_tokens, "original_estimated_tokens": prepared.original_tokens,
            "truncated": prepared.truncated,
        }

        full_text = str(result.get("text", ""))
        full_output_tokens = estimate_tokens(full_text)
        provider_usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
        try:
            cache_read_tokens = max(0, int(
                result.get("cache_read_tokens", provider_usage.get("cache_read_tokens", 0)) or 0
            ))
        except (TypeError, ValueError, OverflowError):
            cache_read_tokens = 0
        if (not internal) and bool(saving.get("compact_responses", True)):
            result = self.artifacts.compact(result, kind=source)
        result["latency"] = {
            "queue_wait_ms": round(max(0.0, queue_wait_ms), 1),
            "service_ms": round(max(0.0, service_ms), 1),
        }
        inline_tokens = estimate_tokens(str(result.get("text", "")))
        compact_saved = max(0, full_output_tokens - inline_tokens)
        cached_compute_tokens = (prepared.estimated_tokens + full_output_tokens) if cache_layer in {"exact", "semantic", "single-flight", "stale-on-error"} else 0
        result["token_saving"] = {
            "compact_output_tokens_avoided_est": compact_saved,
            "delegated_cloud_context_tokens_avoided_est": max(0, int(measured_cloud_context_tokens)),
            # Separate from cloud-context savings: these are tokens the local model
            # did not need to process/generate because a cache/single-flight result
            # was reused. Keeping the metric separate prevents double counting.
            "local_compute_tokens_avoided_est": max(0, int(cached_compute_tokens)),
        }

        success = bool(result.get("success", "error" not in result))
        if self.tuner is not None and cache_layer == "ollama" and success:
            self._observe_tuner_safely(
                str(result.get("model", model)),
                result,
                (time.perf_counter() - started) * 1000,
            )
        error_type = "" if success else "model_request_failed"
        self.telemetry.record(
            action=source, model=str(result.get("model", model)), cache_hit=effective_cache_hit, coalesced=coalesced,
            cache_layer=cache_layer, input_tokens=prepared.estimated_tokens,
            cache_read_tokens=cache_read_tokens, output_tokens=full_output_tokens,
            task_type=source.split(":", 1)[1] if source.startswith("delegate:") else source.split(":", 1)[0],
            avoided_cloud_tokens=max(0, int(measured_cloud_context_tokens)) + compact_saved,
            duration_ms=(time.perf_counter() - started) * 1000, queue_wait_ms=queue_wait_ms, service_ms=service_ms,
            load_duration_ms=float(result.get("load_duration_ns", 0) or 0) / 1_000_000,
            success=success, fallback_used=bool(result.get("fallback_used", False)), retry_count=retry_count,
            degraded=bool(result.get("stale_fallback", False) or result.get("fallback_used", False)), error_type=error_type,
        )
        if not success:
            self.telemetry.record_error(
                "ollama", source, result.get("error", "model request failed"),
                error_type_override=str(result.get("error_type", "")),
                error_code_override=str(result.get("error_code", "")),
                retryable=True,
            )
        return result

    @staticmethod
    def _conversation_user_prompt(task: str, context: str = "") -> str:
        prompt = f"TASK:\n{task}\n"
        if context:
            prompt += f"\nCONTEXT:\n{context}\n"
        return prompt

    @staticmethod
    def _conversation_transcript(messages: list[dict[str, str]], next_user_prompt: str) -> str:
        rendered = []
        for message in messages:
            role = "USER" if message.get("role") == "user" else "ASSISTANT"
            rendered.append(f"{role}:\n{message.get('content', '')}")
        rendered.append(f"USER:\n{next_user_prompt}")
        return "CONVERSATION:\n\n" + "\n\n".join(rendered)

    def _conversation_prompt_limit(self) -> int:
        cfg = self.config.get("model_conversations", {})
        return max(256, int(cfg.get("max_prompt_tokens", self.config.get("token_saving", {}).get("max_local_input_tokens", 56000))))

    def _conversation_error(self, conversation_id: str, error: str) -> dict[str, Any]:
        active = error == "conversation is already running"
        return {
            "success": False,
            "conversation_id": conversation_id,
            "error": error,
            "terminal": not active,
            "retryable": active,
            "in_progress": active,
        }

    @staticmethod
    def _conversation_cancelled(conversation_id: str) -> dict[str, Any]:
        return {
            "success": False, "conversation_id": conversation_id,
            "error": "conversation generation cancelled for resource release",
            "reason": "cancelled", "cancelled": True, "preempted": True,
            "terminal": True, "retryable": False,
        }

    def _start_conversation(
        self,
        *,
        prompt: str,
        route: dict[str, Any],
        system: str,
        max_tokens: int,
        temperature: float,
        source: str,
        priority: int,
        trace_system: str | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        if cancel_event is not None and cancel_event.is_set():
            return self._conversation_cancelled("")
        if estimate_tokens(prompt) + estimate_tokens(system) > self._conversation_prompt_limit():
            return self._conversation_error("", "conversation prompt limit exceeded")
        conversation = self.conversations.start_reserved({
            "model": route["model"], "system": system,
            "trace_system": system if trace_system is None else trace_system,
            "max_tokens": max_tokens,
            "temperature": temperature, "source": source, "priority": priority,
            "route": dict(route),
        })
        if conversation is None:
            return self._conversation_error("", "conversation capacity reached")
        try:
            result = self._generate(
                route["model"], prompt, system, max_tokens, temperature, source=source, priority=priority,
                internal=True, use_cache=False, trace_system_override=trace_system,
                cancel_event=cancel_event,
                route=route,
            )
        except Exception:
            self.conversations.discard(conversation.conversation_id)
            raise
        if not result.get("success", "error" not in result):
            self.conversations.discard(conversation.conversation_id)
            return result
        if cancel_event is not None and cancel_event.is_set():
            self.conversations.discard(conversation.conversation_id)
            return self._conversation_cancelled(conversation.conversation_id)
        if not self.conversations.complete(conversation.conversation_id, prompt, str(result.get("text", ""))):
            return self._conversation_error(
                conversation.conversation_id,
                "conversation expired or was lost while model was running",
            )
        result["conversation_id"] = conversation.conversation_id
        result["route"] = dict(route)
        return result

    def continue_conversation(
        self, args: dict[str, Any], *, cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        reject_retired_tenancy_fields(args)
        conversation_id = str(args.get("conversation_id", "")).strip()
        task = str(args.get("task", "")).strip()
        if not conversation_id:
            return self._conversation_error("", "conversation_id is required")
        if not task:
            return self._conversation_error(conversation_id, "task is required")
        if cancel_event is not None and cancel_event.is_set():
            return self._conversation_cancelled(conversation_id)
        conversation, error = self.conversations.reserve(conversation_id)
        if error:
            return self._conversation_error(conversation_id, error)
        assert conversation is not None
        user_prompt = self._conversation_user_prompt(task, str(args.get("context", "")))
        prompt = self._conversation_transcript(conversation.messages, user_prompt)
        settings = conversation.settings
        if estimate_tokens(prompt) + estimate_tokens(str(settings["system"])) > self._conversation_prompt_limit():
            self.conversations.abort(conversation_id)
            return self._conversation_error(conversation_id, "conversation prompt limit exceeded")
        try:
            result = self._generate(
                str(settings["model"]), prompt, str(settings["system"]), int(settings["max_tokens"]),
                float(settings["temperature"]), source=str(settings["source"]), priority=int(settings["priority"]),
                internal=True, use_cache=False,
                trace_system_override=str(settings.get("trace_system", settings["system"])),
                cancel_event=cancel_event,
                route=settings.get("route"),
            )
        except Exception:
            self.conversations.abort(conversation_id)
            raise
        if not result.get("success", "error" not in result):
            self.conversations.abort(conversation_id)
            return result
        if cancel_event is not None and cancel_event.is_set():
            self.conversations.abort(conversation_id)
            return self._conversation_cancelled(conversation_id)
        if not self.conversations.complete(
            conversation_id, user_prompt, str(result.get("text", "")),
        ):
            return self._conversation_error(
                conversation_id,
                "conversation expired or was lost while model was running",
            )
        result["conversation_id"] = conversation_id
        result["route"] = dict(settings["route"])
        return result


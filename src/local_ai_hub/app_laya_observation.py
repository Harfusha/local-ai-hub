from __future__ import annotations

from .app import (
    Any as Any,
    CompletionGateError as CompletionGateError,
    Mapping as Mapping,
    Path as Path,
    uuid as uuid,
)


LocalAIApp = None


class AppLayaObservationMixin:
    def _derive_laya_decision_baseline(self, request: Any, task: Any) -> dict[str, str] | None:
        """Derive deterministic baselines from authoritative Hub state."""
        from .laya_decisions import DecisionCategory, derive_watchdog_lifecycle_baseline

        if request.category is DecisionCategory.WATCHDOG:
            checkpoint = getattr(task, "checkpoint", None)
            return derive_watchdog_lifecycle_baseline(
                status=getattr(task, "status", None),
                request_evidence_ids=getattr(request, "evidence_ids", ()),
                checkpoint_evidence_ids=getattr(checkpoint, "evidence_ids", ()),
                options=getattr(request, "options", ()),
            )

        if request.category is DecisionCategory.COMPLETION_GAP:
            if not request.evidence_ids:
                return None
            checkpoint = getattr(task, "checkpoint", None)
            task_evidence_ids = getattr(checkpoint, "evidence_ids", ())
            evidence_id = next(
                (item for item in request.evidence_ids if item in task_evidence_ids),
                None,
            )
            task_id = getattr(task, "task_id", None)
            if not isinstance(evidence_id, str) or not isinstance(task_id, str) or not task_id:
                return None
            try:
                self.agent_tasks.validate_completion(task_id)
            except CompletionGateError:
                suggestion = "not_ready"
            else:
                suggestion = "ready"
            return {
                "method": "agent_os_completion_gate",
                "suggestion": suggestion,
                "evidence_id": evidence_id,
            }

        checkpoint = getattr(task, "checkpoint", None)
        task_evidence_ids = getattr(checkpoint, "evidence_ids", ()) if checkpoint else ()
        evidence_id = next(
            (item for item in request.evidence_ids if item in task_evidence_ids),
            None,
        )
        if not isinstance(evidence_id, str):
            return None

        if request.category is DecisionCategory.NEXT_STEP:
            status_val = getattr(getattr(task, "status", None), "value", str(getattr(task, "status", "")))
            if status_val in {"verifying", "failed"}:
                sugg = "run_test"
            elif status_val == "completed":
                sugg = "ask_human"
            elif status_val == "active":
                sugg = "inspect_source"
            else:
                sugg = "retrieve_evidence"
            if sugg not in request.options:
                sugg = request.options[0] if request.options else "retrieve_evidence"
            return {
                "method": "pipeline_step_progress",
                "suggestion": sugg,
                "evidence_id": evidence_id,
            }

        if request.category is DecisionCategory.MODEL_ROUTE:
            contract = getattr(task, "contract", None)
            risk = getattr(contract, "risk_profile", "normal") if contract else "normal"
            sugg = "smart" if risk in {"high", "critical"} else "fast"
            if sugg not in request.options:
                sugg = request.options[0] if request.options else "fast"
            return {
                "method": "model_router_classify",
                "suggestion": sugg,
                "evidence_id": evidence_id,
            }

        if request.category is DecisionCategory.CONTEXT_BUDGET:
            sugg = "standard" if "standard" in request.options else (request.options[0] if request.options else "compact")
            return {
                "method": "repo_context_token_budget",
                "suggestion": sugg,
                "evidence_id": evidence_id,
            }

        if request.category is DecisionCategory.REDUNDANT_STEP:
            sugg = "validation_still_required" if "validation_still_required" in request.options else (request.options[0] if request.options else "possible_duplicate")
            return {
                "method": "command_broker_dedup",
                "suggestion": sugg,
                "evidence_id": evidence_id,
            }

        if request.category is DecisionCategory.DELEGATION:
            sugg = "no_delegation" if "no_delegation" in request.options else (request.options[0] if request.options else "review_only")
            return {
                "method": "pipeline_worker_escalation",
                "suggestion": sugg,
                "evidence_id": evidence_id,
            }

        return None

    def _record_laya_decision_eligibility(self, request: Any) -> bool:
        try:
            telemetry = getattr(self, "telemetry", None)
            recorder = getattr(telemetry, "record_laya_eligibility", None)
            return bool(recorder and recorder(
                decision_id=request.decision_id,
                mode=request.mode.value,
                category=request.category.value,
            ) is True)
        except Exception as exc:
            warning = getattr(getattr(self, "logger", None), "warning", None)
            if callable(warning):
                warning("Laya eligibility telemetry failed: %s", type(exc).__name__)
            return False

    def _record_laya_runtime_decision(
        self,
        request: Any,
        decision: Any,
        runtime: Any | None = None,
    ) -> bool:
        """Store the typed decision projection through existing metadata telemetry."""
        try:
            telemetry = getattr(self, "telemetry", None)
            recorder = getattr(telemetry, "record_laya_decision", None)
            if not callable(recorder):
                return False
            metadata = decision.metadata()
            metadata.update({
                "runtime_latency_ms": getattr(runtime, "latency_ms", None),
                "inference_latency_ms": getattr(runtime, "inference_latency_ms", None),
                "queue_wait_ms": getattr(runtime, "adapter_queue_wait_ms", None),
                "backend": getattr(runtime, "provider", None),
                "fallback_used": (
                    getattr(runtime, "fallback_reason", None) is not None
                    if runtime is not None else None
                ),
                "fallback_reason": getattr(runtime, "fallback_reason", None),
            })
            recorded = recorder(
                metadata,
                repository_id=request.repository_id,
                task_id=request.task_id,
                session_id=request.session_id,
            )
            collector = getattr(self, "training_collector", None)
            if collector and getattr(collector, "enabled", False):
                try:
                    cat = getattr(request, "category", None)
                    cat_val = str(getattr(cat, "value", cat) or "decision")
                    sugg = getattr(decision, "suggestion", None)
                    if sugg:
                        state_data = getattr(request, "state", None) or {}
                        if hasattr(state_data, "to_dict"):
                            state_data = state_data.to_dict()
                        elif not isinstance(state_data, dict):
                            state_data = {"raw": str(state_data)}
                        task_id = str(getattr(request, "task_id", "") or "unbound")
                        collector.record_laya_decision(
                            category=cat_val,
                            state=state_data,
                            question_text=f"Decision {cat_val} for task {task_id}",
                            expected_choice=str(sugg),
                            confidence_distribution={str(sugg): 1.0},
                        )
                except Exception as exc:
                    debug_log = getattr(getattr(self, "logger", None), "debug", None)
                    if callable(debug_log):
                        debug_log("Laya training collector record failed: %s", type(exc).__name__)
        except Exception as exc:
            warning = getattr(getattr(self, "logger", None), "warning", None)
            if callable(warning):
                warning("Laya decision telemetry failed: %s", type(exc).__name__)
            return False
        if recorded is not True:
            warning = getattr(getattr(self, "logger", None), "warning", None)
            if callable(warning):
                warning("Laya decision telemetry was not recorded")
            return False
        return True

    def _record_laya_capture_observation(
        self,
        status: str,
        reason: str,
        *,
        error_type: str = "",
    ) -> bool:
        """Persist typed capture lifecycle metadata without request content."""
        statuses = {"skipped", "queued", "captured", "failed"}
        reasons = {
            "laya_disabled", "context_unavailable", "task_identity_unavailable",
            "task_scope_unavailable", "session_identity_mismatch",
            "retrieval_provenance_unavailable", "backend_states_unavailable",
            "fewer_than_two_verified_sources", "no_unresolved_evidence_gap",
            "capture_executor_unavailable", "hub_shutdown", "capture_in_flight",
            "capture_queue_unavailable", "runtime_error", "outcome_not_captured",
            "runtime_outcome", "queued", "unspecified", "capture_exception",
            "checkpoint_unavailable", "decision_scope_unavailable",
            "decision_evidence_unavailable", "decision_context_unavailable", "decision_invalid",
            "decision_outcome",
            "completion_outcome", "completion_outcome_unavailable",
            "completion_no_candidate", "completion_scope_unavailable",
        }
        safe_status = status if status in statuses else "failed"
        safe_reason = reason if reason in reasons else "unspecified"
        recorder = getattr(getattr(self, "telemetry", None), "record_stage", None)
        if not callable(recorder):
            return False
        event = {
            "action": "laya_capture",
            "stage": safe_status,
            "bypass_reason": safe_reason,
            "success": safe_status != "failed",
        }
        if error_type:
            event["error_type"] = error_type
        try:
            recorder(**event)
            return True
        except Exception as exc:
            self.logger.warning("Laya capture telemetry failed: %s", type(exc).__name__)
            return False

    def _laya_inference_enabled(self) -> bool:
        config = getattr(self, "config", {})
        laya_cfg = config.get("laya", {}) if isinstance(config, Mapping) else {}
        return not (isinstance(laya_cfg, Mapping) and laya_cfg.get("enabled", True) is False)

    def queue_laya_completion_observation(self, operation: Any, root: str) -> dict[str, str]:
        """Persist a typed completion outcome asynchronously without affecting the gate."""
        if not self._laya_inference_enabled():
            self._record_laya_capture_observation("skipped", "laya_disabled")
            return {"status": "skipped", "reason": "laya_disabled"}
        if (
            type(operation) is not dict
            or set(operation) != {"task_id", "session_id", "outcome"}
            or not isinstance(root, str)
            or not root.strip()
            or not isinstance(operation.get("task_id"), str)
            or not operation["task_id"].strip()
            or not isinstance(operation.get("session_id"), str)
            or not operation["session_id"].strip()
        ):
            self._record_laya_capture_observation("skipped", "completion_scope_unavailable")
            return {"status": "skipped", "reason": "completion_scope_unavailable"}
        executor = getattr(self, "_status_dependency_executor", None)
        capture_lock = getattr(self, "_laya_capture_lock", None)
        capture_queue = getattr(self, "_laya_capture_queue", None)
        if (
            not callable(getattr(executor, "submit", None))
            or not callable(getattr(capture_lock, "acquire", None))
            or not isinstance(capture_queue, list)
        ):
            self._record_laya_capture_observation("skipped", "capture_executor_unavailable")
            return {"status": "skipped", "reason": "capture_executor_unavailable"}
        shutdown = getattr(self, "_shutdown", None)
        if shutdown is not None and shutdown.is_set():
            self._record_laya_capture_observation("skipped", "hub_shutdown")
            return {"status": "skipped", "reason": "hub_shutdown"}

        dispatch = False
        with capture_lock:
            if shutdown is not None and shutdown.is_set():
                self._record_laya_capture_observation("skipped", "hub_shutdown")
                return {"status": "skipped", "reason": "hub_shutdown"}
            if len(capture_queue) >= 16:
                self._record_laya_capture_observation("skipped", "capture_queue_unavailable")
                return {"status": "skipped", "reason": "capture_queue_unavailable"}
            capture_queue.append((
                {"action": "record_completion_outcome", "operation": operation},
                root,
                {},
            ))
            if not getattr(self, "_laya_capture_draining", False):
                self._laya_capture_draining = True
                dispatch = True
        if dispatch:
            try:
                future = executor.submit(self._drain_laya_capture_queue)
            except Exception as exc:
                with capture_lock:
                    discarded = len(capture_queue)
                    capture_queue.clear()
                    self._laya_capture_draining = False
                for _ in range(discarded):
                    self._record_laya_capture_observation(
                        "skipped", "capture_queue_unavailable", error_type=type(exc).__name__
                    )
                return {"status": "skipped", "reason": "capture_queue_unavailable"}

            def observe_dispatch(completed: Any) -> None:
                try:
                    error = completed.exception()
                except Exception as exc:
                    error = exc
                if error is None:
                    return
                with capture_lock:
                    discarded = len(capture_queue)
                    capture_queue.clear()
                    self._laya_capture_draining = False
                reason = "hub_shutdown" if shutdown is not None and shutdown.is_set() else "capture_queue_unavailable"
                for _ in range(discarded):
                    self._record_laya_capture_observation("skipped", reason, error_type=type(error).__name__)
                self.logger.warning("Laya decision queue stopped: %s", type(error).__name__)

            future.add_done_callback(observe_dispatch)
        if operation["outcome"].get("status") == "rejected":
            self._queue_laya_completion_gap_observation(operation, root)
        self._queue_laya_completion_next_step_observation(operation, root)
        self._record_laya_capture_observation("queued", "completion_outcome")
        return {"status": "queued", "reason": "completion_outcome"}

    def _queue_laya_completion_next_step_observation(
        self, operation: Mapping[str, Any], root: str
    ) -> dict[str, str]:
        """Capture bounded next-step context from a genuine completion validation."""
        try:
            from .laya_decisions import DecisionCategory, allowed_decision_options

            status = operation["outcome"].get("status")
            mutation_generation = operation["outcome"].get("mutation_generation")
            if status not in {"passed", "rejected"} or type(mutation_generation) is not int or mutation_generation < 0:
                return {"status": "skipped", "reason": "completion_scope_unavailable"}
            canonical_root = str(Path(root).resolve(strict=True))
            task = self.laya_candidates._find_task(self.agent_tasks, canonical_root, operation["task_id"])
            if self.laya_candidates._session_for_task(task) != operation["session_id"]:
                return {"status": "skipped", "reason": "completion_scope_unavailable"}
            checkpoint = getattr(task, "checkpoint", None)
            evidence_id = next(
                (item for item in getattr(checkpoint, "evidence_ids", ()) if isinstance(item, str) and item.strip()),
                None,
            )
            criteria = getattr(getattr(task, "contract", None), "acceptance_criteria", ())
            if evidence_id is None or not isinstance(criteria, (list, tuple)) or not criteria:
                self._record_laya_capture_observation("skipped", "decision_evidence_unavailable")
                return {"status": "skipped", "reason": "decision_evidence_unavailable"}
            task_input = "\n".join(item for item in criteria if isinstance(item, str) and item.strip())
            task_input = task_input.encode("utf-8", errors="replace")[:4096].decode("utf-8", errors="ignore").strip()
            if not task_input:
                self._record_laya_capture_observation("skipped", "decision_context_unavailable")
                return {"status": "skipped", "reason": "decision_context_unavailable"}
            decision_operation = {
                "action": "evaluate_decision",
                "task_id": operation["task_id"],
                "decision": {
                    "category": DecisionCategory.NEXT_STEP.value,
                    "evidence_ids": [evidence_id],
                    "options": sorted(allowed_decision_options(DecisionCategory.NEXT_STEP)),
                    "state": {
                        "completion_status": status,
                        "reason_code": f"completion_validation_{status}",
                        "mutation_generation": str(mutation_generation),
                    },
                    "training_content": {"task_input": task_input},
                },
            }
            return self.queue_laya_decision_observation(
                decision_operation,
                canonical_root,
                {
                    "method": "pipeline_step_progress",
                    "suggestion": "ask_human" if status == "passed" else "run_test",
                    "evidence_id": evidence_id,
                },
            )
        except Exception:
            self._record_laya_capture_observation("skipped", "completion_scope_unavailable")
            return {"status": "skipped", "reason": "completion_scope_unavailable"}

    def _queue_laya_completion_gap_observation(
        self, operation: Mapping[str, Any], root: str
    ) -> dict[str, str]:
        """Queue a redacted shadow decision for a naturally rejected completion gate."""
        try:
            from .laya_decisions import DecisionCategory, allowed_decision_options

            task_id = operation["task_id"]
            canonical_root = str(Path(root).resolve(strict=True))
            task = self.laya_candidates._find_task(self.agent_tasks, canonical_root, task_id)
            if self.laya_candidates._session_for_task(task) != operation["session_id"]:
                return {"status": "skipped", "reason": "completion_scope_unavailable"}
            checkpoint = getattr(task, "checkpoint", None)
            evidence_ids = getattr(checkpoint, "evidence_ids", ())
            evidence_id = next(
                (item for item in evidence_ids if isinstance(item, str) and item.strip()),
                None,
            )
            if evidence_id is None:
                self._record_laya_capture_observation("skipped", "decision_evidence_unavailable")
                return {"status": "skipped", "reason": "decision_evidence_unavailable"}

            outcome = operation["outcome"]
            mutation_generation = outcome.get("mutation_generation")
            if type(mutation_generation) is not int or mutation_generation < 0:
                self._record_laya_capture_observation("skipped", "completion_scope_unavailable")
                return {"status": "skipped", "reason": "completion_scope_unavailable"}
            decision_operation = {
                "action": "evaluate_decision",
                "task_id": task_id,
                "decision": {
                    "category": DecisionCategory.COMPLETION_GAP.value,
                    "evidence_ids": [evidence_id],
                    "options": sorted(allowed_decision_options(DecisionCategory.COMPLETION_GAP)),
                    "state": {
                        "completion_status": "not_ready",
                        "reason_code": "completion_gate_rejected",
                        "mutation_generation": str(mutation_generation),
                    },
                    "training_content": {},
                },
            }
            baseline = {
                "method": "agent_os_completion_gate",
                "suggestion": "not_ready",
                "evidence_id": evidence_id,
            }
            return self.queue_laya_decision_observation(decision_operation, canonical_root, baseline)
        except Exception:
            self._record_laya_capture_observation("skipped", "completion_scope_unavailable")
            return {"status": "skipped", "reason": "completion_scope_unavailable"}

    def queue_laya_decision_observation(
        self,
        operation: Any,
        root: str,
        baseline: Mapping[str, str],
    ) -> dict[str, str]:
        """Queue an automatic typed decision after authentic scope/evidence validation."""
        def skipped(reason: str) -> dict[str, str]:
            self._record_laya_capture_observation("skipped", reason)
            return {"status": "skipped", "reason": reason}

        if not self._laya_inference_enabled():
            return skipped("laya_disabled")
        if type(operation) is not dict or set(operation) != {"action", "task_id", "decision"}:
            return skipped("decision_invalid")
        if operation.get("action") != "evaluate_decision" or not isinstance(root, str) or not root.strip():
            return skipped("decision_scope_unavailable")
        laya_cfg = self.config.get("laya", {})
        runtime_cfg = laya_cfg.get("runtime", {}) if isinstance(laya_cfg, dict) else {}
        if (
            not isinstance(runtime_cfg, dict)
            or not isinstance(runtime_cfg.get("checkpoint_path"), str)
            or not runtime_cfg.get("checkpoint_path")
            or not isinstance(runtime_cfg.get("revision"), str)
            or not runtime_cfg.get("revision")
            or not isinstance(runtime_cfg.get("expected_sha256"), dict)
            or not runtime_cfg.get("expected_sha256")
        ):
            return skipped("checkpoint_unavailable")

        try:
            from .laya_decisions import DecisionCategory, DecisionInput, DecisionMode, DecisionRequest
            from .project_config import resolve_project_context

            canonical_root = str(Path(root).resolve(strict=True))
            project = resolve_project_context(canonical_root, Path(self.config["server"]["state_dir"]))
            repository_id = getattr(project, "coordination_id", None)
            task_id = operation["task_id"]
            if not isinstance(repository_id, str) or not repository_id:
                return skipped("decision_scope_unavailable")
            task = self.laya_candidates._find_task(self.agent_tasks, canonical_root, task_id)
            session_id = self.laya_candidates._session_for_task(task)
            decision_data = operation["decision"]
            if type(decision_data) is not dict or set(decision_data) != {
                "category", "evidence_ids", "options", "state", "training_content",
            }:
                return skipped("decision_invalid")
            request = DecisionRequest.from_mapping(
                {key: decision_data[key] for key in ("category", "evidence_ids", "options")},
                decision_id="laya_" + uuid.uuid4().hex,
                mode=DecisionMode.SHADOW,
                repository_id=repository_id,
                task_id=task_id,
                session_id=session_id,
            )
            if request.category is DecisionCategory.CONTEXT_SOURCE or not request.evidence_ids:
                return skipped("decision_evidence_unavailable")
            decision_input = DecisionInput.from_mapping({
                "state": decision_data["state"],
                "training_content": decision_data["training_content"],
            })
            expected_method = {
                DecisionCategory.MODEL_ROUTE: "model_router_classify",
                DecisionCategory.CONTEXT_BUDGET: "repo_context_token_budget",
                DecisionCategory.COMPLETION_GAP: "agent_os_completion_gate",
                DecisionCategory.DELEGATION: "pipeline_worker_escalation",
                DecisionCategory.WATCHDOG: "agent_os_task_lifecycle",
                DecisionCategory.REDUNDANT_STEP: "command_broker_dedup",
                DecisionCategory.NEXT_STEP: "pipeline_step_progress",
            }.get(request.category)
            baseline_value = dict(baseline)
            baseline_suggestion_valid = baseline_value.get("suggestion") in request.options
            if request.category is DecisionCategory.COMPLETION_GAP:
                baseline_suggestion_valid = baseline_value.get("suggestion") in {"ready", "not_ready"}
            if (
                expected_method is None
                or set(baseline_value) != {"method", "suggestion", "evidence_id"}
                or baseline_value.get("method") != expected_method
                or not baseline_suggestion_valid
                or baseline_value.get("evidence_id") not in request.evidence_ids
            ):
                return skipped("decision_invalid")
            candidate = self.laya_candidates._candidate_input({
                "decision_schema_version": "laya-decision-v1",
                "category": request.category.value,
                "state": decision_input.model_state(),
                "options": list(request.options),
                "language": "und",
                "preprocessing": {"name": "laya-runtime", "version": runtime_cfg["revision"]},
                "evidence_ids": list(request.evidence_ids),
            })
            self.laya_candidates._validate_context_source_evidence(
                candidate, evidence_store=self.evidence, canonical_root=canonical_root
            )
        except Exception:
            return skipped("decision_scope_unavailable")

        capture_lock = getattr(self, "_laya_capture_lock", None)
        capture_queue = getattr(self, "_laya_capture_queue", None)
        executor = getattr(self, "_status_dependency_executor", None)
        shutdown = getattr(self, "_shutdown", None)
        if (
            not callable(getattr(capture_lock, "acquire", None))
            or not isinstance(capture_queue, list)
            or not callable(getattr(executor, "submit", None))
        ):
            return skipped("capture_executor_unavailable")
        if shutdown is not None and shutdown.is_set():
            return skipped("hub_shutdown")
        dispatch = False
        with capture_lock:
            if shutdown is not None and shutdown.is_set():
                return skipped("hub_shutdown")
            if len(capture_queue) >= 16:
                return skipped("capture_queue_unavailable")
            capture_queue.append((operation, canonical_root, baseline_value))
            if not getattr(self, "_laya_capture_draining", False):
                self._laya_capture_draining = True
                dispatch = True
        self._record_laya_capture_observation("queued", "queued")
        if not dispatch:
            return {"status": "queued"}
        try:
            future = executor.submit(self._drain_laya_capture_queue)
        except Exception as exc:
            with capture_lock:
                discarded = len(capture_queue)
                capture_queue.clear()
                self._laya_capture_draining = False
            for _ in range(discarded):
                self._record_laya_capture_observation(
                    "skipped", "capture_queue_unavailable", error_type=type(exc).__name__
                )
            return {"status": "skipped", "reason": "capture_queue_unavailable"}

        def observe_dispatch(completed: Any) -> None:
            try:
                error = completed.exception()
            except Exception as exc:
                error = exc
            if error is None:
                return
            with capture_lock:
                discarded = len(capture_queue)
                capture_queue.clear()
                self._laya_capture_draining = False
            reason = "hub_shutdown" if shutdown is not None and shutdown.is_set() else "capture_queue_unavailable"
            for _ in range(discarded):
                self._record_laya_capture_observation("skipped", reason, error_type=type(error).__name__)
            self.logger.warning("Laya decision queue stopped: %s", type(error).__name__)

        future.add_done_callback(observe_dispatch)
        return {"status": "queued"}

    def capture_laya_context_source_from_context(
        self,
        request: Any,
        result: Any,
    ) -> dict[str, Any]:
        try:
            observation = self._capture_laya_context_source_from_context(request, result)
        except Exception as exc:
            self._record_laya_capture_observation(
                "failed", "capture_exception", error_type=type(exc).__name__
            )
            raise
        status = observation.get("status") if isinstance(observation, dict) else "failed"
        reason = observation.get("reason") if isinstance(observation, dict) else "outcome_not_captured"
        error_type = observation.get("error_type") if isinstance(observation, dict) else None
        if status == "queued":
            reason = "queued"
        elif not isinstance(reason, str):
            reason = "unspecified"
        if status != "queued":
            self._record_laya_capture_observation(
                status, reason, error_type=error_type if isinstance(error_type, str) else ""
            )
        return observation


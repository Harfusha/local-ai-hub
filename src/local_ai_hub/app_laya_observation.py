from __future__ import annotations

from .app import (
    Any as Any,
    CompletionGateError as CompletionGateError,
    Mapping as Mapping,
)


LocalAIApp = None


class AppLayaObservationMixin:
    def _derive_laya_decision_baseline(self, request: Any, task: Any) -> dict[str, str] | None:
        """Derive deterministic baselines from authoritative Hub state."""
        from .laya_decisions import DecisionCategory, derive_watchdog_lifecycle_baseline

        if task is None:
            preferred = {
                DecisionCategory.MODEL_ROUTE: "fast",
                DecisionCategory.CONTEXT_BUDGET: "standard",
                DecisionCategory.RETRIEVAL_STRATEGY: "hybrid",
                DecisionCategory.NEXT_STEP: "inspect_source",
                DecisionCategory.DELEGATION: "review_only",
                DecisionCategory.SUBAGENT_BUDGET: "single_agent",
            }.get(request.category)
            suggestion = preferred if preferred in request.options else next(iter(request.options), None)
            if not request.evidence_ids or suggestion is None:
                return None
            method = {
                DecisionCategory.MODEL_ROUTE: "model_router_classify",
                DecisionCategory.CONTEXT_BUDGET: "repo_context_token_budget",
                DecisionCategory.RETRIEVAL_STRATEGY: "hybrid_context_default",
                DecisionCategory.NEXT_STEP: "pipeline_step_progress",
                DecisionCategory.DELEGATION: "pipeline_worker_escalation",
                DecisionCategory.SUBAGENT_BUDGET: "request_delegation_budget",
            }.get(request.category)
            return ({"method": method, "suggestion": suggestion, "evidence_id": request.evidence_ids[0]}
                    if method else None)

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

        if request.category is DecisionCategory.SUBAGENT_BUDGET:
            if "single_agent" not in request.options:
                return None
            return {
                "method": "request_delegation_budget",
                "suggestion": "single_agent",
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
                provider_label=request.provider_label,
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
        baseline: Mapping[str, Any] | None = None,
    ) -> bool:
        """Store the typed decision projection through existing metadata telemetry."""
        try:
            telemetry = getattr(self, "telemetry", None)
            recorder = getattr(telemetry, "record_laya_decision", None)
            if not callable(recorder):
                return False
            metadata = decision.metadata()
            baseline_suggestion = baseline.get("suggestion") if isinstance(baseline, Mapping) else None
            baseline_available = isinstance(baseline_suggestion, str) and bool(baseline_suggestion)
            suggestion = getattr(decision, "suggestion", None)
            comparable = baseline_available and baseline_suggestion in getattr(request, "options", ())
            metadata.update({
                "provider_label": request.provider_label,
                "baseline_available": baseline_available,
                "baseline_match": (
                    suggestion == baseline_suggestion
                    if comparable and getattr(getattr(decision, "status", None), "value", None) == "success"
                    else None
                ),
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
                provider_label=request.provider_label,
            )
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
        statuses = {"captured", "failed"}
        reasons = {"runtime_outcome", "runtime_error", "outcome_not_captured", "capture_exception"}
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

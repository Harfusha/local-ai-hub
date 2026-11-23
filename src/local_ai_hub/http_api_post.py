from __future__ import annotations

from typing import Any, Mapping

from .http_server_proxy import services_module


class HttpPostHelpersMixin:
    def _handle_post_work_orders(self, payload: Any) -> None:
        if not getattr(services_module.APP, "work_orchestrator", None) or not services_module.APP.work_orchestrator.enabled:
            self._send(403, {"success": False, "unsupported": True, "error": "work orchestrator is disabled", "terminal": True}); return
        action = str(payload.get("action", "submit")).strip().lower().replace("-", "_")
        work_id = str(payload.get("work_id", "")).strip()

        def send_work_result(result: Any) -> None:
            if isinstance(result, dict) and result.get("error") == "work order not found":
                self._send(404, {**result, "terminal": True, "retryable": False}); return
            self._send(200, result)

        if action == "submit":
            self._send(200, services_module.APP.work_orchestrator.submit(payload)); return
        if action == "status":
            send_work_result(services_module.APP.work_orchestrator.status(work_id)); return
        if action == "wait":
            send_work_result(services_module.APP.work_orchestrator.wait(work_id, float(payload.get("timeout_seconds", 90)))); return
        if action == "get":
            send_work_result(services_module.APP.work_orchestrator.get(work_id, profile=str(payload.get("response_profile", "")), return_fields=payload.get("return_fields") if isinstance(payload.get("return_fields"), list) else None, max_output_tokens=int(payload.get("max_output_tokens", 0) or 0))); return
        if action == "cancel":
            send_work_result(services_module.APP.work_orchestrator.cancel(work_id)); return
        if action == "continue":
            send_work_result(services_module.APP.work_orchestrator.continue_work(work_id, str(payload.get("answer", "")))); return
        self._send(400, {"success": False, "error": "unknown work-order action", "terminal": True}); return

    def _handle_post_async_jobs(self, payload: Any) -> None:
        action = str(payload.get("action", "")).strip().lower().replace("-", "_")
        if action == "submit":
            if bool(payload.get("conversation", False)):
                self._send(400, {"success": False, "error": "conversations require delivery=sync", "terminal": True, "retryable": False}); return
            raw_job_action = payload.get("job_action", "reason")
            if not isinstance(raw_job_action, str) or not raw_job_action.strip():
                self._send(400, {
                    "success": False,
                    "error": "job_action must be a non-empty string",
                    "terminal": True,
                    "retryable": False,
                }); return
            job_action = raw_job_action.strip()
            supported_actions = getattr(services_module.APP.async_jobs, "ACTIONS", None)
            normalized_job_action = job_action.lower().replace("-", "_")
            if isinstance(supported_actions, (set, frozenset)) and normalized_job_action not in supported_actions:
                self._send(400, {
                    "success": False,
                    "error": "unsupported async task action",
                    "terminal": True,
                    "retryable": False,
                }); return
            job_payload = dict(payload)
            response = services_module.APP.async_jobs.submit(job_action, job_payload)
            status_code = services_module._async_job_http_status(response)
            if status_code != 200 and isinstance(response, dict):
                response = {**response, "status_code": status_code}
            self._send(status_code, response); return
        if action in {"status", "wait", "result", "cancel"}:
            raw_job_id = payload.get("job_id")
            if not isinstance(raw_job_id, str) or not raw_job_id.strip():
                self._send(400, {
                    "success": False,
                    "error": "job_id must be a non-empty string",
                    "terminal": True,
                    "retryable": False,
                }); return
            job_id = raw_job_id.strip()

        def send_async_job_response(response: Any) -> None:
            status_code = services_module._async_job_http_status(response)
            if status_code != 200 and isinstance(response, dict):
                response = {**response, "status_code": status_code}
            self._send(status_code, response)

        if action == "status":
            send_async_job_response(services_module.APP.async_jobs.status(job_id)); return
        if action == "wait":
            raw_timeout = payload.get("timeout_seconds", 90)
            if isinstance(raw_timeout, bool) or not isinstance(raw_timeout, (int, float, str)):
                self._send(400, {
                    "success": False,
                    "error": "timeout_seconds must be a finite number",
                    "terminal": True,
                    "retryable": False,
                }); return
            try:
                timeout_seconds = float(raw_timeout)
            except (OverflowError, TypeError, ValueError):
                self._send(400, {
                    "success": False,
                    "error": "timeout_seconds must be a finite number",
                    "terminal": True,
                    "retryable": False,
                }); return
            if not services_module.math.isfinite(timeout_seconds):
                self._send(400, {
                    "success": False,
                    "error": "timeout_seconds must be a finite number",
                    "terminal": True,
                    "retryable": False,
                }); return
            send_async_job_response(services_module.APP.async_jobs.wait(job_id, timeout_seconds)); return
        if action == "result":
            diagnostic_result = getattr(services_module.APP.async_jobs, "diagnostic_result", None)
            if (
                not services_module.detailed_diagnostics_enabled(getattr(services_module.APP, "config", {}), store=getattr(services_module.APP, "debug_traces", None))
                and callable(diagnostic_result)
                and diagnostic_result(job_id=str(payload.get("job_id", ""))) is True
            ):
                self._send(409, services_module.diagnostics_disabled_response())
                return
            send_async_job_response(services_module.APP.async_jobs.result(job_id)); return
        if action == "cancel":
            send_async_job_response(services_module.APP.async_jobs.cancel(job_id)); return
        self._send(400, {"success": False, "error": "unknown async job action", "terminal": True, "retryable": False}); return

    def _handle_post_db_query(self, payload: Any) -> None:
        db_name = str(payload.get("db", "agent_state"))
        sql_q = str(payload.get("query", "SELECT name FROM sqlite_master WHERE type='table'"))
        self._send(200, self._handle_db_query(db_name, sql_q))

    def _handle_post_telemetry_timeline(self, payload: Any) -> None:
        limit = payload.get("limit", 100) if isinstance(payload, dict) else 100
        before_id = payload.get("before_id") if isinstance(payload, dict) else None
        try:
            page = services_module.APP.telemetry.get_timeline_page(limit, before_id=before_id)
        except (TypeError, ValueError):
            raise
        except Exception as exc:
            logger = getattr(services_module.APP, "logger", None)
            if logger is not None:
                logger.warning("telemetry timeline page failed error_type=%s", type(exc).__name__)
            self._send(503, {
                "success": False,
                "error": {"code": "telemetry_page_unavailable", "message": "telemetry timeline is temporarily unavailable"},
                "status_code": 503,
                "retryable": True,
                "terminal": False,
            })
            return
        self._send(200, {"success": True, **page})

    def _handle_post_repository_analysis(
        self, payload: Any, *, route_ids: tuple[str, ...] = ()
    ) -> None:
        services_module.handle_post_repository_analysis(self, payload, route_ids, services_module.APP)

    def _async_delivery(self, path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]] | None:
        """Convert eligible long foreground work into an existing durable job when requested."""
        if services_module.APP is None:
            return None
        action_by_path = {
            "/api/delegate": "delegate", "/api/reason": "reason", "/api/review": "review",
            "/api/review/diff": "review_diff",
            "/api/second-opinion": "second_opinion", "/api/compress": "compress",
            "/api/route": "route", "/api/delegate/batch": "batch",
            "/api/rag/index": "rag_index",
        }
        job_action = action_by_path.get(path)
        if not job_action:
            return None
        if bool(payload.get("conversation", False)):
            if str(payload.get("delivery", "sync")).strip().lower() != "sync":
                return 400, {"success": False, "error": "conversations require delivery=sync", "terminal": True, "retryable": False}
            return None
        try:
            estimate = services_module.APP.telemetry.http_latency_estimate(path)
            default_delivery = "auto" if job_action == "rag_index" else "sync"
            delivery = str(payload.get("delivery", default_delivery))
            default_budget_ms = 30_000 if job_action == "rag_index" else 0
            budget_ms = float(payload.get("latency_budget_ms", default_budget_ms) or 0)
            samples = int(estimate.get("samples", 0) or 0)
            queue_age_ms = float(payload.get("queue_age_ms", estimate.get("queue_age_ms", 0)) or 0)
            max_queue_age_ms = float(
                payload.get(
                    "max_queue_age_ms",
                    getattr(services_module.APP, "config", {}).get("review", {}).get("max_queue_age_ms", 30_000),
                ) or 0
            )
            if (
                job_action == "review_diff"
                and delivery.strip().lower() == "auto"
                and max_queue_age_ms > 0
                and queue_age_ms > max_queue_age_ms
            ):
                decision = services_module.decide_delivery(
                    delivery,
                    latency_budget_ms=budget_ms,
                    observed_p95_ms=estimate.get("p95_duration_ms", 0),
                    samples=samples,
                    queue_age_ms=queue_age_ms,
                    max_queue_age_ms=max_queue_age_ms,
                )
            elif job_action == "rag_index" and delivery.strip().lower() == "auto" and budget_ms > 0 and samples < 10:
                decision = {"mode": "async", "reason": "cold_start_rag_index"}
            elif job_action == "review_diff" and delivery.strip().lower() == "auto" and budget_ms > 0 and samples < 5:
                # Cold-start long work has no trustworthy p95 yet. Keep RAG
                # indexing and large-diff review off the synchronous request.
                decision = {"mode": "async", "reason": "cold_start_review_diff"}
            else:
                decision = services_module.decide_delivery(
                    delivery, latency_budget_ms=budget_ms,
                    observed_p95_ms=estimate.get("p95_duration_ms", 0), samples=estimate.get("samples", 0),
                    queue_age_ms=queue_age_ms,
                    max_queue_age_ms=max_queue_age_ms,
                )
        except (TypeError, ValueError) as exc:
            return 400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}
        if decision["mode"] == "bypass":
            return 503, {
                "success": False,
                "terminal": True,
                "retryable": False,
                "error": "review queue age exceeded delivery budget",
                "delivery": decision,
                "next_action": "retry_with_bounded_sync_or_inspect_existing_job",
            }
        if decision["mode"] != "async":
            return None
        job_payload = dict(payload)
        job_payload.pop("delivery", None); job_payload.pop("latency_budget_ms", None)
        if job_action == "reason":
            job_payload["task"] = str(job_payload.get("problem", job_payload.get("task", "")))
        elif job_action == "review":
            job_payload["task"] = str(job_payload.get("instructions", job_payload.get("task", "Report actionable defects only.")))
            job_payload["context"] = str(job_payload.get("code", job_payload.get("context", "")))
        elif job_action == "second_opinion":
            job_payload["task"] = str(job_payload.get("question", job_payload.get("task", "")))
        elif job_action == "compress":
            job_payload["task"] = str(job_payload.get("instruction", job_payload.get("task", "Compress while preserving facts.")))
            job_payload["context"] = str(job_payload.get("text", job_payload.get("context", "")))
        elif job_action == "route":
            job_payload["task"] = str(job_payload.get("query", job_payload.get("task", "")))
            job_payload["context"] = str(job_payload.get("text", job_payload.get("context", "")))
        elif job_action == "review_diff":
            job_payload["_async_job"] = True
        result = services_module.APP.async_jobs.submit(job_action, job_payload)
        status_code = services_module._async_job_http_status(result)
        if status_code != 200 and isinstance(result, dict):
            result = {**result, "status_code": status_code}
        if isinstance(result, dict):
            result["delivery"] = decision
        trace_store = getattr(services_module.APP, "debug_traces", None)
        api_trace_id = str(getattr(self, "_debug_trace_id", "") or "")
        if trace_store is not None and api_trace_id and isinstance(result, dict):
            if result.get("job_id"):
                trace_store.link(api_trace_id, async_job_id=str(result["job_id"]))
            trace_store.event(api_trace_id, "async_job_submitted", {"job_id": result.get("job_id", ""), "trace_id": result.get("trace_id", ""), "delivery": decision})
        return status_code, result

    def _send_database_locked(self) -> None:
        mutation = str(getattr(self, "command", "GET")).upper() not in {"GET", "HEAD", "OPTIONS"}
        response = {
            "success": False,
            "degraded": True,
            "error": "database_locked",
            "error_code": "database_locked",
            "status_code": 503,
            "terminal": mutation,
            "retryable": not mutation,
            "outcome_unknown": mutation,
        }
        self._send(503, response)

    def _send(self, status: int, data: Any, *, headers: Mapping[str, str] | None = None) -> None:
        response_path = services_module.urlparse(str(getattr(self, "path", ""))).path
        if (
            isinstance(status, int)
            and not isinstance(status, bool)
            and 200 <= status < 300
            and isinstance(data, dict)
            and data.get("success") is False
            and not (response_path == "/api/search" and services_module.search_execution_stopped(data))
        ):
            status, data = services_module._api_result_http_response(data)
        execution_started = getattr(self, "_handler_execution_started", None)
        operation = str(getattr(self, "_admin_operation", ""))
        if operation:
            audit_recorded = self._audit_admin_action(status, data)
            if not audit_recorded and isinstance(data, dict):
                data = dict(data)
                data["audit_accepted"] = False
                if 200 <= int(status) < 300:
                    data.setdefault("warning", "operation may have completed but audit event was not accepted for queuing")
        if getattr(self, "_admin_action", ""):
            audit_accepted = self._audit_admin_result(status)
            mutation = str(getattr(self, "command", "GET")).upper() not in {"GET", "HEAD", "OPTIONS"}
            if mutation and not audit_accepted and 200 <= status < 400 and isinstance(data, dict):
                status = 503
                data = {**data, "success": False, "error": "admin result audit unavailable; operation may have completed",
                        "outcome_unknown": True, "terminal": True, "retryable": False}
        if status >= 400:
            data = services_module.normalize_transport_error(status, data)
        if (
            status == 413
            and isinstance(data, dict)
            and data.get("error") == "checkpoint_response_budget_too_small"
        ):
            data = {**data, "error_code": "response_budget_too_small"}
        request_headers = getattr(self, "headers", None)
        response_request_id = request_headers.get("X-LocalAI-Request-ID", "") if hasattr(request_headers, "get") else ""
        if (
            isinstance(data, dict)
            and "request_id" not in data
            and isinstance(response_request_id, str)
            and 1 <= len(response_request_id) <= 128
            and response_request_id.isascii()
            and all(0x21 <= ord(char) <= 0x7E for char in response_request_id)
        ):
            data = {**data, "request_id": response_request_id}
        request_id = getattr(self, "_journal_request_id", None)
        if request_id and isinstance(data, dict):
            data = dict(data)
            data.setdefault("request_id", request_id)
        if request_id and services_module.APP is not None and not getattr(self, "_journal_finished", False):
            try:
                success = services_module._journal_outcome_success(status, data)
                detail = "" if success else str(data.get("error", "request failed")) if isinstance(data, dict) else "request failed"
                services_module.APP.recovery.finish(request_id, success, detail, status_code=status, response=data)
                self._journal_finished = True
            except Exception:
                pass
        serialization_started = services_module.time.perf_counter()
        exec_ms = (
            max(0.0, (serialization_started - execution_started) * 1000.0)
            if isinstance(execution_started, (int, float))
            else None
        )
        # Keep the canonical result for the journal, local trace and aggregate
        # telemetry. Only the wire projection drops internal observations.
        detail_enabled = services_module.detailed_diagnostics_enabled(
            getattr(services_module.APP, "config", {}), store=getattr(services_module.APP, "debug_traces", None),
        )
        aggregate_report = response_path in {"/api/metrics", "/api/telemetry/report"}
        wire_data = (
            services_module.project_status_response(data, enabled=detail_enabled)
            if response_path in {"/api/status", "/api/live/status"}
            else services_module.project_pubsub_poll_response(data, enabled=detail_enabled) if response_path == "/api/coord/pubsub_poll"
            else services_module.project_wait_event_response(data, enabled=detail_enabled) if response_path == "/api/coord/wait_for_event"
            else services_module.project_aggregate_response(data, enabled=detail_enabled) if aggregate_report
            else services_module.project_agent_response(data, enabled=detail_enabled)
        )
        if isinstance(wire_data, dict) and "returned_tokens" in (wire_data.get("response_budget") or {}):
            wire_data = services_module._reconcile_existing_budget(wire_data) or wire_data
        body = services_module._json_bytes(wire_data)
        if (
            response_path in {"/api/search", "/api/repo/code-index"}
            and int(status) < 400
            and len(body) > services_module.MAX_HTTP_PAGE_RESPONSE_BYTES
            and isinstance(data, dict)
        ):
            page_key = "results" if response_path == "/api/search" else "symbols"
            data = {
                "success": False,
                "status_code": 413,
                "terminal": True,
                "retryable": False,
                "error": "requested search page exceeds the 4 MiB HTTP response limit; reduce limit or snippet size",
                "root": data.get("root"),
                "offset": data.get("offset", 0),
                "limit": data.get("limit", 24),
                "total_matches": data.get("total_matches", 0),
                "has_more": data.get("has_more", False),
                page_key: [],
            }
            status = 413
            body = services_module._json_bytes(data)
        serialization_ms = max(0.0, (services_module.time.perf_counter() - serialization_started) * 1000.0)
        self._finish_debug_trace(status, data)
        if services_module.APP is not None and not getattr(self, "_telemetry_finished", False):
            try:
                path = str(getattr(self, "_request_path", services_module.urlparse(self.path).path))
                excluded = set(services_module.APP.config.get("observability", {}).get("exclude_http_paths", []))
                if path not in services_module.MONITOR_PATHS and not path.startswith("/api/debug-traces/") and path not in excluded:
                    elapsed_ms = max(0.0, (services_module.time.perf_counter() - float(getattr(self, "_request_started", services_module.time.perf_counter()))) * 1000)
                    telemetry_data = dict(data) if isinstance(data, dict) else data
                    reliability_success, outcome_error_type, record_operational_error = services_module._telemetry_http_outcome(status, telemetry_data, path)
                    err = str(data.get("error", "")) if isinstance(data, dict) else ""
                    evidence = data.get("evidence", []) if isinstance(data, dict) else []
                    canonical = data.get("canonical", {}) if isinstance(data, dict) and isinstance(data.get("canonical"), dict) else {}
                    canonical_route = canonical.get("route", {}) if isinstance(canonical.get("route"), dict) else {}
                    pipeline = data.get("pipeline", {}) if isinstance(data, dict) and isinstance(data.get("pipeline"), dict) else {}
                    repo_context = data.get("repo_context", {}) if isinstance(data, dict) and isinstance(data.get("repo_context"), dict) else {}
                    repo_evidence = repo_context.get("evidence", []) if isinstance(repo_context.get("evidence"), list) else []
                    stages = pipeline.get("stages", []) if isinstance(pipeline.get("stages"), list) else []
                    phase_latency = services_module._response_phase_latency(data)
                    req_root = getattr(self, "_request_root", "") or (data.get("root") if isinstance(data, dict) else "")
                    services_module.APP.telemetry.record_http(
                        agent=self._agent(),
                        request_id=str(getattr(self, "_trace_request_id", "")),
                        trace_id=str(getattr(self, "_trace_id", "")),
                        action=path,
                        duration_ms=elapsed_ms,
                        success=reliability_success,
                        status_code=status,
                        response_bytes=len(body),
                        model=str(data.get("model", "")) if isinstance(data, dict) else "",
                        cache_hit=bool(data.get("cache_hit", False)) if isinstance(data, dict) else False,
                        preprocessed_hit=bool(data.get("preprocessed_hit", False)) if isinstance(data, dict) else False,
                        cache_layer=str(data.get("cache_layer", "")) if isinstance(data, dict) else "",
                        fallback_used=bool(data.get("fallback_used", False)) if isinstance(data, dict) else False,
                        degraded=bool(data.get("stale_fallback", False) or data.get("degraded", False)) if isinstance(data, dict) else False,
                        route=(">".join(str(x) for x in stages) if stages else str(data.get("strategy", data.get("route", ""))))[:120] if isinstance(data, dict) else "",
                        task_type=str(canonical_route.get("task_type", ""))[:80],
                        complexity=str(canonical_route.get("complexity", ""))[:40],
                        evidence_count=(len(repo_evidence) if repo_evidence else (len(evidence) if isinstance(evidence, list) else 0)),
                        error_type=outcome_error_type,
                        queue_wait_ms=phase_latency.get("queue_wait_ms"),
                        service_ms=phase_latency.get("service_ms"),
                        db_wait_ms=phase_latency.get("db_wait_ms"),
                        exec_ms=exec_ms,
                        serialization_ms=serialization_ms,
                        root=str(req_root or ""),
                    )
                    request_evaluation = getattr(self, "_request_evaluation", None)
                    if reliability_success and request_evaluation is not None:
                        services_module.APP.telemetry.record_request_evaluation(request_evaluation, duration_ms=elapsed_ms)
                    if record_operational_error and err:
                        error_code = "application_error" if outcome_error_type == "application_error" else "http_request_failed"
                        services_module.APP.telemetry.record_error("http", path, err, request_id=str(getattr(self, "_trace_request_id", "")), agent=self._agent(), error_type_override=outcome_error_type, error_code_override=error_code, retryable=status in {429, 500, 502, 503, 504})
                    if services_module.APP is not None and getattr(services_module.APP, "endpoint_stats", None) is not None:
                        try:
                            services_module.APP.endpoint_stats.record_call(
                                item_type="endpoint",
                                item_name=path,
                                duration_ms=elapsed_ms,
                                success=reliability_success,
                                root=str(req_root or ""),
                            )
                        except Exception:
                            pass
                self._telemetry_finished = True
            except Exception:
                pass
        try:
            if status == 200 and str(getattr(self, "command", "GET")).upper() == "GET":
                etag = f'"{services_module.hashlib.md5(body).hexdigest()}"'
                req_headers = getattr(self, "headers", None)
                if_none_match = req_headers.get("If-None-Match") if hasattr(req_headers, "get") else None
                if if_none_match and if_none_match.strip() == etag:
                    self.send_response(304)
                    self.send_header("ETag", etag)
                    self.send_header("Connection", "close")
                    self._common_headers()
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(status)
                self.send_header("ETag", etag)
            else:
                self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Connection", "close")
            self._common_headers()
            for name, value in (headers or {}).items():
                self.send_header(str(name), str(value))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except OSError as exc:
            if not services_module._is_client_disconnect(exc):
                raise
        finally:
            self.close_connection = True
            if not getattr(self, "_debug_trace_finished", False):
                self._finish_debug_trace(status, data)
            self._close_trace_context()

    def _claim_recovery(self, path: str, payload: Any) -> bool:
        if services_module.APP is None:
            return True
        recovery = getattr(services_module.APP, "recovery", None)
        if recovery is None or not callable(getattr(recovery, "begin", None)):
            return True
        request_id = str(getattr(self, "_trace_request_id", ""))
        self._journal_request_id = request_id
        self._journal_finished = False
        try:
            claim = recovery.begin(
                request_id,
                action=path,
                payload=payload,
            )
        except Exception as exc:
            self._journal_finished = True
            self._send(503, services_module._recovery_claim_failure_response(recovery, exc))
            return False

        if not isinstance(claim, services_module.Mapping):
            self._journal_finished = True
            self._send(503, services_module._recovery_claim_failure_response(recovery, invalid_claim=True))
            return False
        if claim.get("claimed"):
            return True

        self._journal_finished = True
        state = str(claim.get("state", ""))
        if state == "conflict":
            self._send(409, {"success": False, "error": claim.get("error", "request id conflict"), "terminal": True})
            return False
        if state in {"done", "failed"} and claim.get("response") is not None:
            status = int(claim.get("status_code") or (200 if state == "done" else 500))
            self._send(status, claim["response"])
            return False
        if state == "running":
            app_cfg = getattr(services_module.APP, "config", None) if services_module.APP is not None else None
            singleflight_timeout = (
                app_cfg.get("resilience", {}).get("singleflight_wait_timeout_seconds", 1.0)
                if isinstance(app_cfg, dict) else 1.0
            )
            wait_seconds = min(
                2.0,
                max(0.05, float(singleflight_timeout)),
            )
            try:
                replay = services_module.APP.recovery.wait_for(
                    request_id,
                    action=path,
                    timeout_seconds=wait_seconds,
                    payload_fingerprint=services_module.APP.recovery.fingerprint_payload(payload),
                )
            except Exception:
                self._send(409, {
                    "success": False,
                    "error": "request outcome is unknown; mutation was not replayed",
                    "status_code": 409,
                    "terminal": True,
                    "retryable": False,
                    "outcome_unknown": True,
                    "request_id": request_id,
                })
                return False
            if replay and replay.get("state") in {"done", "failed"} and replay.get("response") is not None:
                status = int(replay.get("status_code") or (200 if replay.get("state") == "done" else 500))
                self._send(status, replay["response"])
                return False
            if replay and replay.get("outcome_unknown"):
                self._send(409, {
                    "success": False,
                    "error": "request outcome is unknown; mutation was not replayed",
                    "terminal": True,
                    "retryable": False,
                    "outcome_unknown": True,
                })
                return False
            self._send(409, {
                "success": False,
                "error": "request with this id is already running",
                "retryable": True,
                "in_progress": True,
                "retry_after_seconds": 1,
                "waited_seconds": wait_seconds,
            })
            return False
        if claim.get("outcome_unknown") or state == "abandoned":
            self._send(409, {
                "success": False,
                "error": "request outcome is unknown; mutation was not replayed",
                "terminal": True,
                "retryable": False,
                "outcome_unknown": True,
            })
            return False
        self._send(409, {"success": False, "error": "request journal returned an invalid state", "terminal": True})
        return False

    def _handle_post_artifact_get(self, payload: dict[str, Any]) -> None:
        allowed_fields = {"artifact_id", "offset", "max_chars", "section", "binary", "slices"}
        if not isinstance(payload, dict) or set(payload) - allowed_fields:
            self._send(400, {"success": False, "error": "artifact request contains unsupported fields", "terminal": True, "retryable": False})
            return
        artifact_id = payload.get("artifact_id", "")
        offset = payload.get("offset", 0)
        max_chars = payload.get("max_chars", 6000)
        section = payload.get("section", "")
        binary = payload.get("binary", False)
        if not isinstance(artifact_id, str) or not artifact_id:
            self._send(400, {"success": False, "error": "artifact_id must be a non-empty string", "terminal": True, "retryable": False})
            return
        if not services_module.detailed_diagnostics_enabled(getattr(services_module.APP, "config", {}), store=getattr(services_module.APP, "debug_traces", None)):
            kind_reader = getattr(services_module.APP.artifacts, "kind", None)
            kind = kind_reader(artifact_id) if callable(kind_reader) else None
            diagnostic_result = getattr(getattr(services_module.APP, "async_jobs", None), "diagnostic_result", None)
            retained_async_detail = kind == "async-job" and (
                not callable(diagnostic_result) or diagnostic_result(artifact_id=artifact_id) is not False
            )
            if kind == "diagnostic-async-job" or retained_async_detail:
                self._send(409, services_module.diagnostics_disabled_response())
                return
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            self._send(400, {"success": False, "error": "offset must be a non-negative integer", "terminal": True, "retryable": False})
            return
        if isinstance(max_chars, bool) or not isinstance(max_chars, int) or not 1 <= max_chars <= 50_000:
            self._send(400, {"success": False, "error": "max_chars must be between 1 and 50000", "terminal": True, "retryable": False})
            return
        if not isinstance(section, str) or len(section) > 512:
            self._send(400, {"success": False, "error": "section must be a string of at most 512 characters", "terminal": True, "retryable": False})
            return
        if not isinstance(binary, bool):
            self._send(400, {"success": False, "error": "binary must be a boolean", "terminal": True, "retryable": False})
            return
        if "slices" in payload and not isinstance(payload["slices"], list):
            self._send(400, {"success": False, "error": "slices must be an array", "terminal": True, "retryable": False})
            return
        slices = payload.get("slices")
        if slices is not None:
            if binary or set(payload) - {"artifact_id", "slices", "binary"}:
                self._send(400, {"success": False, "error": "multi-slice retrieval accepts only artifact_id, slices, and binary=false", "terminal": True, "retryable": False})
                return
            if not 1 <= len(slices) <= 16:
                self._send(400, {"success": False, "error": "slices must contain 1 to 16 ranges", "terminal": True, "retryable": False})
                return
            requested = 0
            for item in slices:
                if not isinstance(item, dict) or set(item) != {"offset", "max_chars"}:
                    self._send(400, {"success": False, "error": "each slice must contain only offset and max_chars", "terminal": True, "retryable": False})
                    return
                item_offset, item_max = item["offset"], item["max_chars"]
                if isinstance(item_offset, bool) or not isinstance(item_offset, int) or item_offset < 0:
                    self._send(400, {"success": False, "error": "slice offset must be a non-negative integer", "terminal": True, "retryable": False})
                    return
                if isinstance(item_max, bool) or not isinstance(item_max, int) or not 1 <= item_max <= 50_000:
                    self._send(400, {"success": False, "error": "slice max_chars must be between 1 and 50000", "terminal": True, "retryable": False})
                    return
                requested += item_max
                if requested > 50_000:
                    self._send(400, {"success": False, "error": "combined slice max_chars cannot exceed 50000", "terminal": True, "retryable": False})
                    return
            self._send(200, services_module.APP.artifacts.get_slices(artifact_id, slices=slices))
            return
        if binary:
            if section:
                self._send(400, {"success": False, "error": "section is not valid for binary retrieval", "terminal": True, "retryable": False})
                return
            self._send(200, services_module.APP.artifacts.get_binary(artifact_id))
            return
        self._send(200, services_module.APP.artifacts.get(
            artifact_id,
            offset=offset,
            max_chars=max_chars,
            section=section,
        ))

    def _handle_post_artifact_list(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict) or set(payload) - {"limit"}:
            self._send(400, {"success": False, "error": "artifact list accepts only limit", "terminal": True, "retryable": False})
            return
        limit = payload.get("limit", 20)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            self._send(400, {"success": False, "error": "limit must be a positive integer", "terminal": True, "retryable": False})
            return
        self._send(200, {"success": True, "artifacts": services_module.APP.artifacts.list(limit=limit)})

    def _handle_post_lease_claim(self, payload: dict[str, Any]) -> None:
        allowed_fields = {"owner", "root", "paths", "ttl_seconds", "purpose", "coordination_id"}
        if not isinstance(payload, dict) or set(payload) - allowed_fields:
            self._send(400, {"success": False, "error": "lease claim contains unsupported fields", "terminal": True, "retryable": False})
            return
        root = payload.get("root")
        owner = payload.get("owner")
        paths = payload.get("paths", [])
        ttl_seconds = payload.get("ttl_seconds", 900)
        purpose = payload.get("purpose", "agent edit")
        if not isinstance(root, str) or not root.strip() or "\x00" in root:
            self._send(400, {"success": False, "error": "root must be a non-empty string", "terminal": True, "retryable": False})
            return
        if not isinstance(paths, list) or any(not isinstance(path, str) or not path.strip() or "\x00" in path for path in paths):
            self._send(400, {"success": False, "error": "paths must be an array of non-empty strings", "terminal": True, "retryable": False})
            return
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or ttl_seconds < 1:
            self._send(400, {"success": False, "error": "ttl_seconds must be a positive integer", "terminal": True, "retryable": False})
            return
        if not isinstance(purpose, str) or "\x00" in purpose:
            self._send(400, {"success": False, "error": "purpose must be a string", "terminal": True, "retryable": False})
            return
        if not isinstance(owner, str) or not owner or owner != owner.strip() or "\x00" in owner:
            self._send(400, {"success": False, "error": "owner must identify the actual writer", "terminal": True, "retryable": False})
            return
        root = self._bind_root(root)
        if root is None:
            return
        coordination_id = services_module._lease_coordination_id(root)
        if "coordination_id" in payload and payload["coordination_id"] != coordination_id:
            self._send(400, {"success": False, "error": "coordination_id conflicts with repository", "terminal": True, "retryable": False})
            return
        result = services_module.APP.leases.claim_batch(
            owner=owner, root=root, paths=paths, ttl_seconds=ttl_seconds, purpose=purpose, coordination_id=coordination_id,
        )
        status = 200
        if not isinstance(result, dict) or result.get("success") is not True:
            status = 409 if isinstance(result, dict) and (
                result.get("deadlock") is True or bool(result.get("conflicts"))
            ) else 400
            if isinstance(result, dict):
                result.setdefault("status_code", status)
        self._send(status, result)

    def _handle_post_lease_release(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict) or set(payload) != {"owner", "lease_id"}:
            self._send(400, {"success": False, "error": "lease release requires owner and lease_id", "terminal": True, "retryable": False})
            return
        lease_id = payload["lease_id"]
        if not isinstance(lease_id, str) or not lease_id.strip() or "\x00" in lease_id:
            self._send(400, {"success": False, "error": "lease_id must be a non-empty string", "terminal": True, "retryable": False})
            return
        owner = payload["owner"]
        if not isinstance(owner, str) or not owner or owner != owner.strip() or "\x00" in owner:
            self._send(400, {"success": False, "error": "owner must identify the actual writer", "terminal": True, "retryable": False})
            return
        self._send(200, services_module.APP.leases.release(owner=owner, lease_id=lease_id))

    def _handle_post_lease_renew(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict) or "owner" not in payload or set(payload) - {"owner", "lease_id", "ttl_seconds"}:
            self._send(400, {"success": False, "error": "lease renewal contains unsupported fields", "terminal": True, "retryable": False})
            return
        lease_id = payload.get("lease_id")
        ttl_seconds = payload.get("ttl_seconds", 900)
        if not isinstance(lease_id, str) or not lease_id.strip() or "\x00" in lease_id:
            self._send(400, {"success": False, "error": "lease_id must be a non-empty string", "terminal": True, "retryable": False})
            return
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or ttl_seconds < 1:
            self._send(400, {"success": False, "error": "ttl_seconds must be a positive integer", "terminal": True, "retryable": False})
            return
        owner = payload["owner"]
        if not isinstance(owner, str) or not owner or owner != owner.strip() or "\x00" in owner:
            self._send(400, {"success": False, "error": "owner must identify the actual writer", "terminal": True, "retryable": False})
            return
        self._send(200, services_module.APP.leases.renew(owner=owner, lease_id=lease_id, ttl_seconds=ttl_seconds))

    @staticmethod
    def _context_retrieval_mode(payload: Mapping[str, Any]) -> str | None:
        raw_mode = payload.get("mode", "adaptive")
        return raw_mode if isinstance(raw_mode, str) and raw_mode in {"adaptive", "full", "fast"} else None

    def _send_service_result(self, result: Any) -> None:
        status = result.get("status_code", 200) if isinstance(result, dict) else 200
        # Preserve every valid failure status, including root/path denial (403).
        # Never let bool, string or out-of-range payload values set an HTTP code.
        http_status = status if type(status) is int and 400 <= status <= 599 else 200
        self._send(http_status, result)


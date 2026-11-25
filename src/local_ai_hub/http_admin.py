from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping


@lru_cache(maxsize=1)
def _installed_hub_version() -> str | None:
    try:
        import importlib.metadata

        return importlib.metadata.version("local-ai-hub")
    except Exception:
        return None


class HTTPAdminMixin:
    def _handle_post_config_update(self, payload: dict[str, Any]) -> None:
        from . import http_server as services_module
        from .dashboard_contracts import dashboard_settings_patch

        app = services_module.APP
        action = str(payload.get("action", "update")).strip().lower()
        config_path = str(app.config.get("_config_path", ""))
        if not config_path:
            self._send(500, {"success": False, "error": "active config path unavailable"})
            return
        if action == "reset":
            target = services_module.save_runtime_overrides(config_path, {}, reset=True)
            self._send(200, {
                "success": True, "restart_required": True,
                "runtime_override_path": services_module._safe_config_file_label(target),
                "reset": True,
            })
            return
        requested = payload.get("settings", {})
        if not isinstance(requested, dict):
            self._send(400, {"success": False, "error": "settings must be an object"})
            return
        try:
            patch = dashboard_settings_patch(requested)
        except ValueError as exc:
            self._send(400, {"success": False, "error": str(exc)})
            return
        failure_stage = "validation"
        try:
            prospective = services_module.deep_merge(app.config, patch)
            services_module.validate_config(prospective)
            failure_stage = "persistence"
            target = services_module.save_runtime_overrides(config_path, patch)
        except (services_module.ConfigError, OSError, ValueError) as exc:
            logger = getattr(app, "logger", None)
            if logger is not None:
                logger.error(
                    "config update rejected stage=%s error_type=%s",
                    failure_stage,
                    type(exc).__name__,
                )
            failure = services_module._config_update_failure_payload(exc)
            failure["failure_stage"] = failure_stage
            self._send(400, failure)
            return
        live_trace_toggle = services_module._apply_live_debug_trace_toggle(app, requested)
        self._send(200, {
            "success": True,
            "restart_required": not live_trace_toggle,
            "applied_live": live_trace_toggle,
            "runtime_override_path": services_module._safe_config_file_label(target),
            "settings": requested,
        })

    def _handle_telemetry_post(self, path: str, payload: dict[str, Any]) -> bool:
        from . import http_server as services_module

        app = services_module.APP
        if path == "/api/telemetry/endpoint-stats/reset":
            store = getattr(app, "endpoint_stats", None)
            if store is None:
                self._send(200, {"success": True, "reset": False, "available": False})
                return True
            req_root = str(payload.get("root", "") or "")
            ok = store.reset(root=req_root)
            if payload.get("purge_telemetry", False) or req_root in ("", "all", "__all__"):
                t_store = getattr(app, "telemetry", None)
                if t_store is not None and hasattr(t_store, "reset"):
                    t_store.reset()
            self._send(200, {"success": ok, "reset": ok, "root": req_root})
            return True
        if path != "/api/telemetry/tool-accounting":
            return False
        # Exclude this internal reporter from workload telemetry and journal accepted request IDs.
        self._telemetry_finished = True
        if getattr(app, "recovery", None) is not None and not self._claim_recovery(path, payload):
            return True
        accepted = rejected = 0
        rejection_reasons: dict[str, int] = {}
        for event in payload.get("events", []):
            try:
                scoped_event = dict(event) if isinstance(event, dict) else event
                recorded = app.telemetry.record_tool_accounting(scoped_event)
                if recorded is False:
                    rejected += 1
                    tool = event.get("tool") if isinstance(event, dict) else None
                    reason = "self_accounting" if isinstance(tool, str) and tool[:160] == "local_ai_telemetry" else (
                        "telemetry_disabled" if getattr(app.telemetry, "enabled", True) is False else "queue_full"
                    )
                    rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
                    continue
                accepted += 1
                if (app is not None and getattr(app, "endpoint_stats", None) is not None
                        and isinstance(scoped_event.get("event_id"), str)
                        and 0 < len(scoped_event["event_id"]) <= 128
                        and type(scoped_event.get("success")) is bool):
                    try:
                        tool_name = str(scoped_event.get("tool", ""))
                        op_name = str(scoped_event.get("operation", scoped_event.get("action", "")))
                        mcp_name = f"{tool_name}:{op_name}" if op_name and op_name not in ("default", tool_name) else tool_name
                        app.endpoint_stats.record_call(
                            item_type="mcp", item_name=mcp_name,
                            duration_ms=float(scoped_event.get("duration_ms", 0.0) or 0.0),
                            success=bool(scoped_event.get("success", True)),
                            root=str(scoped_event.get("root", "") or ""),
                            event_id=scoped_event["event_id"],
                        )
                    except Exception:
                        pass
            except Exception as exc:
                rejected += 1
                reason = "invalid_event" if isinstance(exc, (TypeError, ValueError)) else "record_failed"
                rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
        self._send(200, {
            "success": True, "accepted": accepted, "rejected": rejected,
            "rejection_reasons": rejection_reasons,
        })
        return True

    def _handle_health_route(self, path: str) -> bool:
        from . import http_server as services_module
        if path == "/health":
            installed_version = _installed_hub_version()
            self._send(
                200,
                {
                    "success": True,
                    "hub_online": True,
                    "version": services_module.__version__,
                    "installed_version": installed_version,
                },
            )
            return True
        if path == "/ready":
            if services_module.APP is None and not self._loopback_client():
                self._send(403, {"success": False, "ready": False, "error": "readiness is loopback-only"})
                return True
            if services_module.APP is not None and not self._require_authorized("monitor"):
                return True
            app = services_module.APP
            stores_ready = app is not None and all(
                getattr(app, name, None) is not None
                for name in services_module.READINESS_COMPONENTS
            )
            ready = app is not None and not bool(getattr(app, "_closed", False)) and stores_ready
            reason = "ready" if ready else "app_initializing_or_closed"
            if app is not None and not bool(getattr(app, "_closed", False)) and not stores_ready:
                reason = "required_store_unavailable"
            self._send(
                200 if ready else 503,
                {
                    "success": ready,
                    "ready": ready,
                    "reason": reason,
                    "retryable": not ready,
                    "version": services_module.__version__,
                },
            )
            return True
        return False

    def _audit_admin_authorization(self, action: str, *, allowed: bool) -> bool:
        from . import http_server as services_module
        if services_module.APP is None:
            return False
        telemetry = getattr(services_module.APP, "telemetry", None)
        recorder = getattr(telemetry, "record_system", None)
        if not callable(recorder):
            return False
        try:
            request_path = services_module.urlparse(str(getattr(self, "path", ""))).path
            accepted = recorder(
                "admin.authorization",
                success=allowed,
                component="http_admin",
                operation=action,
                route=request_path,
                stage=action,
            )
            return accepted is not False
        except Exception:
            return False

    def _audit_admin_result(self, status: int) -> bool:
        from . import http_server as services_module
        action = str(getattr(self, "_admin_action", "") or "")
        if not action:
            return True
        if getattr(self, "_admin_result_audited", False):
            return bool(getattr(self, "_admin_result_audit_accepted", False))
        self._admin_result_audited = True
        self._admin_result_audit_accepted = False
        telemetry = getattr(services_module.APP, "telemetry", None) if services_module.APP is not None else None
        recorder = getattr(telemetry, "record_system", None)
        if not callable(recorder):
            return False
        try:
            request_path = services_module.urlparse(str(getattr(self, "path", ""))).path
            accepted = recorder(
                "admin.action.result",
                success=200 <= int(status) < 400,
                component="http_admin",
                operation=action,
                route=request_path,
                stage=action,
                status_code=int(status),
            )
            self._admin_result_audit_accepted = accepted is not False
        except Exception:
            # Audit transport failure is reported, never silently accepted.
            self._admin_result_audit_accepted = False
        return self._admin_result_audit_accepted

    def _authorize_admin_action(self, operation: str) -> bool:
        """Require a globally authenticated request and an exact action/method route."""
        from . import http_server as services_module
        rule = self._ADMIN_ACTIONS.get(str(operation))
        if rule is None or not getattr(self, "_authorization_succeeded", False):
            self._send(403 if rule is not None else 400, {"success": False, "error": "admin action not authorized"})
            return False
        methods, expected_path, expected_action = rule
        actual_path = services_module.urlparse(str(getattr(self, "path", ""))).path
        path_matches = actual_path == expected_path
        if expected_path.endswith("/"):
            path_matches = actual_path.startswith(expected_path) and actual_path.count("/") == expected_path.count("/")
        if str(getattr(self, "command", "")) not in methods:
            self._send(
                405,
                {"success": False, "status_code": 405, "error": "method not allowed for admin action"},
                headers={"Allow": ", ".join(sorted(methods))},
            )
            return False
        if not path_matches:
            self._send(403, {"success": False, "error": "admin action does not match route"})
            return False
        if expected_action is not None and str(getattr(self, "command", "")) == "POST":
            payload = getattr(self, "_admin_payload", {})
            default_action = "update" if operation == "config.update" else "list" if operation == "models.list" else ""
            action = str(payload.get("action", default_action)).strip().lower().replace("-", "_") if isinstance(payload, dict) else ""
            if action != expected_action:
                self._send(403, {"success": False, "error": "admin action does not match request"})
                return False
        self._admin_operation = str(operation)
        self._admin_audited = False
        return True

    def _audit_admin_action(self, status: int, data: Any = None) -> bool:
        """Record only fixed operation and outcome metadata; never request content."""
        from . import http_server as services_module
        if getattr(self, "_admin_audited", False):
            return True
        operation = str(getattr(self, "_admin_operation", ""))
        if not operation:
            return True
        if services_module.APP is None:
            return False
        try:
            elapsed_ms = max(0.0, (services_module.time.perf_counter() - float(getattr(self, "_request_started", services_module.time.perf_counter()))) * 1000)
            accepted = services_module.APP.telemetry.record_system(
                f"admin.{operation}",
                success=200 <= int(status) < 300,
                duration_ms=elapsed_ms,
                status_code=int(status),
            )
        except Exception:
            accepted = False
        if accepted is True:
            self._admin_audited = True
            return True
        logger = getattr(services_module.APP, "logger", None)
        if logger is not None:
            logger.error("admin audit event not accepted operation=%s", operation)
        return False

    def _handle_get_live(self, query: Mapping[str, list[str]]) -> None:
        from . import http_server as services_module
        after = int((query.get("after") or [0])[0])
        limit_param = query.get("limit")
        default_limit = 50 if after == 0 else 200
        limit = int((limit_param or [default_limit])[0])
        compact_param = (query.get("compact") or ["1"])[0].lower() in {"1", "true", "yes"}
        max_batch = int(services_module.APP.config.get("monitoring", {}).get("live_max_batch", 200))
        self._send(200, services_module.APP.telemetry.live(after, min(limit, max_batch), compact=compact_param))

    def _handle_get_live_status(self, query: Mapping[str, list[str]]) -> None:
        from . import http_server as services_module
        light = str((query.get("light") or ["0"])[0]).lower() in {"1", "true", "yes"}
        if not services_module.detailed_diagnostics_enabled(getattr(services_module.APP, "config", {}), store=getattr(services_module.APP, "debug_traces", None)):
            light = True
        scope = str((query.get("scope") or ["process"])[0])
        status = services_module.APP.realtime_status(light=light, scope=scope)
        if isinstance(self.server, services_module.LocalAIHTTPServer):
            status["http_concurrency"] = self.server.concurrency_stats()
        self._send(200, status)

    def _handle_api_status(self, path: str, query: Mapping[str, list[str]], detail_enabled: bool) -> None:
        from . import http_server as services_module
        detail = str((query.get("detail") or [""])[0]).strip().lower()
        if detail == "agent_state":
            # The dependency-backed branch reads durable projections.
            # Without an already-bound root it must stay capability-only;
            # global task IDs/counts are never a valid monitor projection.
            if not getattr(self, "_authorization_root", None):
                requested_root = (query.get("root") or [""])[0]
                if requested_root:
                    if not self._bind_repository_root_query(query):
                        return
            if getattr(self, "_authorization_root", None) and hasattr(services_module.APP, "_status_dependency_lock"):
                dependency_status: dict[str, dict[str, services_module.Any]] = {}
                deadline = services_module.time.monotonic() + services_module._STATUS_TOTAL_BUDGET_SECONDS

                def read_agent_detail(key: str, callback, fallback):
                    timeout = min(services_module._STATUS_DEPENDENCY_TIMEOUT_SECONDS, max(0.0, deadline - services_module.time.monotonic()))
                    value, healthy = services_module._status_dependency(
                        callback, fallback, key=f"detail.agent_state.{key}",
                        lock=services_module.APP._status_dependency_lock, inflight=services_module.APP._status_dependency_inflight,
                        slots=services_module.APP._status_dependency_slots, timeout_seconds=timeout,
                    )
                    dependency_status[key] = {"deadline_ms": max(0, int(timeout * 1000)), "degraded": not healthy, "status": "ok" if healthy else "degraded"}
                    return value

                scoped_root = str(getattr(self, "_authorization_root", "") or "")
                tasks = read_agent_detail("tasks", services_module.APP.agent_tasks.list_tasks, []) if getattr(services_module.APP, "agent_tasks", None) else []
                scoped_tasks = [
                    task for task in tasks
                    if self._task_matches_request(task, scoped_root)
                ]
                active_tasks = [getattr(t, "task_id", "") for t in scoped_tasks if getattr(t, "status", None) == services_module.TaskStatus.ACTIVE]
                incidents = read_agent_detail("incidents", services_module.APP.agent_incidents.list_incidents, []) if getattr(services_module.APP, "agent_incidents", None) else []
                repository_key = services_module._incident_scope_key("repository", scoped_root)
                scoped_incidents = [
                    incident for incident in incidents
                    if getattr(incident, "repository_key", "") == repository_key
                ]
                # Candidates lack repository provenance; do not project
                # the owner's global candidates into a repository view.
                scoped_candidates: list[services_module.Any] = []
                degraded = any(item["degraded"] for item in dependency_status.values())
                self._send(200, {
                    "success": not degraded,
                    "degraded": degraded,
                    "status": "degraded" if degraded else "ok",
                    "dependency_status": dependency_status,
                    "snapshot_cached": False,
                    "enabled": bool(getattr(services_module.APP, "agent_state", None) and services_module.APP.agent_state.enabled),
                    "active_tasks": active_tasks,
                    "tasks_count": len(scoped_tasks),
                    "incidents_count": len(scoped_incidents),
                    "candidates_count": len(scoped_candidates),
                }); return
            # Capability readiness only: global projection counts would
            # mix other repositories and require an unbounded scan.
            state = getattr(services_module.APP, "agent_state", None)
            enabled = bool(state is not None and state.enabled)
            initialized = bool(enabled and getattr(state, "_initialized", False))
            self._send(200, {
                "success": True,
                "enabled": enabled,
                "initialized": initialized,
                "status": "ok" if enabled else "disabled",
                "active_tasks": [],
                "tasks_count": 0,
                "incidents_count": 0,
                "candidates_count": 0,
            }); return
        scope = str((query.get("scope") or ["process"])[0])
        if not detail_enabled or detail in {"brief", "summary", "light"}:
            status = services_module.APP.realtime_status(light=True, scope=scope)
            status["detail_level"] = "summary"
        else:
            status = services_module.APP.status(scope=scope)
            status["detail_level"] = "full"
        if isinstance(self.server, services_module.LocalAIHTTPServer):
            status["http_concurrency"] = self.server.concurrency_stats()
        self._send(200, status); return


    def _handle_repair_priorities(self, path: str, query: Mapping[str, list[str]]) -> None:
        from . import http_server as services_module
        diagnostics_enabled = services_module.detailed_diagnostics_enabled(services_module.APP.config, store=services_module.APP.debug_traces)
        try:
            error_offset = int((query.get("error_offset") or [0])[0])
        except (TypeError, ValueError, OverflowError):
            self._send(400, {"success": False, "error": "error_offset must be an integer between 0 and 100000", "terminal": True, "retryable": False}); return
        if not 0 <= error_offset <= 100_000:
            self._send(400, {"success": False, "error": "error_offset must be an integer between 0 and 100000", "terminal": True, "retryable": False}); return
        status = services_module.project_status_response(services_module.APP.status(scope="process"), enabled=diagnostics_enabled)
        telemetry = services_module.project_aggregate_response(
            services_module.APP.telemetry.report(days=7, recent_errors=100, _error_offset=error_offset, scope="window"),
            enabled=diagnostics_enabled,
        )
        endpoint_stats = getattr(services_module.APP, "endpoint_stats", None)
        stats = endpoint_stats.get_stats(include_unused=True) if endpoint_stats is not None else {"success": False, "items": []}
        priorities: list[dict[str, services_module.Any]] = []
        def add_priority(priority: str, kind: str, name: str, evidence: dict[str, services_module.Any], action: str, score: int, confidence: str) -> None:
            priorities.append({"priority": priority, "priority_score": score, "confidence": confidence, "kind": kind, "name": name, "evidence": evidence, "action": action})

        if status.get("hub_online") is False:
            add_priority("P0", "hub", "runtime", {"hub_online": False}, "Restore the Hub process.", 100, "high")
        for name, component in (status.get("dependency_status") or {}).items():
            if isinstance(component, dict) and (component.get("degraded") or component.get("status") == "degraded"):
                add_priority("P1", "component", str(name), component, "Inspect component health and restore dependency.", 85, "high")
        if status.get("degraded") and not any(item["kind"] == "component" for item in priorities):
            add_priority("P1", "hub", "runtime", {"success": status.get("success"), "degraded": True}, "Inspect Hub runtime status and degraded dependencies.", 85, "high")
        for error in (telemetry.get("error_fingerprints") or []):
            if not isinstance(error, dict):
                continue
            count = max(0, int(error.get("count", 0) or 0))
            recovered = max(0, int(error.get("recovered_count", 0) or 0))
            unresolved = max(0, count - recovered)
            if not unresolved:
                continue
            critical = str(error.get("error_type", "")) in {"MemoryError", "SystemExit", "FatalError"}
            priority = "P1" if critical or unresolved >= 5 else ("P2" if unresolved >= 2 else "P3")
            evidence = {key: error.get(key) for key in ("fingerprint", "error_type", "component", "operation", "last_seen") if key in error}
            evidence.update({"occurrences": count, "unresolved_occurrences": unresolved, "recovered_occurrences": recovered})
            if diagnostics_enabled and error.get("safe_message"):
                evidence["safe_message"] = error["safe_message"]
            add_priority(priority, "error", str(error.get("component") or error.get("operation") or error.get("error_type") or "unknown"), evidence,
                         "Resolve this unresolved error group.", {"P1": 75, "P2": 50, "P3": 25}[priority] + min(24, unresolved * 3), "high" if unresolved >= 10 else "medium" if unresolved >= 3 else "low")
        route_stats = ((telemetry.get("http_tail_latency") or {}).get("by_action") or [])
        observed_routes = {str(item.get("action", "")) for item in route_stats if isinstance(item, dict) and item.get("action")}
        for item in route_stats:
            if not isinstance(item, dict) or item.get("action") == path:
                continue
            events = max(0, int(item.get("events", 0) or 0))
            failures = max(0, int(item.get("failures", 0) or 0))
            rate = float(item.get("failure_rate", failures / events if events else 0.0) or 0.0)
            confidence = "high" if events >= 20 else "medium" if events >= 5 else "low"
            route = str(item.get("action", "unknown"))
            if failures:
                priority = "P1" if (events >= 3 and rate >= 0.8) or (events >= 5 and rate >= 0.5) else ("P2" if events >= 5 and rate >= 0.1 else "P3")
                add_priority(priority, "endpoint_error_rate", route,
                             {key: item.get(key) for key in ("events", "failures", "failure_rate")},
                             "Investigate recent endpoint failures.", {"P1": 75, "P2": 50, "P3": 25}[priority] + min(24, int(rate * 20) + events // 10), confidence)
            p95 = item.get("p95_duration_ms")
            if events >= 10 and isinstance(p95, (int, float)) and p95 >= 2500:
                priority = "P1" if p95 >= 30000 else "P2" if p95 >= 10000 else "P3"
                add_priority(priority, "endpoint_latency", route,
                             {"events": events, "p95_duration_ms": p95},
                             "Investigate endpoint tail latency against its service objective.", {"P1": 75, "P2": 50, "P3": 25}[priority] + min(24, int(p95 // 2500)), confidence)
            queue_p95 = item.get("p95_queue_wait_ms")
            if events >= 5 and isinstance(queue_p95, (int, float)) and queue_p95 >= 500:
                priority = "P1" if queue_p95 >= 5000 else "P2" if queue_p95 >= 1000 else "P3"
                add_priority(priority, "endpoint_queue", route,
                             {"events": events, "p95_queue_wait_ms": queue_p95},
                             "Reduce time spent waiting in the request queue.", {"P1": 75, "P2": 50, "P3": 25}[priority] + min(24, int(queue_p95 // 500)), confidence)
        for hotspot in (telemetry.get("hotspots") or []):
            if isinstance(hotspot, dict):
                kind = str(hotspot.get("type", "quality"))
                priority = "P1" if kind in {"reliability", "observability"} else "P2"
                add_priority(priority, kind, str(hotspot.get("signal", "hotspot")), hotspot, "Investigate telemetry hotspot.", 80 if priority == "P1" else 55, "medium")
        quality = ((telemetry.get("evaluation") or {}).get("cohorts") or {}).get("hub_on", {})
        quality_rate = quality.get("quality_pass_rate")
        quality_samples = int(quality.get("quality_evaluated", 0) or 0)
        if quality_samples >= 10 and isinstance(quality_rate, (int, float)) and quality_rate < 0.8:
            priority = "P1" if quality_rate < 0.5 else "P2"
            add_priority(priority, "quality", "hub_on", {"evaluated": quality_samples, "pass_rate": quality_rate, "matched_tasks": (telemetry.get("evaluation") or {}).get("matched_tasks", 0), "endpoint_attribution": False}, "Investigate failed quality evaluations and improve the affected workflows.", 80 if priority == "P1" else 55, "high")
        priorities.sort(key=lambda item: (-item["priority_score"], item["kind"], item["name"]))
        telemetry_available = bool(telemetry) and telemetry.get("success", True) is not False and not telemetry.get("error") and telemetry.get("enabled", True) is True
        registered_routes = {str(item.get("name")) for item in (stats.get("items") or []) if isinstance(item, dict) and item.get("type") == "endpoint" and item.get("name") != path}
        unobserved_routes = sorted(registered_routes - observed_routes)
        error_page = telemetry.get("error_fingerprints_page") or {}
        complete = bool(status) and telemetry_available and bool(stats.get("success")) and diagnostics_enabled and error_page.get("next_offset") is None
        self._send(200, {
            "success": True, "generated_at": services_module.datetime.now(services_module.timezone.utc).isoformat(),
            "window": {"telemetry_days": 7, "endpoint_stats": "catalog_only; lifetime counts excluded from priority"},
            "complete": complete,
            "health": {"success": status.get("success"), "degraded": status.get("degraded"), "runtime_online": status.get("ollama_online"), "runtime_status": status.get("ollama_status"), "dependencies": status.get("dependency_status", {})},
            "telemetry_available": telemetry_available,
            "endpoint_stats_available": bool(stats.get("success")),
            "diagnostic_details_available": diagnostics_enabled,
            "coverage": {"observed_routes_7d": len(observed_routes), "registered_routes": len(registered_routes), "unobserved_routes": unobserved_routes[:100], "unobserved_route_count": len(unobserved_routes), "unobserved_truncated": len(unobserved_routes) > 100, "error_groups_total": error_page.get("total"), "error_groups_returned": len(telemetry.get("error_fingerprints") or []), "error_offset": error_offset, "next_error_offset": error_page.get("next_offset"), "error_groups_more": bool(error_page.get("next_offset") is not None) if diagnostics_enabled else None},
            "quality_evidence": {"available": diagnostics_enabled and quality_samples >= 10, "evaluated": quality_samples, "minimum_samples": 10, "endpoint_attribution": False, "reason": "diagnostics disabled" if not diagnostics_enabled else "quality and test evaluations are cohort-level, not endpoint-level" if quality_samples >= 10 else "fewer than 10 evaluation samples"},
            "priority_policy": {"endpoint_error_p1": "failure_rate >= 80% with >=3 samples, or >=50% with >=5 samples", "endpoint_error_p2": "failure_rate >=10% with >=5 samples", "latency_samples": 10, "latency_p3_p95_ms": 2500, "latency_p2_p95_ms": 10000, "latency_p1_p95_ms": 30000},
            "priorities": priorities,
        }); return



    def _handle_admin_get(self, path: str, query: Mapping[str, list[str]]) -> bool:
        from . import http_server as services_module

        app = services_module.APP
        if path == "/api/models/manage":
            self._send(200, self._handle_models_list())
        elif path == "/api/security_audit":
            root = (query.get("root") or ["."])[0]
            limit = int((query.get("limit") or [50])[0])
            if app.deterministic is not None:
                self._send(200, app.services.security_audit(root, limit))
            else:
                self._send(200, {"success": False, "error": "deterministic engine disabled"})
        elif path in {"/api/maintenance/optimize_db", "/api/maintenance/purge_cache", "/api/maintenance/resolve_errors"}:
            self._send(405, {"success": False, "error": "method not allowed"}, headers={"Allow": "POST"})
        elif path == "/api/config":
            self._send(200, {
                "success": True,
                "config": services_module._redact_config_secrets(app.config),
                "config_path": services_module._safe_config_file_label(app.config.get("_config_path", "")),
                "runtime_override_path": services_module._safe_config_file_label(app.config.get("_runtime_override_path", "")),
            })
        elif path == "/api/logs/tail":
            try:
                lines = max(1, min(int((query.get("lines") or query.get("limit") or [50])[0]), 1000))
                log_path = Path(app.config["server"]["state_dir"]) / "logs" / "hub.log"
                if not log_path.is_file():
                    self._send(200, {"success": True, "lines": []})
                else:
                    with log_path.open("rb") as fh:
                        fh.seek(0, 2)
                        size = fh.tell()
                        fh.seek(max(0, size - 512 * 1024))
                        text = fh.read(512 * 1024).decode("utf-8", errors="replace")
                    self._send(200, {"success": True, "lines": text.splitlines()[-lines:]})
            except (OSError, ValueError):
                self._send(400, {
                    "success": False,
                    "error": "log tail unavailable",
                    "error_code": "log_tail_unavailable",
                    "terminal": True,
                    "retryable": False,
                })
        elif path == "/api/doctor":
            self._send(200, app.services.run_doctor())
        elif path in {"/api/preprocess", "/api/preprocess/status"}:
            self._send(200, app.preprocessor.status((query.get("root") or [None])[0]))
        else:
            return False
        return True

    def _handle_models_list(self) -> dict[str, Any]:
        from . import http_server as services_module
        if services_module.APP is None:
            return {"success": False, "error": "Hub app not initialized", "models": []}
        ollama_url = services_module.APP.config.get("ollama", {}).get("url", "http://localhost:11434")
        try:
            req = services_module.urllib.request.Request(f"{ollama_url}/api/tags")
            with services_module.urllib.request.urlopen(req, timeout=3) as resp:
                tags_data = services_module.json.loads(resp.read().decode("utf-8"))
            models = tags_data.get("models", [])
            running: dict[str, services_module.Any] = {}
            try:
                req_ps = services_module.urllib.request.Request(f"{ollama_url}/api/ps")
                with services_module.urllib.request.urlopen(req_ps, timeout=2) as resp_ps:
                    ps_data = services_module.json.loads(resp_ps.read().decode("utf-8"))
                    running = {m.get("model"): m for m in ps_data.get("models", [])}
            except Exception:
                pass

            enriched = []
            for m in models:
                name = str(m.get("name", ""))
                is_running = name in running or any(name.startswith(k) for k in running)
                run_info = running.get(name, {})
                enriched.append({
                    "name": name,
                    "size_gb": round(m.get("size", 0) / (1024**3), 2),
                    "modified_at": m.get("modified_at", ""),
                    "running": is_running,
                    "vram_mb": round(run_info.get("size_vram", 0) / (1024**2), 1) if is_running else 0,
                })
            return {"success": True, "models": enriched, "count": len(enriched)}
        except Exception as exc:
            return {"success": False, "error": f"Ollama query failed: {exc}", "models": []}

    def _handle_models_action(self, action: str, model_name: str) -> dict[str, Any]:
        from . import http_server as services_module
        if not model_name:
            return {"success": False, "error": "model parameter required"}
        if services_module.APP is None:
            return {"success": False, "error": "Hub app not initialized"}
        ollama_url = services_module.APP.config.get("ollama", {}).get("url", "http://localhost:11434")
        try:
            if action == "delete":
                req = services_module.urllib.request.Request(f"{ollama_url}/api/delete", data=services_module.json_dumps({"name": model_name}).encode("utf-8"), headers={"Content-Type": "application/json"}, method="DELETE")
                with services_module.urllib.request.urlopen(req, timeout=5):
                    return {"success": True, "deleted": model_name}
            elif action == "pull":
                req = services_module.urllib.request.Request(f"{ollama_url}/api/pull", data=services_module.json_dumps({"name": model_name, "stream": False}).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
                timeout = max(0.001, min(float(services_module._MODEL_PULL_TIMEOUT_SECONDS), 600.0))
                deadline = services_module.time.monotonic() + timeout
                timed_out = services_module.threading.Event()
                response_holder: dict[str, services_module.Any] = {}

                def _expire_pull() -> None:
                    timed_out.set()
                    response = response_holder.get("response")
                    if response is not None:
                        try:
                            response.close()
                        except Exception:
                            pass

                timer = services_module.threading.Timer(timeout, _expire_pull)
                timer.daemon = True
                timer.start()
                try:
                    response = services_module.urllib.request.urlopen(req, timeout=max(0.001, deadline - services_module.time.monotonic()))
                    response_holder["response"] = response
                    remaining = deadline - services_module.time.monotonic()
                    if timed_out.is_set() or remaining <= 0:
                        return {"success": False, "degraded": True, "retryable": True, "error": "model pull time budget exceeded"}
                    sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
                    if sock is not None:
                        sock.settimeout(remaining)
                    body = response.read(max(1, min(int(services_module._MODEL_PULL_MAX_RESPONSE_BYTES), 4 * 1024 * 1024)) + 1)
                    if timed_out.is_set() or services_module.time.monotonic() >= deadline:
                        return {"success": False, "degraded": True, "retryable": True, "error": "model pull time budget exceeded"}
                    if len(body) > services_module._MODEL_PULL_MAX_RESPONSE_BYTES:
                        return {"success": False, "error": "model pull response exceeded byte limit"}
                    if body:
                        payload = services_module.json_loads(body)
                        if isinstance(payload, dict) and payload.get("error"):
                            return {"success": False, "error": str(payload["error"])}
                    return {"success": True, "pulled": model_name}
                finally:
                    timer.cancel()
                    response = response_holder.get("response")
                    if response is not None:
                        try:
                            response.close()
                        except Exception:
                            pass
            return {"success": False, "error": f"Unknown action: {action}"}
        except Exception as exc:
            timed_out_event = locals().get("timed_out")
            deadline = locals().get("deadline")
            pull_timed_out = action == "pull" and (
                bool(timed_out_event and timed_out_event.is_set())
                or (deadline is not None and services_module.time.monotonic() >= deadline)
            )
            if pull_timed_out:
                return {"success": False, "degraded": True, "retryable": True, "error": "model pull time budget exceeded"}
            return {"success": False, "error": str(exc)}



    def _handle_post_diagnostics_export(self, payload: dict[str, Any]) -> None:
        from . import http_server as services_module
        export = None
        response_started = False

        def export_cancelled() -> bool:
            try:
                ready, _, _ = services_module.select.select([self.connection], [], [], 0)
                return bool(ready and self.connection.recv(1, services_module.socket.MSG_PEEK) == b"")
            except (BlockingIOError, InterruptedError):
                return False
            except OSError:
                return True

        try:
            candidate_export = None
            if payload:
                if set(payload) != {"root", "laya_candidate_export"}:
                    raise services_module.RequestBodyError("diagnostics export accepts only root and laya_candidate_export")
                if type(payload["root"]) is not str or not payload["root"]:
                    raise services_module.RequestBodyError("candidate export root must be an absolute repository path")
                operation = payload["laya_candidate_export"]
                if type(operation) is not dict or set(operation) != {"snapshot_id"}:
                    raise services_module.RequestBodyError("laya_candidate_export requires exactly snapshot_id")
                candidate_export = payload
            export = services_module.APP.export_diagnostics(cancelled=export_cancelled, candidate_export=candidate_export)
            services_module.APP.logger.info(
                "diagnostic support archive exported",
                extra={
                    "diagnostics_export_bytes": export.size,
                    "diagnostics_export_files": export.manifest["included_files"],
                },
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self._common_headers()
            self.send_header("Cache-Control", "no-store")
            self.send_header("Pragma", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Local-AI-Export-Password", export.password)
            self.send_header("Content-Disposition", 'attachment; filename="local-ai-hub-support.zip"')
            self.send_header("Content-Length", str(export.size))
            self.end_headers()
            response_started = True
            with export.path.open("rb") as archive_stream:
                while True:
                    chunk = archive_stream.read(1024 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
            self.wfile.flush()
        except services_module.RequestBodyError as exc:
            if not response_started:
                self._send(exc.status, {
                    "success": False,
                    "error": str(exc),
                    "error_code": "diagnostics_export_request_invalid",
                    "terminal": True,
                    "retryable": False,
                })
        except ValueError as exc:
            if not response_started:
                self._send(400, {
                    "success": False,
                    "error": str(exc),
                    "error_code": "diagnostics_export_scope_invalid",
                    "terminal": True,
                    "retryable": False,
                })
        except Exception as exc:
            services_module.APP.logger.exception("diagnostic support archive export failed")
            if not services_module._is_client_disconnect(exc) and not response_started:
                self._send(500, {
                    "success": False,
                    "error": "diagnostics export unavailable",
                    "error_code": "diagnostics_export_unavailable",
                    "terminal": True,
                    "retryable": False,
                })
            elif services_module._is_client_disconnect(exc):
                self.close_connection = True
        finally:
            if export is not None:
                export.close()
        return

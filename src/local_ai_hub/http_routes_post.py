from __future__ import annotations

from typing import Any
from uuid import uuid4

from .http_server_proxy import services_module


def split_change_paths_from_payload(payload: Any) -> list[str] | None:
    if not isinstance(payload, dict):
        raise ValueError("split_changes request must be an object")
    retired_fields = sorted({"paths", "changed_files"}.intersection(payload))
    if retired_fields:
        raise ValueError(f"Unsupported split_changes field(s): {', '.join(retired_fields)}; use changed_paths")
    changed_paths = payload.get("changed_paths")
    if changed_paths is not None and (
        not isinstance(changed_paths, list)
        or any(not isinstance(path, str) or not path.strip() for path in changed_paths)
    ):
        raise ValueError("changed_paths must be a list of non-empty strings")
    return changed_paths


class HTTPPostRoutesMixin:
    def _handle_post_opencode_gateway(self, payload: Any) -> None:
        """Run OpenAI chat requests only through Hub policy and scheduler."""
        from .opencode_gateway import openai_sse, to_openai_completion, to_ollama_chat

        app = services_module.APP
        repository_root = None
        if isinstance(payload, dict) and "root" in payload:
            payload = dict(payload)
            root_payload = {"root": payload.pop("root")}
            if not self._bind_repository_root_payload(root_payload):
                return
            repository_root = root_payload["root"]
        configured = app.config.get("models", {}) if isinstance(app.config, dict) else {}
        role_keys = {"opencode", "general", "fast_code", "heavy_code", "reasoning", "background_code"}
        configured_models = {
            value.strip() for key, value in configured.items()
            if key in role_keys and isinstance(value, str) and value.strip()
        } if isinstance(configured, dict) else set()
        auto_model_route = isinstance(payload, dict) and payload.get("model") == "auto"
        if auto_model_route:
            default_model = configured.get("opencode") or configured.get("general")
            if not isinstance(default_model, str) or not default_model.strip():
                self._send(503, {"success": False, "error": "OpenCode auto model route is not configured", "terminal": True, "retryable": False})
                return
            payload = {**payload, "model": default_model.strip()}
        try:
            request, wants_stream = to_ollama_chat(payload, configured_models)
        except (TypeError, ValueError) as exc:
            self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False})
            return
        try:
            installed_models = set(str(value) for value in app.runtime.installed_models())
            if request["model"] not in installed_models:
                self._send(400, {"success": False, "error": "model is not installed locally", "terminal": True, "retryable": False})
                return
        except Exception:
            self._send(503, {"success": False, "error": "local model inventory unavailable", "terminal": True, "retryable": False})
            return
        try:
            result = app.services.proxy_request(
                "/api/chat", request, source="proxy:opencode",
                repository_root=repository_root,
                model_route_requested=auto_model_route,
            )
            if isinstance(result, dict) and result.get("error") and result.get("done") is not True:
                error = result.get("error")
                response = {
                    "success": False,
                    "error": error[:240] if isinstance(error, str) else "Hub inference failed",
                    "error_code": str(result.get("error_code", "hub_inference_error"))[:80],
                    "terminal": True,
                    "retryable": bool(result.get("retryable", False)),
                }
                admission = result.get("admission")
                if isinstance(admission, dict):
                    safe_fields = {"state", "reason", "retryable", "vram_available_bytes",
                                   "vram_incremental_required_bytes", "queue_wait_ms"}
                    response["admission"] = {key: admission[key] for key in safe_fields if key in admission}
                self._send(503, response)
                return
            completion = to_openai_completion(result, request_id=f"chatcmpl-{uuid4().hex}")
        except (TypeError, ValueError) as exc:
            self._send(502, {"success": False, "error": str(exc), "terminal": True, "retryable": False})
            return
        except Exception:
            self._send(502, {"success": False, "error": "Hub inference failed", "terminal": True, "retryable": False})
            return
        if wants_stream:
            stream_options = payload.get("stream_options", {}) if isinstance(payload, dict) else {}
            body = b"".join(openai_sse(completion, include_usage=stream_options.get("include_usage") is True))
            self._send(200, completion, raw_body=body, content_type="text/event-stream; charset=utf-8",
                       headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
        else:
            self._send(200, completion)

    def do_POST(self) -> None:
        path = services_module.urlparse(self.path).path
        post_route_ids = services_module.select_http_routes("POST", path)
        if not post_route_ids:
            # Rejected routes never accept a body. Waiting for one lets a peer
            # occupy a handler without reaching an authorized operation.
            self.close_connection = True
            self._send(404, {
                "success": False,
                "error": "route not found",
                "terminal": True,
                "retryable": False,
            })
            return
        self._handler_execution_started = services_module.time.perf_counter()
        if services_module.APP is None:
            self._send(503, {"success": False, "error": "hub starting up; please retry", "status_code": 503, "retryable": True})
            return
        if not self._require_authorized():
            return
        if path == "/api/updates":
            self._handle_desktop_updates(mutate=True)
            return
        early_mode_rejection = None
        if path != "/api/context/pack":
            early_mode_rejection = services_module._http_mode_gate_error("POST", path)
        if early_mode_rejection is not None and early_mode_rejection.get("mode") in {"maintenance", "preprocessing"}:
            status = 423 if early_mode_rejection.get("error_code") == "operational_mode_blocked" else 503
            self._send(status, early_mode_rejection)
            if services_module.os.name == "nt":
                self._close_rejected_mode_post()
            return
        self._begin_trace(path)
        if getattr(services_module.APP, "recovery", None) is not None:
            try:
                request_id = services_module.RecoveryJournal.validate_request_id(self._ensure_trace_request_id())
            except (TypeError, ValueError) as exc:
                self._journal_finished = True
                self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False})
                return
            self._trace_request_id = request_id
        if path == "/api/admin/mode":
            self._handle_admin_mode_post(path)
            return
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if path == "/api/bundle/import":
            mode_rejection = services_module._http_mode_gate_error("POST", path)
            if mode_rejection is not None:
                self._send(503, mode_rejection)
                return
            if content_type not in {"application/zip", "application/octet-stream"}:
                self._send(415, {"success": False, "error": "bundle import requires raw ZIP content"}); return
            try:
                limit = max(1024, int(services_module.APP.config.get("bundles", {}).get("max_bundle_bytes", 128 * 1024 * 1024)))
                raw_bundle = self._read_body(limit=limit)
                query = services_module.parse_qs(services_module.urlparse(self.path).query)
                target_root = (query.get("target_root") or [None])[0]
                if not self._claim_recovery(path, {
                    "bundle_sha256": services_module.hashlib.sha256(raw_bundle).hexdigest(),
                    "target_root": target_root,
                }):
                    return
                self._send(200, services_module.APP.import_bundle(raw_bundle, target_root)); return
            except services_module.RequestBodyError as exc:
                self._send(exc.status, {"success": False, "error": str(exc)}); return
            except Exception:
                self._send(500, {
                    "success": False,
                    "error": "bundle import failed; outcome may be partial",
                    "outcome_unknown": True,
                    "terminal": True,
                    "retryable": False,
                }); return
        try:
            payload = self._read_json()
            self._validate_payload(path, payload)
            if isinstance(payload, dict) and "root" in payload and payload["root"]:
                self._request_root = str(payload["root"])
        except services_module.RequestBodyError as exc:
            self._send(exc.status, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
        if (
            not services_module.detailed_diagnostics_enabled(getattr(services_module.APP, "config", {}), store=getattr(services_module.APP, "debug_traces", None))
            and services_module.diagnostic_http_operation("POST", path, payload)
        ):
            self._send(409, services_module.diagnostics_disabled_response())
            return
        if path == "/api/work-orders" and isinstance(payload, services_module.Mapping) and "request_id" in payload:
            supplied_request_id = payload.get("request_id")
            journal_request_id = str(getattr(self, "_trace_request_id", ""))
            if supplied_request_id != journal_request_id:
                self._send(400, {
                    "success": False,
                    "error": "body request_id conflicts with X-LocalAI-Request-ID",
                    "terminal": True,
                    "retryable": False,
                }); return
        self._admin_payload = payload if isinstance(payload, dict) else {}
        mode_rejection = services_module._http_mode_gate_error("POST", path, payload)
        if mode_rejection is not None:
            status = (
                503
                if path == "/api/context/pack"
                else 423 if mode_rejection.get("error_code") == "operational_mode_blocked" else 503
            )
            self._send(status, mode_rejection)
            return
        hardware_rejection = services_module._http_hardware_capability_error(
            path, payload if isinstance(payload, services_module.Mapping) else None,
            getattr(services_module.APP, "config", {}),
        )
        if hardware_rejection is not None:
            self._send(int(hardware_rejection.get("status_code", 403)), hardware_rejection)
            return
        allowed_agent_state_post = {
            "/api/agent-state/memory",
            "/api/agent-state/tasks",
            "/api/agent-state/verification",
            "/api/agent-state/context",
            "/api/agent-state/events/delta",
            "/api/agent-state/blackboard",
            "/api/agent-state/incidents",
            "/api/agent-state/cleanup",
            "/api/agent-state/swarm/dispatch",
            "/api/agent-state/swarm/step",
            "/api/agent-state/swarm/cancel",
        }
        # Learning candidates are global operator state, not repository-scoped
        # task state. Keep the route behind normal authenticated POST access,
        # then reject direct/unbound dispatch before touching the store.
        if path == "/api/agent-state/learning" and getattr(self, "_authorization_actor", "unrecognized") == "unrecognized":
            self._send(403, {"success": False, "error": "learning route requires authenticated operator scope", "terminal": True, "retryable": False}); return
        if path == "/api/agent-state/cleanup" and getattr(self, "_authorization_actor", "unrecognized") == "unrecognized":
            self._send(403, {"success": False, "error": "cleanup route requires authenticated operator scope", "terminal": True, "retryable": False}); return
        if path == "/api/agent-state/tasks" and payload.get("action") in {"projection_restore", "projection_restore_batch"} and getattr(self, "_authorization_actor", "unrecognized") == "unrecognized":
            self._send(403, {"success": False, "error": "projection restore requires authenticated operator scope", "terminal": True, "retryable": False}); return
        if path.startswith("/api/agent-state/") and path not in allowed_agent_state_post and path != "/api/agent-state/learning":
            self._send(403, {"success": False, "error": "agent_state route has no root-scoped access contract", "terminal": True, "retryable": False}); return
        if path == "/api/agent-state/memory" and not self._bind_memory_payload(payload):
            return
        if path == "/api/agent-state/tasks" and not self._bind_task_payload(payload):
            return
        if path == "/api/agent-state/verification" and not self._bind_task_payload(payload):
            return
        if path == "/api/agent-state/verification" and payload.get("action") == "project_command":
            request_id = self.headers.get("X-LocalAI-Request-ID", "")
            if not isinstance(request_id, str) or not services_module.re.fullmatch(r"[0-9a-f]{32}", request_id):
                self._send(400, {"success": False, "error": "project_command requires a 32-character request id", "terminal": True, "retryable": False}); return
            recovery = getattr(services_module.APP, "recovery", None)
            if not isinstance(recovery, services_module.RecoveryJournal):
                self._send(503, {"success": False, "error_code": "request_journal_unavailable", "terminal": True, "retryable": False}); return
        if path == "/api/agent-state/incidents" and not self._bind_incident_payload(payload):
            return
        if path in {
            "/api/agent-state/swarm/dispatch",
            "/api/agent-state/swarm/step",
            "/api/agent-state/swarm/cancel",
        } and not self._bind_swarm_payload(payload):
            return
        if path in {
            "/api/code/ast_rename",
            "/api/ast_rename",
            "/api/code/batch_replace",
            "/api/repo/batch_replace",
        } and not self._bind_repository_root_payload(payload):
            return
        if path in {"/api/repo/cross_repo_contract", "/api/cross_repo_contract"} and not self._bind_multi_repository_payload(payload, cross_repo_contract=True):
            return
        if path in {"/api/cross_project_graph", "/api/cross_project_symbols", "/api/cross_project_impact"} and not self._bind_multi_repository_payload(payload):
            return
        root_scoped_repo_paths = {
            "/api/git/status", "/api/git/diff", "/api/git/history_search",
            "/api/repo/state", "/api/repo/hotspots",
            "/api/hotspots", "/api/repo/generate_tests_for_diff",
            "/api/generate_tests_for_diff", "/api/repo/affected_tests",
            "/api/repo/topology", "/api/test_matrix",
            "/api/security_audit", "/api/code-intelligence/query",
            "/api/code-intelligence/reset", "/api/repo/dead_code",
            "/api/symbol_callgraph",
            "/api/repo/call_graph_diff", "/api/bundle/export",
            "/api/reachability_dead_code", "/api/mutation_test",
            "/api/type_stubs", "/api/split_changes", "/api/synthesize_rules",
            "/api/code_invariants", "/api/generate_dataset", "/api/callers",
            "/api/secret_scan", "/api/schema_inspect", "/api/explain_query",
            "/api/env_compat", "/api/worktree_lease", "/api/worktree_release",
            "/api/worktree_prune", "/api/lint_fix",
            "/api/rag/index", "/api/rag/search", "/api/rag/docset/index",
            "/api/rag/ingest_document", "/api/rag/ingest_diagram",
        }
        if (
            path in root_scoped_repo_paths
            or path.startswith("/api/coord/plan_")
            or path.startswith("/api/coord/worktree_")
            or (path.startswith("/api/repo/") and path not in {"/api/repo/cross_repo_contract"})
            or path.startswith("/api/code/")
        ) and not self._bind_repository_root_payload(payload):
            return
        if path == "/api/agent-state/verification":
            action = payload.get("action", "")
            if action in {"receipt", "completion", "project_command"}:
                receipt = payload.get("receipt") if isinstance(payload.get("receipt"), dict) else {}
                request_task_id = str(payload.get("task_id", "") or "").strip()
                receipt_task_id = str(receipt.get("task_id", "") or "").strip()
                if action == "receipt" and request_task_id and receipt_task_id and request_task_id != receipt_task_id:
                    self._send(404, {"success": False, "error": "task not found", "terminal": True, "retryable": False})
                    return
                scoped_task_id = receipt_task_id or request_task_id
                if scoped_task_id and not self._require_scoped_task(scoped_task_id):
                    return
        if path == "/api/agent-state/context" and not self._bind_context_payload(payload):
            return
        if path == "/api/agent-state/events/delta" and not self._bind_task_event_payload(payload):
            return
        if path == "/api/agent-state/blackboard" and not self._bind_task_board_payload(payload):
            return
        if path.startswith("/api/memory/") and not self._bind_workspace_memory_payload(path, payload):
            return
        if path == "/api/telemetry/tool-accounting":
            self._telemetry_finished = True
            if getattr(services_module.APP, "recovery", None) is not None and not self._claim_recovery(path, payload):
                return
            accepted = rejected = 0
            rejection_reasons: dict[str, int] = {}
            for event in payload.get("events", []):
                try:
                    scoped_event = dict(event) if isinstance(event, dict) else event
                    recorded = services_module.APP.telemetry.record_tool_accounting(scoped_event)
                    if recorded is False:
                        rejected += 1
                        tool = event.get("tool") if isinstance(event, dict) else None
                        reason = "self_accounting" if isinstance(tool, str) and tool[:160] == "local_ai_telemetry" else (
                            "telemetry_disabled" if getattr(services_module.APP.telemetry, "enabled", True) is False else "queue_full"
                        )
                        rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
                        continue
                    accepted += 1
                    if (services_module.APP is not None and getattr(services_module.APP, "endpoint_stats", None) is not None
                            and isinstance(scoped_event.get("event_id"), str)
                            and 0 < len(scoped_event["event_id"]) <= 128
                            and type(scoped_event.get("success")) is bool):
                        try:
                            tool_name = str(scoped_event.get("tool", ""))
                            op_name = str(scoped_event.get("operation", scoped_event.get("action", "")))
                            mcp_name = f"{tool_name}:{op_name}" if op_name and op_name not in ("default", tool_name) else tool_name
                            services_module.APP.endpoint_stats.record_call(
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
            return
        if self._handle_telemetry_post(path, payload):
            return
        if not self._claim_recovery(path, payload):
            return
        self._request_evaluation = payload.get("evaluation")
        trace_store = getattr(services_module.APP, "debug_traces", None)
        api_trace_id = str(getattr(self, "_debug_trace_id", "") or "")
        if trace_store is not None and api_trace_id:
            try:
                trace_store.event(api_trace_id, "handler_started", {"action": path, "payload_keys": sorted(str(key) for key in payload)})
            except Exception:
                # Debug persistence is optional and must not strand a claimed request.
                pass
        try:
            if isinstance(payload, dict):
                async_response = self._async_delivery(path, payload)
                if async_response is not None:
                    status, response = async_response
                    self._send(status, response)
                    return
            post_handler_name = services_module.select_post_handler(post_route_ids)
            if post_handler_name is not None:
                post_handler = getattr(self, post_handler_name)
                if post_handler_name in {
                    "_handle_post_repository_analysis",
                    "_handle_post_cancellable_task_service",
                }:
                    post_handler(payload, route_ids=post_route_ids)
                else:
                    post_handler(payload)
                return
            if 'post_browser_capability_1' in post_route_ids:
                if not services_module.APP.config.get("browser_bridge", {}).get("enabled", True):
                    self._send(501, services_module.capture_failure("unsupported")); return
                origin = str(payload.get("origin", ""))
                try:
                    capability = services_module.issue_capture_capability(services_module.APP.config, origin=origin, tab_id=payload.get("tab_id"), window_id=payload.get("window_id"))
                except Exception as exc:
                    code = getattr(exc, "error_code", "permission_denied")
                    status = int(getattr(exc, "status", 403))
                    self._send(status, {"success": False, "error": str(exc), "error_code": code, "terminal": True, "retryable": False}); return
                ttl = int(services_module.APP.config.get("browser_bridge", {}).get("capability_ttl_seconds", 60))
                self._send(200, {"success": True, "capability": capability, "one_use": True, "expires_in_seconds": ttl, "tab_id": payload.get("tab_id"), "window_id": payload.get("window_id")}); return
            if 'post_browser_capture_abandon_1' in post_route_ids:
                request = {
                    "origin": self.headers.get("Origin", payload.get("origin", "")),
                    "tab_id": payload.get("tab_id"),
                    "window_id": payload.get("window_id"),
                    "request_id": payload.get("request_id"),
                }
                capability = str(payload.get("capability", ""))
                if path == "/api/browser/capture/purge":
                    checked = services_module.validate_capture_request(capability, request)
                    if not checked.get("success"):
                        self._send(int(checked.get("status_code", 403)), checked); return
                    result = services_module.APP.artifacts.purge_browser_capture(payload.get("bundle_artifact_id"))
                    self._send(int(result.get("status_code", 200 if result.get("success") else 400)), result); return
                if path == "/api/browser/capture/stage":
                    staged_payload = dict(payload)
                    staged_payload["origin"] = request["origin"]
                    result = services_module.stage_capture(capability, staged_payload, config=services_module.APP.config)
                elif path == "/api/browser/capture/commit":
                    result = services_module.commit_staged_capture(capability, request, artifacts=services_module.APP.artifacts, config=services_module.APP.config)
                else:
                    result = services_module.abandon_staged_capture(capability, request)
                self._send(int(result.get("status_code", 200 if result.get("success") else 400)), result); return
            if 'post_browser_capture_1' in post_route_ids:
                request = {
                    "origin": self.headers.get("Origin", payload.get("origin", "")),
                    "tab_id": payload.get("tab_id"),
                    "window_id": payload.get("window_id"),
                }
                checked = services_module.validate_capture_request(str(payload.get("capability", "")), request)
                if not checked.get("success"):
                    status = int(checked.get("status_code", 403))
                    self._send(status, checked); return
                if payload.get("capture_error"):
                    failure = services_module.capture_failure(str(payload["capture_error"]))
                    self._send(int(failure["status_code"]), failure); return
                self._send(200, services_module.capture_to_artifacts(payload, artifacts=services_module.APP.artifacts, config=services_module.APP.config)); return
            delivery = self._async_delivery(path, payload)
            if delivery is not None:
                self._send(*delivery); return
            if path == "/api/delegate":
                connection = getattr(self, "connection", None) if getattr(self, "headers", {}).get("X-LocalAI-Cancel-On-Disconnect") == "1" else None
                if bool(payload.get("conversation", False)):
                    result = services_module._invoke_cancellable_request(services_module._ACTIVE_CONVERSATIONS, services_module.APP.services.delegate, payload, connection=connection)
                    self._send(200, result); return
                if connection is not None:
                    result = services_module._invoke_cancellable_request(services_module._ACTIVE_DELEGATES, services_module.APP.services.delegate, payload, connection=connection)
                    self._send(200, result); return
                self._send(200, services_module.APP.services.delegate(payload)); return
            if path == "/api/conversations/continue":
                connection = getattr(self, "connection", None) if getattr(self, "headers", {}).get("X-LocalAI-Cancel-On-Disconnect") == "1" else None
                result = services_module._invoke_cancellable_request(services_module._ACTIVE_CONVERSATIONS, services_module.APP.services.continue_conversation, payload, connection=connection)
                self._send(200, result); return
            if 'post_benchmark_run_1' in post_route_ids:
                if not getattr(services_module.APP, "benchmark_runner", None):
                    self._send(503, {"success": False, "error": "benchmark runner unavailable"}); return
                model = str(payload.get("model", ""))
                prompt = str(payload.get("prompt", payload.get("task", "")))
                num_tokens = int(payload.get("num_tokens", payload.get("max_tokens", 40)))
                res = services_module.APP.benchmark_runner.run(
                    model=model,
                    prompt=prompt or "def test(): pass\n",
                    num_tokens=num_tokens,
                    context_tokens=payload.get("context_tokens"),
                )
                self._send(200, res); return
            if 'post_gpu_reservation_1' in post_route_ids:
                scheduler = getattr(services_module.APP, "scheduler", None)
                if scheduler is None:
                    self._send(503, {"success": False, "error": "scheduler unavailable"}); return
                operation = str(payload.get("action", ""))
                res = scheduler.gpu_reservation_operation(
                    action=operation,
                    generation=payload.get("generation", ""),
                    consent=payload.get("consent"),
                    audit_reason=payload.get("audit_reason", ""),
                    lease_id=payload.get("lease_id", ""),
                    owner=payload.get("owner", ""),
                    ollama_runner_probe=(lambda: services_module._ollama_runner_present(services_module.APP.config))
                    if operation == "release_scheduler_capacity_lease" else None,
                )
                self._send(200, res); return
            if 'post_patch_validate_1' in post_route_ids:
                result = services_module.APP.services.validate_patch(payload)
                self._send(result.get("status_code", 200), result)
                return
            if 'post_query_expand_1' in post_route_ids:
                q = payload.get("query", "")
                self._send(200, {"success": True, "query": q, "expanded_terms": services_module.APP.services.expand_query(
                    q, root=payload.get("root", ""), session_id=payload.get("session_id", ""),
                )})
                return
            if 'post_audit_dependencies_1' in post_route_ids:
                root = str(payload.get("root", "."))
                if services_module.APP.deterministic is not None:
                    self._send(200, services_module.APP.deterministic.audit_dependencies(root))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if 'post_refactor_impact_1' in post_route_ids:
                root = str(payload.get("root", "."))
                file_param = str(payload.get("file", payload.get("path", "")))
                symbol_param = payload.get("symbol")
                if services_module.APP.deterministic is not None:
                    self._send(200, services_module.APP.services.refactor_impact(root, file_param, symbol_param))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if 'post_resolve_imports_1' in post_route_ids:
                root = str(payload.get("root", "."))
                lang = str(payload.get("language", "auto"))
                syms = payload.get("symbols", [payload.get("symbol")] if payload.get("symbol") else [])
                if services_module.APP.deterministic is not None:
                    self._send(200, services_module.APP.services.resolve_imports(root, syms, lang))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if 'post_generate_tests_for_diff_1' in post_route_ids:
                root = str(payload.get("root", "."))
                diff = payload.get("diff")
                p = payload.get("path")
                if services_module.APP.deterministic is not None:
                    self._send(200, services_module.APP.services.generate_tests_for_diff(root, diff=diff, path=p))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if 'post_cross_repo_contract_1' in post_route_ids:
                b_root = str(payload.get("backend_root", payload.get("root", ".")))
                f_root = str(payload.get("frontend_root", payload.get("client_root", ".")))
                if services_module.APP.deterministic is not None:
                    self._send(200, services_module.APP.services.cross_repo_contract(b_root, f_root))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if 'post_affected_tests_1' in post_route_ids:
                root = str(payload.get("root", "."))
                paths = payload["paths"] if "paths" in payload else payload.get("changed_paths")
                if paths is not None and not isinstance(paths, list):
                    raise ValueError("paths must be a JSON array or null")
                if services_module.APP.deterministic is not None:
                    self._send(200, services_module.APP.services.affected_tests(root, changed_paths=paths))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if 'post_repo_topology_1' in post_route_ids:
                root = str(payload.get("root", "."))
                if services_module.APP.deterministic is not None:
                    self._send(200, services_module.APP.services.repo_topology(root))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if 'post_ast_rename_1' in post_route_ids:
                root = str(payload.get("root", "."))
                target_file = str(payload.get("file", payload.get("path", "")))
                old_sym = str(payload.get("old_symbol", payload.get("symbol", "")))
                new_sym = str(payload.get("new_symbol", payload.get("replacement", "")))
                apply_changes = bool(payload.get("apply", False))
                if services_module.APP.deterministic is not None:
                    self._send(200, services_module.APP.services.ast_rename(root, target_file, old_sym, new_sym, apply_changes=apply_changes))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if 'post_code_generate_mocks_1' in post_route_ids:
                root = str(payload.get("root", "."))
                target_file = str(payload.get("file", payload.get("path", "")))
                symbol = str(payload.get("symbol", ""))
                if services_module.APP.deterministic is not None:
                    self._send(200, services_module.APP.services.generate_mocks(root, target_file, symbol))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if 'post_security_audit_1' in post_route_ids:
                root = str(payload.get("root", "."))
                limit = int(payload.get("limit", 50))
                if services_module.APP.deterministic is not None:
                    self._send(200, services_module.APP.services.security_audit(root, limit))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if 'post_code_intelligence_query_1' in post_route_ids:
                root = str(payload.get("root", "."))
                self._send(200, services_module.APP.external_tools.query(
                    root, str(payload.get("query", "")),
                    backend=str(payload.get("backend", "auto")),
                    action=str(payload.get("action", "search")),
                    path=str(payload.get("path", "")),
                    limit=max(1, min(int(payload.get("limit", 20)), 50)),
                ))
                return
            if 'post_code_ast_outline_1' in post_route_ids:
                root = str(payload.get("root", "."))
                path_param = str(payload.get("path", payload.get("file", "")))
                if services_module.APP.deterministic is not None:
                    self._send(200, services_module.APP.services.ast_outline(root, path_param))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if 'post_code_batch_replace_1' in post_route_ids:
                root = str(payload.get("root", "."))
                edits = payload.get("edits") or payload.get("replacements") or []
                dry_run = bool(payload.get("dry_run", False))
                self._send(200, services_module.APP.services.batch_replace(
                    root,
                    edits if isinstance(edits, list) else [],
                    dry_run=dry_run,
                    owner=payload.get("owner"),
                    lease_id=payload.get("lease_id"),
                    lease_store=services_module.APP.leases,
                ))
                return
            if 'post_maintenance_optimize_db_1' in post_route_ids:
                self._send(200, services_module.APP.services.optimize_databases())
                return
            if 'post_debug_trace_purge_1' in post_route_ids:
                if set(payload) != {"confirm"} or type(payload.get("confirm")) is not bool or payload["confirm"] is not True:
                    self._send(400, {"success": False, "error": "explicit confirm=true is required", "terminal": True, "retryable": False})
                    return
                result = services_module.APP.debug_traces.purge()
                status = 200 if result.get("success") is True else 503 if result.get("retryable") else 500
                self._send(status, result)
                return
            if 'post_maintenance_purge_cache_1' in post_route_ids:
                days = int(payload.get("days", 7))
                self._send(200, services_module.APP.services.purge_stale_cache(days))
                return
            if 'post_maintenance_resolve_errors_1' in post_route_ids:
                result = services_module.APP.services.resolve_all_errors()
                status = 200 if result.get("success") is True else 503 if result.get("retryable") else 500
                self._send(status, result)
                return
            if 'post_doctor_1' in post_route_ids:
                self._send(200, services_module.APP.services.run_doctor())
                return
            if 'post_code_symbol_1' in post_route_ids:
                root = str(payload.get("root", "."))
                sym = str(payload.get("symbol", ""))
                self._send(200, services_module.APP.services.code_inspect_symbol(root, sym))
                return
            if 'post_code_find_symbol_1' in post_route_ids:
                root = str(payload.get("root", "."))
                pat = str(payload.get("pattern") or payload.get("name_path_pattern") or "")
                depth = int(payload.get("depth", 0))
                include_body = services_module._parse_include_body(payload.get("include_body", False))
                if include_body is None:
                    self._send(400, {"success": False, "error": "include_body must be a boolean"})
                    return
                include_info = bool(payload.get("include_info", True))
                rel_path = payload.get("path") or payload.get("relative_path")
                limit = int(payload.get("limit", 30))
                self._send(200, services_module.APP.services.code_find_symbol(root, pat, depth=depth, include_body=include_body, include_info=include_info, relative_path=str(rel_path) if rel_path else None, limit=limit))
                return
            if 'post_code_find_implementations_1' in post_route_ids:
                root = str(payload.get("root", "."))
                sym = str(payload.get("symbol") or payload.get("name") or "")
                rel_path = payload.get("path")
                self._send(200, services_module.APP.services.code_find_implementations(root, sym, path=str(rel_path) if rel_path else None))
                return
            if 'post_code_find_referencing_symbols_1' in post_route_ids:
                root = str(payload.get("root", "."))
                sym = str(payload.get("symbol") or payload.get("name") or "")
                rel_path = payload.get("path")
                self._send(200, services_module.APP.services.code_find_referencing_symbols(root, sym, path=str(rel_path) if rel_path else None))
                return
            if 'post_code_symbols_overview_1' in post_route_ids:
                root = str(payload.get("root", "."))
                fpath = str(payload.get("path", ""))
                depth = int(payload.get("depth", 1))
                self._send(200, services_module.APP.services.code_symbols_overview(root, fpath, depth=depth))
                return
            if 'post_code_diagnostics_1' in post_route_ids:
                root = str(payload.get("root", "."))
                fpath = str(payload.get("path", ""))
                self._send(200, services_module.APP.services.code_diagnostics(root, fpath))
                return
            if 'post_code_intelligence_control_1' in post_route_ids:
                action = str(payload.get("action", "status")).strip().lower().replace("-", "_")
                if action == "status":
                    self._send(200, {"success": True, **services_module.APP.external_tools.status()}); return
                if action in {"rediscover", "refresh"}:
                    self._send(200, services_module.APP.external_tools.rediscover()); return
                if action in {"reset", "reset_sessions"}:
                    self._send(200, services_module.APP.external_tools.reset_sessions(str(payload.get("backend", "all")), str(payload.get("root")) if payload.get("root") else None)); return
                self._send(400, {"success": False, "error": f"unknown code-intelligence action: {action}"}); return
            if 'post_complete_1' in post_route_ids:
                # FIM completion routed through APP.services with caching / APP.scheduler.submit
                connection = getattr(self, "connection", None) if getattr(self, "headers", {}).get("X-LocalAI-Cancel-On-Disconnect") == "1" else None
                if connection is not None:
                    result = services_module._invoke_cancellable_request(services_module._ACTIVE_DELEGATES, services_module.APP.services.complete_code, payload, connection=connection)
                    self._send(200, result); return
                self._send(200, services_module.APP.services.complete_code(payload)); return
            if 'post_preprocess_1' in post_route_ids:
                self._send(200, services_module.APP.services.preprocess(payload)); return
            if 'post_dead_code_1' in post_route_ids:
                root = str(payload.get("root", "."))
                limit = int(payload.get("limit", 50))
                self._send(200, services_module.APP.services.dead_code(root, limit))
                return
            if 'post_symbol_callgraph_1' in post_route_ids:
                root = str(payload.get("root", "."))
                sym = payload.get("symbol")
                limit = int(payload.get("limit", 50))
                self._send(200, services_module.APP.services.symbol_callgraph(root, str(sym) if sym else None, limit))
                return
            if 'post_cross_project_graph_1' in post_route_ids:
                roots = payload.get("roots")
                if not isinstance(roots, list) or not roots:
                    roots = [str(p.get("root")) for p in services_module.APP.preprocessor.status().get("projects", []) if p.get("root")]
                if services_module.APP.deterministic is not None:
                    self._send(200, services_module.APP.deterministic.cross_project_graph([str(r) for r in roots]))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if 'post_cross_project_symbols_1' in post_route_ids:
                roots = payload.get("roots")
                if not isinstance(roots, list) or not roots:
                    roots = [str(p.get("root")) for p in services_module.APP.preprocessor.status().get("projects", []) if p.get("root")]
                query = str(payload.get("query", ""))
                limit = int(payload.get("limit", 50))
                if services_module.APP.deterministic is not None:
                    self._send(200, services_module.APP.deterministic.cross_repo_symbol_find([str(r) for r in roots], query, limit))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if 'post_cross_project_impact_1' in post_route_ids:
                roots = payload.get("roots")
                if not isinstance(roots, list) or not roots:
                    roots = [str(p.get("root")) for p in services_module.APP.preprocessor.status().get("projects", []) if p.get("root")]
                symbol = str(payload.get("symbol", payload.get("query", "")))
                origin_root = payload.get("origin_root")
                if services_module.APP.deterministic is not None:
                    self._send(200, services_module.APP.deterministic.cross_project_impact(symbol, [str(r) for r in roots], str(origin_root) if origin_root else None))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if 'post_repo_call_graph_diff_1' in post_route_ids:
                root = str(payload.get("root", "."))
                diff = payload.get("diff")
                if services_module.APP.deterministic is not None:
                    if "old_code" in payload or "new_code" in payload:
                        result = services_module.APP.deterministic.ast_diff(payload.get("old_code"), payload.get("new_code"))
                        if result.get("success"):
                            try:
                                artifact_id = services_module.APP.artifacts.put_json(result, kind="ast-structural-diff")
                                if not isinstance(artifact_id, str) or not artifact_id:
                                    raise ValueError("artifact ID unavailable")
                            except Exception:
                                self._send(503, {"success": False, "terminal": False, "retryable": True,
                                                 "error_code": "ast_diff_artifact_unavailable",
                                                 "error": "structural diff artifact could not be stored"}); return
                            changes = result["changes"]
                            preview: list[dict[str, Any]] = []
                            preview_chars = 0
                            for change in changes[:32]:
                                size = len(services_module.json.dumps(change, ensure_ascii=False, separators=(",", ":")))
                                if preview_chars + size > 8000:
                                    break
                                preview.append(change)
                                preview_chars += size
                            result = {**result, "artifact_id": artifact_id, "changes_total": len(changes),
                                      "changes_returned": len(preview), "changes": preview,
                                      "truncated": len(changes) > len(preview)}
                            if len(changes) > len(preview) or len(services_module.json.dumps(result["tree"], ensure_ascii=False, separators=(",", ":"))) + preview_chars > 8000:
                                result.pop("tree", None)
                                result["tree_in_artifact"] = True
                                result["truncated"] = True
                        self._send(200, result)
                    else:
                        self._send(200, services_module.APP.deterministic.call_graph_diff(root, diff=diff))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if 'post_diagnostics_export_1' in post_route_ids:
                self._handle_post_diagnostics_export(payload)
                return

            if 'post_bundle_export_1' in post_route_ids:
                root = str(payload.get("root", "."))
                try:
                    data = services_module.APP.export_bundle(root)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/zip")
                    self._common_headers()
                    self.send_header("Content-Disposition", 'attachment; filename="local-ai-hub-project.bundle.zip"')
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except Exception as exc:
                    if not services_module._is_client_disconnect(exc):
                        self._send(500, {
                            "success": False,
                            "error": "bundle export unavailable",
                            "error_code": "bundle_export_unavailable",
                            "terminal": True,
                            "retryable": False,
                        })
                return
            if 'post_benchmark_1' in post_route_ids:
                self._send(200, services_module.APP.services.benchmark()); return
            if 'post_evaluation_1' in post_route_ids:
                self._send(200, services_module.APP.services.evaluation(payload)); return
            if 'post_repo_knowledge_manage_1' in post_route_ids:
                from .repo_knowledge_management import manage_repository_knowledge
                def knowledge_operator_write() -> bool:
                    # Local-owner trust is established by normal Host/Origin and
                    # loopback checks above; the desktop marker is not identity.
                    return (
                        getattr(self, "_authorization_actor", "") == "local"
                        and self.headers.get("X-LocalAI-Client", "") == "desktop"
                        and self.headers.get("Sec-Fetch-Site", "").lower() == "same-origin"
                        and bool(self.headers.get("Origin", "").strip())
                    )
                result = manage_repository_knowledge(
                    services_module.APP.config, payload, authorize_operator_write=knowledge_operator_write,
                )
                self._send(int(result.pop("status_code", 200)), result)
                return
            if 'post_repo_knowledge_query_1' in post_route_ids:
                from .repo_knowledge import query_repository_knowledge
                result = query_repository_knowledge(services_module.APP.config, payload)
                self._send(int(result.pop("status_code", 200)), result)
                return
            if 'post_search_1' in post_route_ids:
                if "exact_count" in payload and type(payload["exact_count"]) is not bool:
                    self._send(400, {
                        "success": False,
                        "status_code": 400,
                        "terminal": True,
                        "retryable": False,
                        "error": "exact_count must be a boolean",
                    })
                    return
                if "search_mode" in payload and (
                    type(payload["search_mode"]) is not str
                    or payload["search_mode"] not in {"lexical", "rag", "hybrid"}
                ):
                    self._send(400, {"success": False, "terminal": True, "retryable": False,
                                     "error": "search_mode must be lexical, rag, or hybrid"}); return
                query_text = str(payload.get("query", ""))
                search_mode = payload.get("search_mode")
                if "search_mode" not in payload:
                    search_mode = services_module.default_agent_search_mode(query_text)
                result = services_module.APP.services.repo_search(
                    str(payload.get("root", ".")),
                    query_text,
                    int(payload.get("top_k", 12)),
                    context_lines=int(payload["context_lines"]) if payload.get("context_lines") is not None else None,
                    enrich=bool(payload.get("enrich", False)),
                    limit=payload.get("limit", 24),
                    offset=payload.get("offset", 0),
                    path_hints=payload.get("path_hints"),
                    search_mode=search_mode,
                    exact_count=payload.get("exact_count", False),
                )
                status = int(result.pop("status_code", 200))
                self._send(status, result); return
            if path == "/api/context/pack":
                from .http_post_context import handle_context_pack
                handle_context_pack(self, path, payload)
                return

            if 'post_artifact_get_1' in post_route_ids:
                self._handle_post_artifact_get(payload)
                return
            if 'post_artifact_list_1' in post_route_ids:
                self._handle_post_artifact_list(payload)
                return
            if 'post_evidence_verify_1' in post_route_ids:
                evidence = payload.get("evidence", [])
                self._send(200, services_module.APP.repo_tools.verify_evidence(str(payload.get("root", ".")), evidence if isinstance(evidence, list) else [])); return
            if 'post_evidence_get_1' in post_route_ids:
                self._send(200, services_module.APP.evidence.get(str(payload.get("evidence_id", "")), verify=bool(payload.get("verify", True)))); return
            if 'post_leases_claim_1' in post_route_ids:
                self._handle_post_lease_claim(payload)
                return
            if path == "/api/leases/release":
                self._handle_post_lease_release(payload)
                return
            if 'post_leases_renew_1' in post_route_ids:
                self._handle_post_lease_renew(payload)
                return
            if 'post_memory_put_1' in post_route_ids:
                self._send(200, services_module.APP.memory.put(str(payload.get("root", ".")), str(payload.get("key", "")), str(payload.get("value", "")), ttl_seconds=payload.get("ttl_seconds"), metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None, expected_version=payload.get("expected_version"))); return
            if 'post_memory_get_1' in post_route_ids:
                self._send(200, services_module.APP.memory.get(str(payload.get("root", ".")), str(payload.get("key", "")))); return
            if 'post_memory_search_1' in post_route_ids:
                self._send(200, services_module.APP.memory.search(str(payload.get("root", ".")), str(payload.get("query", "")), int(payload.get("limit", 12)))); return
            if path == "/api/memory/delete":
                self._send(200, services_module.APP.memory.delete(str(payload.get("root", ".")), str(payload.get("key", "")))); return
            if path == "/api/embed":
                texts = payload.get("texts", payload.get("input", []))
                if isinstance(texts, str):
                    texts = [texts]
                self._send(200, services_module.APP.services.embed([str(x) for x in texts], query=bool(payload.get("query", False)))); return
            if 'post_rerank_1' in post_route_ids:
                docs = payload.get("documents", [])
                self._send(200, services_module.APP.reranker.rerank(str(payload.get("query", "")), [str(x) for x in docs], payload.get("top_k"))); return
            if 'post_rag_index_1' in post_route_ids:
                root = str(payload.get("root", "."))
                result = services_module.APP.rag.index(root, workspace=payload.get("workspace"))
                if isinstance(result, dict) and result.get("success") is True:
                    services_module.APP.services._touch_project(root)
                status, result = services_module._api_result_http_response(result)
                self._send(status, result); return
            if 'post_rag_search_1' in post_route_ids:
                workspace = str(payload.get("workspace", ""))
                if not workspace:
                    self._send(400, {"success": False, "error": "workspace is required"}); return
                root = payload["root"]
                services_module.APP.rag.require_workspace_root(workspace=workspace, root=root)
                services_module.APP.services._touch_project(str(root))
                try:
                    reranking_available = services_module.FeatureSet(services_module.APP.config).capability_status().get("reranking", {}).get("available") is True
                except Exception:
                    reranking_available = False
                use_reranker = payload.get("use_reranker") is True and reranking_available
                query = str(payload.get("query", ""))
                connection = getattr(self, "connection", None) if getattr(self, "headers", {}).get("X-LocalAI-Cancel-On-Disconnect") == "1" else None
                laya_strategy = None
                strategy_router = getattr(services_module.APP.services, "recommend_direct_rag_strategy", None)
                # The adaptive preflight performs its own bounded retrieval. Keep
                # disconnect-cancellable requests on the single deterministic path
                # so a dropped client cannot be held by work outside the cancel gate.
                if connection is None and callable(strategy_router):
                    try:
                        laya_strategy = strategy_router(root, query, workspace=workspace)
                    except Exception:
                        laya_strategy = None
                deadline = services_module.time.perf_counter() + services_module.repository_search_timeout(services_module.APP.config)
                options = {"workspace": workspace, "top_k": int(payload.get("top_k", 8)),
                           "use_reranker": use_reranker,
                           "semantic_only": laya_strategy != "lexical_bm25",
                           "deadline": deadline}
                if laya_strategy == "lexical_bm25":
                    options["lexical_only"] = True

                def search_with_lexical_fallback(cancel_event=None):
                    search_options = dict(options)
                    if cancel_event is not None:
                        search_options["cancel_event"] = cancel_event
                    semantic_result = services_module.APP.rag.search(query, **search_options)
                    if laya_strategy == "lexical_bm25":
                        if (
                            isinstance(semantic_result, dict)
                            and semantic_result.get("success") is True
                            and semantic_result.get("results")
                        ):
                            return semantic_result
                        semantic_options = {
                            **options,
                            "semantic_only": True,
                            "lexical_only": False,
                        }
                        if cancel_event is not None:
                            semantic_options["cancel_event"] = cancel_event
                        baseline_result = services_module.APP.rag.search(query, **semantic_options)
                        if isinstance(baseline_result, dict) and baseline_result.get("success") is True:
                            return {
                                **baseline_result,
                                "degraded": True,
                                "laya_retrieval_fallback": "lexical_no_results_or_error",
                            }
                        return {
                            **(semantic_result if isinstance(semantic_result, dict) else {}),
                            "degraded": True,
                            "laya_retrieval_fallback": "lexical_and_semantic_failed",
                            "semantic_fallback_error": baseline_result.get("error") if isinstance(baseline_result, dict) else None,
                        }
                    if not (
                        isinstance(semantic_result, dict)
                        and semantic_result.get("success") is True
                        and semantic_result.get("fallback") == "embedding_backend"
                    ):
                        return semantic_result

                    lexical_options = {
                        **options,
                        "semantic_only": False,
                        "lexical_only": True,
                    }
                    if cancel_event is not None:
                        lexical_options["cancel_event"] = cancel_event
                    lexical_result = services_module.APP.rag.search(query, **lexical_options)
                    if not (
                        isinstance(lexical_result, dict)
                        and lexical_result.get("success") is True
                        and lexical_result.get("results")
                    ):
                        return semantic_result
                    return {
                        **lexical_result,
                        "degraded": True,
                        "semantic_fallback_used": True,
                        "semantic_fallback_reason": semantic_result.get("reason", "embedding_backend_unavailable"),
                        "reason": semantic_result.get("reason", "embedding_backend_unavailable"),
                    }

                if connection is None:
                    result = search_with_lexical_fallback()
                else:
                    result = services_module._invoke_cancellable_request(
                        services_module._ACTIVE_DELEGATES,
                        lambda _request, *, cancel_event: search_with_lexical_fallback(cancel_event=cancel_event),
                        payload,
                        connection=connection,
                    )
                if laya_strategy is not None and isinstance(result, dict):
                    result["laya_retrieval_strategy"] = laya_strategy
                    if laya_strategy == "dense_rag" and result.get("semantic_fallback_used") is True:
                        result["laya_retrieval_fallback"] = "embedding_backend"
                self._send(200, result); return
            if 'post_speculative_draft_1' in post_route_ids:
                connection = getattr(self, "connection", None) if getattr(self, "headers", {}).get("X-LocalAI-Cancel-On-Disconnect") == "1" else None
                if connection is not None:
                    result = services_module._invoke_cancellable_request(services_module._ACTIVE_DELEGATES, services_module.APP.services.speculative_draft, payload, connection=connection)
                    self._send(200, result); return
                self._send(200, services_module.APP.services.speculative_draft(payload)); return
            if 'post_scaffold_1' in post_route_ids:
                connection = getattr(self, "connection", None) if getattr(self, "headers", {}).get("X-LocalAI-Cancel-On-Disconnect") == "1" else None
                if connection is not None:
                    result = services_module._invoke_cancellable_request(services_module._ACTIVE_DELEGATES, services_module.APP.services.task_scaffold, payload, connection=connection)
                    self._send(200, result); return
                self._send(200, services_module.APP.services.task_scaffold(payload)); return
            if 'post_models_manage_1' in post_route_ids:
                action = str(payload.get("action", "list"))
                model_name = str(payload.get("model", ""))
                self._send(200, self._handle_models_action(action, model_name)); return
            if 'post_reachability_dead_code_1' in post_route_ids:
                root = str(payload.get("root", "."))
                eps = payload.get("entrypoints")
                limit = payload.get("limit", 100)
                if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
                    self._send(400, {"success": False, "error": "limit must be an integer from 1 to 200"}); return
                if services_module.APP.deterministic is not None:
                    self._send(200, services_module.APP.deterministic.reachability_dead_code(root, entrypoints=eps, limit=limit)); return
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"}); return
            if 'post_mutation_test_1' in post_route_ids:
                root = str(payload.get("root", "."))
                tf = str(payload.get("file", payload.get("path", "")))
                diff = payload.get("diff")
                if services_module.APP.deterministic is not None:
                    self._send(200, services_module.APP.deterministic.ast_mutation_test(root, tf, diff=diff)); return
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"}); return
            if 'post_repo_type_stubs_1' in post_route_ids:
                root = str(payload.get("root", "."))
                fp = str(payload.get("file", payload.get("path", "")))
                if services_module.APP.deterministic is not None:
                    self._send(200, services_module.APP.deterministic.generate_type_stubs(root, fp)); return
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"}); return
            if 'post_repo_skeletonize_1' in post_route_ids:
                code = str(payload.get("code", ""))
                targets = payload.get("targets") or payload.get("target_symbols")
                if services_module.APP.deterministic is not None:
                    self._send(200, services_module.APP.deterministic.skeletonize_code(
                        code, target_symbols=targets, root=str(payload.get("root", "")),
                        path=str(payload.get("path", "")),
                    )); return
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"}); return
            if 'post_agent_state_events_delta_1' in post_route_ids:
                action = payload.get("action", "export")
                if action == "export":
                    stream_id = str(payload.get("stream_id", ""))
                    after_seq = int(payload.get("after_seq", 0))
                    limit = int(payload.get("limit", 1000))
                    self._send(200, services_module.APP.agent_state_store.export_delta(stream_id, after_seq, limit)); return
                else:
                    events = list(payload.get("events", []))
                    self._send(200, services_module.APP.agent_state_store.import_delta(events)); return
            if 'post_task_vision_1' in post_route_ids:
                connection = getattr(self, "connection", None) if getattr(self, "headers", {}).get("X-LocalAI-Cancel-On-Disconnect") == "1" else None
                if connection is not None:
                    result = services_module._invoke_cancellable_request(services_module._ACTIVE_DELEGATES, services_module.APP.services.vision, payload, connection=connection)
                    self._send(200, result); return
                self._send(200, services_module.APP.services.vision(payload)); return
            if 'post_task_browser_1' in post_route_ids:
                from .browser_bridge import capture_browser_page
                result = capture_browser_page(payload.get("url", ""), artifacts=services_module.APP.artifacts, state_dir=services_module.APP.config["server"]["state_dir"], viewport=payload.get("viewport"))
                self._send(200, result); return
            if 'post_task_automation_1' in post_route_ids:
                self._handle_task_automation(payload); return
            if 'post_repo_split_changes_1' in post_route_ids:
                root = str(payload.get("root", "."))
                try:
                    paths = split_change_paths_from_payload(payload)
                except ValueError as exc:
                    self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False})
                    return
                result = services_module.APP.services.split_changes(
                    root, paths, mode=payload.get("mode", "summary"),
                    limit=payload.get("limit", 8), offset=payload.get("offset", 0),
                    base=payload.get("base"), head=payload.get("head", "HEAD"), task_id=payload.get("task_id", ""),
                    expected_revision=payload.get("expected_revision"),
                    continuation_revision=payload.get("continuation_revision"),
                )
                self._send(200, result); return
            if 'post_repo_synthesize_rules_1' in post_route_ids:
                root = str(payload.get("root", "."))
                limit = int(payload.get("limit", 10))
                self._send(200, services_module.APP.services.synthesize_rules(root, limit)); return
            if 'post_rag_docset_index_1' in post_route_ids:
                name = str(payload.get("name", payload.get("docset", "")))
                root = str(payload.get("root", payload.get("dir", ".")))
                self._send(200, services_module.APP.rag.docset_index(name, root=root)); return
            if 'post_rag_docset_search_1' in post_route_ids:
                name = str(payload.get("name", payload.get("docset", "")))
                query = str(payload.get("query", ""))
                top_k = int(payload.get("top_k", 8))
                self._send(200, services_module.APP.rag.docset_search(name, query=query, top_k=top_k)); return
            if 'post_task_transcribe_1' in post_route_ids:
                from .process_utils import ProcessCleanupUnverifiedError
                token, cancel_event = services_module._ACTIVE_TRANSCRIPTIONS.begin()
                connection = getattr(self, "connection", None) if getattr(self, "headers", {}).get("X-LocalAI-Cancel-On-Disconnect") == "1" else None
                stop_monitor, monitor = services_module._start_disconnect_monitor(connection, cancel_event)
                result: Any = {}
                cleanup_deferred = False
                try:
                    result = services_module.APP.services.transcribe(payload, cancel_event=cancel_event)
                    self._send(200, result); return
                except ProcessCleanupUnverifiedError as exc:
                    cleanup_deferred = True
                    result = {
                        "success": False, "reason": "cleanup_unverified", "error": str(exc),
                        "terminal": False, "retryable": True, "cleanup_unverified": True,
                    }
                    services_module._ACTIVE_TRANSCRIPTIONS.defer_process_cleanup(
                        token, exc.process, tree_termination_confirmed=exc.tree_termination_confirmed,
                    )
                    self._send(503, result); return
                finally:
                    stop_monitor.set()
                    if monitor is not None:
                        monitor.join(timeout=0.2)
                    if not cleanup_deferred:
                        services_module._ACTIVE_TRANSCRIPTIONS.finish(token, result)
            if path in {"/api/repo/code_invariants", "/api/code_invariants"}:
                self._send(200, services_module.APP.services.code_invariants(str(payload.get("root", ".")), payload.get("path"))); return
            if 'post_generate_dataset_1' in post_route_ids:
                self._send(200, services_module.APP.services.generate_dataset(str(payload.get("root", ".")), payload.get("schema_or_model") or payload.get("schema"), count=int(payload.get("count", 10)), format=str(payload.get("format", "json")))); return
            if 'post_profile_digest_1' in post_route_ids:
                self._send(200, services_module.APP.services.profile_digest(str(payload.get("profile_path") or payload.get("path") or ""), top_n=int(payload.get("top_n", 15)))); return
            if 'post_coord_worktree_lease_1' in post_route_ids:
                self._send(200, services_module.APP.services.worktree_lease(str(payload.get("root", ".")), branch_name=payload.get("branch"))); return
            if path == "/api/coord/worktree_release":
                self._send(200, services_module.APP.services.worktree_release(str(payload.get("root", ".")), str(payload.get("worktree_path", "")), delete_branch=bool(payload.get("delete_branch", True)), branch_name=payload.get("branch"), worktree_id=str(payload.get("worktree_id", "")))); return
            if path == "/api/coord/worktrees":
                self._send(200, services_module.APP.services.list_worktrees(str(payload.get("root", ".")))); return
            if 'post_coord_worktree_prune_1' in post_route_ids:
                self._send(200, services_module.APP.services.prune_worktrees(str(payload.get("root", ".")))); return

            if 'post_repo_patch_1' in post_route_ids:
                root = str(payload.get("root", "."))
                path_val = str(payload.get("path", ""))
                old_code = str(payload.get("old_code", ""))
                new_code = str(payload.get("new_code", ""))
                res = services_module.APP.repo_tools.apply_patch(root, path_val, old_code, new_code)
                status = 200 if res.get("success") else res.get("status_code", 400)
                self._send(status, res); return
            if 'post_repo_call_graph_1' in post_route_ids:
                root = payload.get("root", ".")
                symbol = payload.get("symbol") or payload.get("query", "")
                path_val = payload.get("path")
                depth = payload.get("depth", 1)
                limit = payload.get("limit", 50)
                result = services_module.APP.services.call_graph(root, symbol, path=path_val, depth=depth, limit=limit)
                status = int(result.pop("status_code", 200))
                self._send(status, result); return
            if 'post_repo_git_status_1' in post_route_ids:
                root = str(payload.get("root", "."))
                res = services_module.APP.repo_tools.git_status(root)
                self._send(200 if res.get("success") else 400, res); return
            if 'post_repo_revert_1' in post_route_ids:
                root = str(payload.get("root", "."))
                path_val = str(payload.get("path", ""))
                res = services_module.APP.repo_tools.git_revert_file(root, path_val)
                self._send(200 if res.get("success") else 400, res); return
            if 'post_repo_find_files_1' in post_route_ids:
                root = str(payload.get("root", "."))
                pat = str(payload.get("pattern") or payload.get("query") or "*")
                limit_val = payload.get("limit", 100)
                offset_val = payload.get("offset", 0)
                res = services_module.APP.repo_tools.find_files(root, pattern=pat, limit=limit_val, offset=offset_val)
                status = int(res.pop("status_code", 200 if res.get("success") else 400))
                self._send(status, res); return
            if 'post_repo_file_info_1' in post_route_ids:
                root = str(payload.get("root", "."))
                path_val = str(payload.get("path", ""))
                res = services_module.APP.repo_tools.file_info(root, path_val)
                self._send(200 if res.get("success") else 400, res); return
            if 'post_callers_1' in post_route_ids:
                limit = payload.get("limit", 50); offset = payload.get("offset", 0)
                bounds_error = services_module.pagination_bounds_error(limit, offset)
                if bounds_error:
                    self._send(400, {"success": False, "status_code": 400, "terminal": True, "retryable": False, "error": bounds_error}); return
                self._send(200, services_module.APP.services.callers(str(payload.get("root", ".")), str(payload.get("symbol", "")), limit=limit, offset=offset)); return
            if 'post_callees_1' in post_route_ids:
                limit = payload.get("limit", 50); offset = payload.get("offset", 0)
                bounds_error = services_module.pagination_bounds_error(limit, offset)
                if bounds_error:
                    self._send(400, {"success": False, "status_code": 400, "terminal": True, "retryable": False, "error": bounds_error}); return
                self._send(200, services_module.APP.services.callees(str(payload.get("root", ".")), str(payload.get("symbol", "")), limit=limit, offset=offset)); return
            if 'post_implementations_1' in post_route_ids:
                limit = payload.get("limit", 50); offset = payload.get("offset", 0)
                bounds_error = services_module.pagination_bounds_error(limit, offset)
                if bounds_error:
                    self._send(400, {"success": False, "status_code": 400, "terminal": True, "retryable": False, "error": bounds_error}); return
                self._send(200, services_module.APP.services.code_find_implementations(str(payload.get("root", ".")), str(payload.get("symbol", "")), path=payload.get("path"), limit=limit, offset=offset)); return
            if 'post_declaration_1' in post_route_ids:
                result = services_module.APP.services.code_find_declaration(str(payload.get("root", ".")), str(payload.get("symbol", "")), path=payload.get("path"))
                self._send(result.get("status_code", 200), result); return
            if 'post_repo_secret_scan_1' in post_route_ids:
                if "git_history" in payload:
                    self._send(400, {
                        "success": False, "error": "git_history is not supported; use scan_git_history",
                        "status_code": 400, "terminal": True, "retryable": False,
                    }); return
                scan_git_history = payload.get("scan_git_history", False)
                if not isinstance(scan_git_history, bool):
                    self._send(400, {
                        "success": False, "error": "scan_git_history must be a boolean",
                        "status_code": 400, "terminal": True, "retryable": False,
                    }); return
                result = services_module.APP.services.secret_scan(
                    str(payload.get("root", ".")), payload.get("path"),
                    scan_git_history=scan_git_history,
                    commit_depth=payload.get("commit_depth", 20),
                )
                status = result.get("status_code", 200) if isinstance(result, dict) else 200
                self._send(status if status in {400, 409, 422, 500, 503} else 200, result); return
            if 'post_repo_schema_inspect_1' in post_route_ids:
                self._send_service_result(services_module.APP.services.schema_inspect(str(payload.get("root", ".")), payload.get("db_path"))); return
            if 'post_explain_query_1' in post_route_ids:
                self._send_service_result(services_module.APP.services.explain_query(str(payload.get("root", ".")), str(payload.get("query", "")), payload.get("db_path"))); return
            if 'post_env_compat_1' in post_route_ids:
                self._send(200, services_module.APP.services.env_compat(str(payload.get("root", ".")))); return
            if 'post_coord_pubsub_publish_1' in post_route_ids:
                self._send(200, services_module.APP.services.pubsub_publish(str(payload.get("topic", "default")), payload.get("message", ""), sender=str(payload.get("publisher", payload.get("sender", "agent"))))); return
            if path == "/api/coord/pubsub_poll":
                poll_kwargs: dict[str, Any] = {}
                if "after_seq" in payload:
                    poll_kwargs["after_seq"] = int(payload["after_seq"])
                if "after_ts" in payload:
                    poll_kwargs["since_timestamp"] = float(payload["after_ts"])
                if "limit" in payload:
                    poll_kwargs["limit"] = int(payload["limit"])
                self._send(200, services_module.APP.services.pubsub_poll(str(payload.get("topic", "default")), **poll_kwargs)); return
            if path == "/api/coord/simulate_merge":
                bound_root = self._bind_root(payload.get("root"))
                if bound_root is None:
                    return
                self._send(200, services_module.APP.services.simulate_merge(bound_root, str(payload.get("source_branch", "")), target_branch=str(payload.get("target_branch", "HEAD")))); return
            if path == "/api/coord/wait_for_event":
                timeout_val = float(payload.get("timeout", 60.0))
                self._send(200, services_module.APP.services.wait_for_event(
                    str(payload.get("topic", "default")),
                    timeout=timeout_val,
                    filter_payload=payload.get("filter") or payload.get("filter_payload"),
                )); return
            if path == "/api/coord/semaphore_acquire":
                self._send(200, services_module.APP.services.semaphore_acquire(
                    name=str(payload.get("name", "")),
                    owner=str(payload.get("owner", "agent")),
                    capacity=int(payload.get("capacity", 1)),
                    ttl_seconds=None if payload.get("ttl_seconds") is None else float(payload["ttl_seconds"]),
                    purpose=str(payload.get("purpose", "")),
                    timeout=float(payload.get("timeout", 0.0)),
                )); return
            if path == "/api/coord/semaphore_release":
                self._send(200, services_module.APP.services.semaphore_release(
                    name=str(payload.get("name", "")),
                    lease_id=str(payload.get("lease_id", "")),
                    owner=str(payload.get("owner", "")),
                )); return
            if path == "/api/coord/semaphore_status":
                self._send(200, services_module.APP.services.semaphore_status(
                    name=payload.get("name"),
                )); return
            if path == "/api/coord/session_briefing":
                self._send(200, services_module.APP.services.session_briefing(
                    include=payload.get("include"),
                    root=str(payload.get("root", "")),
                )); return
            if services_module.handle_post_plan(self, payload, path, services_module.APP):
                return
            if 'post_eval_suite_1' in post_route_ids:
                self._send(200, services_module.APP.services.eval_suite(payload)); return
            if 'post_prompt_eval_1' in post_route_ids:
                self._send(200, services_module.APP.services.prompt_eval(payload)); return
            if 'post_eval_drift_1' in post_route_ids:
                self._send(200, services_module.APP.services.eval_drift(payload)); return
            if 'post_circular_dependencies_1' in post_route_ids:
                self._send(200, services_module.APP.services.circular_dependencies(str(payload.get("root", ".")), language=str(payload.get("language", "python")))); return
            if 'post_generate_types_1' in post_route_ids:
                if set(payload) - {"root", "path"}:
                    self._send(
                        400,
                        {
                            "success": False,
                            "error": "generate_types accepts only root and path",
                            "terminal": True,
                            "retryable": False,
                        },
                    )
                    return
                root = payload.get("root", ".")
                source_path = payload.get("path")
                if not isinstance(root, str) or not isinstance(source_path, str) or not source_path:
                    self._send(
                        400,
                        {
                            "success": False,
                            "error": "generate_types requires string root and nonempty path",
                            "terminal": True,
                            "retryable": False,
                        },
                    )
                    return
                self._send(200, services_module.APP.services.generate_types(root, source_path)); return
            if 'post_complexity_1' in post_route_ids:
                self._send(200, services_module.APP.services.code_complexity(
                    str(payload.get("root", ".")), path=payload.get("path"),
                    max_results=int(payload.get("max_results", 20)), include_tests=bool(payload.get("include_tests", False))
                )); return
            if 'post_api_spec_1' in post_route_ids:
                self._send(200, services_module.APP.services.extract_api_spec(str(payload.get("root", ".")), framework=payload.get("framework"))); return
            if 'post_dependency_slice_1' in post_route_ids:
                self._send_service_result(services_module.APP.services.slice_dependency_graph(str(payload.get("root", ".")), str(payload.get("symbol", "")), path=payload.get("path"), depth=int(payload.get("depth", 2)))); return
            if 'post_migration_drift_1' in post_route_ids:
                self._send(200, services_module.APP.services.migration_drift(str(payload.get("root", ".")), db_path=payload.get("db_path"))); return
            if 'post_package_audit_1' in post_route_ids:
                self._send(200, services_module.APP.services.package_audit(str(payload.get("root", ".")), lockfile_path=payload.get("lockfile_path"))); return
            if 'post_repo_structural_search_1' in post_route_ids:
                result = services_module.APP.services.structural_search(
                    str(payload.get("root", ".")), str(payload.get("pattern", "")),
                    path=payload.get("path"),
                    max_results=payload.get("max_results", 30),
                    file_offset=payload.get("offset", 0),
                    match_offset=payload.get("match_offset", 0),
                    expected_revision=payload.get("expected_revision"),
                )
                self._send_service_result(result); return
            if 'post_context_budget_1' in post_route_ids:
                self._send(200, services_module.APP.services.context_budget(str(payload.get("root", ".")), files=payload.get("files"), max_tokens=int(payload.get("max_tokens", 4000)))); return
            if 'post_ingest_document_1' in post_route_ids:
                self._send(200, services_module.APP.rag.ingest_document(root=payload["root"], workspace=payload.get("workspace", ""), content=str(payload.get("content", "")), title=str(payload.get("title", "")), metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None)); return
            if 'post_ingest_diagram_1' in post_route_ids:
                if "path" in payload:
                    self._send(400, {"success": False, "error": "ingest_diagram accepts image_path; path is not an alias", "terminal": True, "retryable": False}); return
                self._send(200, services_module.APP.rag.ingest_diagram(root=payload["root"], workspace=payload.get("workspace", ""), image_path=str(payload.get("image_path", "")), caption=str(payload.get("caption", "")), metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None)); return
            # Optional Ollama/OpenAI protocol proxy. Local AI applies
            # the same shared exact cache + single-flight before the Ollama queue.
            if 'post_chat_1' in post_route_ids:
                if payload.get("stream") is True:
                    self._send(400, {"error": "streaming is intentionally disabled through the affinity queue"}); return
                repository_root = None
                if "root" in payload:
                    if not self._bind_repository_root_payload(payload):
                        return
                    repository_root = payload.pop("root")
                result = services_module.APP.services.proxy_request(
                    path, payload, source=f"proxy:{path}", repository_root=repository_root,
                )
                self._send(200 if "error" not in result else 500, result); return

            self._send(404, {"error": "not found"})
        except services_module.QueueFullError as exc:
            admission = exc.admission if isinstance(exc.admission, dict) else {}
            reason = str(admission.get("reason") or getattr(exc, "reason", "queue_limit"))
            admission_state = str(admission.get("state") or getattr(exc, "admission_state", "rejected"))
            logger = getattr(services_module.APP, "logger", None)
            if logger is not None:
                logger.warning("queue full path=%s reason=%s admission_state=%s", path, reason, admission_state)
            self._send(429, {
                "success": False,
                "error": str(exc),
                "status_code": 429,
                "error_code": reason,
                "admission_state": admission_state,
                "retryable": bool(exc.retryable),
                "terminal": bool(exc.terminal),
            })
        except services_module.ModelUnavailableError as exc:
            logger = getattr(services_module.APP, "logger", None)
            if logger is not None:
                logger.warning("model unavailable path=%s error=%s", path, exc)
            self._send(503, {"success": False, "error": str(exc), "status_code": 503, "retryable": True})
        except (ValueError, TypeError, services_module.RequestBodyError) as exc:
            logger = getattr(services_module.APP, "logger", None)
            if logger is not None:
                logger.warning("invalid request payload path=%s error=%s", path, exc)
            self._send(400, {"success": False, "error": str(exc), "status_code": 400, "terminal": True, "retryable": False})
        except KeyError as exc:
            logger = getattr(services_module.APP, "logger", None)
            if logger is not None:
                logger.warning("resource not found path=%s key=%s", path, exc)
            self._send(404, {"success": False, "error": str(exc), "status_code": 404, "terminal": True, "retryable": False})
        except PermissionError:
            logger = getattr(services_module.APP, "logger", None)
            if logger is not None:
                logger.warning("permission denied path=%s", path)
            self._send(403, {
                "success": False,
                "error": "permission denied",
                "error_code": "permission_denied",
                "status_code": 403,
                "terminal": True,
                "retryable": False,
            })
        except Exception as exc:
            if services_module._is_client_disconnect(exc):
                self._finish_debug_trace(499, {"success": False, "terminal": True}, error="client disconnected")
                self._close_trace_context()
                return
            elif services_module.is_busy_error(exc):
                self._send_database_locked()
                return
            logger = getattr(services_module.APP, "logger", None)
            if logger is not None:
                services_module._log_http_failure(logger, "POST", path, exc)
            try:
                self._send(500, {
                    "success": False,
                    "error": "internal server error",
                    "error_code": "internal_error",
                    "terminal": True,
                    "retryable": False,
                })
            except Exception:
                pass

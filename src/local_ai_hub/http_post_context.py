from __future__ import annotations

from typing import Any


def handle_context_pack(self: Any, path: str, payload: dict[str, Any]) -> None:
    from . import http_server as services_module
    context_request_started = services_module.time.perf_counter()

    def attach_context_phase_timings(
        result: Any, preparation_ms: float, retrieval_ms: float,
    ) -> Any:
        if not isinstance(result, dict):
            return result
        timings = result.get("phase_timings_ms")
        timings = dict(timings) if isinstance(timings, dict) else {}
        total_ms = round((services_module.time.perf_counter() - context_request_started) * 1000.0, 1)
        timings.update({
            "request_preparation_ms": preparation_ms,
            "context_retrieval_ms": retrieval_ms,
            "post_retrieval_ms": max(0.0, round(total_ms - preparation_ms - retrieval_ms, 1)),
            "total_ms": total_ms,
        })
        result["phase_timings_ms"] = timings
        return result

    root = str(payload.get("root", ".")); query_text = str(payload.get("query", ""))
    configured_tokens = services_module.APP.config.get("token_saving", {}).get("default_repo_context_tokens", 8000)
    raw_max_tokens = payload.get("max_tokens", payload.get("token_budget", configured_tokens))
    raw_token_budget = payload.get("token_budget")
    if isinstance(raw_max_tokens, bool) or not isinstance(raw_max_tokens, int):
        self._send(400, {"success": False, "terminal": True, "retryable": False, "error": "max_tokens must be an integer"}); return
    if raw_token_budget is not None:
        if isinstance(raw_token_budget, bool) or not isinstance(raw_token_budget, int):
            self._send(400, {"success": False, "terminal": True, "retryable": False, "error": "token_budget must be an integer"}); return
        if raw_max_tokens and raw_token_budget and raw_max_tokens != raw_token_budget:
            self._send(400, {"success": False, "terminal": True, "retryable": False, "error": "token_budget and max_tokens must match when both are provided"}); return
        raw_max_tokens = raw_token_budget or raw_max_tokens
    if raw_max_tokens < 0:
        self._send(400, {"success": False, "terminal": True, "retryable": False, "error": "max_tokens must be non-negative"}); return
    if raw_max_tokens and not 128 <= raw_max_tokens <= 20_000:
        self._send(400, {"success": False, "terminal": True, "retryable": False, "error": "max_tokens must be 0 or between 128 and 20000"}); return
    max_tokens = raw_max_tokens or max(128, min(int(configured_tokens or 8000), 20_000))
    mode = self._context_retrieval_mode(payload)
    if mode is None:
        self._send(400, {"success": False, "terminal": True, "retryable": False, "error": "context mode must be adaptive, full or fast"}); return
    if "project_config_digest" in payload:
        self._send(400, {
            "success": False, "terminal": True, "retryable": False,
            "error": "project_config_digest is server-resolved",
        }); return
    path_control_fields = ("path_hints", "directory_hints", "exclude_paths", "force_include_paths")
    path_controls_requested = any(field in payload for field in path_control_fields)
    if path_controls_requested and mode != "adaptive":
        self._send(400, {
            "success": False, "terminal": True, "retryable": False,
            "error": "path controls require adaptive context mode",
        }); return
    path_controls = None
    project_config_digest = ""
    project_retrieval_weights = None
    project_memory_revision = ""
    if path_controls_requested:
        for field in path_control_fields:
            if payload.get(field) is not None and not isinstance(payload.get(field), list):
                self._send(400, {
                    "success": False, "terminal": True, "retryable": False,
                    "error": f"{field} must be a list",
                }); return
        from .project_config import resolve_project_context
        from .state_paths import configured_state_dir
        project_context = resolve_project_context(
            root, configured_state_dir(services_module.APP.config, create=False)
        )
        project_config_digest = project_context.config_digest
        from .agent_consistency import ConsistencyRequest
        try:
            path_controls = ConsistencyRequest(
                root=root,
                path_hints=payload.get("path_hints") or (),
                directory_hints=payload.get("directory_hints") or (),
                exclude_paths=payload.get("exclude_paths") or (),
                force_include_paths=payload.get("force_include_paths") or (),
                project_config_digest=project_config_digest,
            )
        except (TypeError, ValueError) as exc:
            self._send(400, {
                "success": False, "terminal": True, "retryable": False,
                "error": str(exc),
            }); return
        project_retrieval_weights = dict(project_context.settings.retrieval_weights)
        from .task_context import _project_context_hint_groups
        try:
            project_root = services_module.Path(root).expanduser().resolve(strict=False)
            pinned_hints, entry_hints, saved_hints = _project_context_hint_groups(
                project_context,
                project_root=project_root,
                repository_revision=(
                    payload.get("repository_revision")
                    if isinstance(payload.get("repository_revision"), str)
                    else ""
                ),
                config_digest=project_config_digest,
            )
            path_controls = ConsistencyRequest(
                root=root,
                path_hints=(
                    *pinned_hints,
                    *entry_hints,
                    *path_controls.path_hints,
                    *saved_hints,
                ),
                directory_hints=path_controls.directory_hints,
                exclude_paths=path_controls.exclude_paths,
                force_include_paths=path_controls.force_include_paths,
                project_config_digest=project_config_digest,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            self._send(400, {
                "success": False, "terminal": True, "retryable": False,
                "error": str(exc),
            }); return
        try:
            project_memory_revision = services_module.APP.services._adaptive_memory_revision(ConsistencyRequest(root=root, query=query_text, workspace=str(payload.get("workspace") or ""), token_budget=max_tokens))
        except (OSError, RuntimeError, TypeError, ValueError, services_module.sqlite3.Error) as exc:
            self._send(200, {
                "success": False,
                "terminal": True,
                "retryable": False,
                "stop_code": "context_memory_revision_unavailable",
                "error": f"context memory revision unavailable: {type(exc).__name__}",
                "context": "",
                "evidence": [],
                "query": query_text,
                "delivery_mode": mode,
            }); return
    auto_injected_task = False
    guarded = payload.get("guarded", False)
    if not isinstance(guarded, bool):
        self._send(400, {"success": False, "terminal": True, "retryable": False, "error": "guarded must be boolean"}); return
    guarded_requested = (
        bool(guarded)
        or bool(str(payload.get("task_id", "")).strip())
        or bool(str(payload.get("phase", "")).strip())
        or bool(str(payload.get("session_id", "")).strip())
    )
    if not guarded_requested:
        guard_fields = (
            "focus", "preload_profile", "changed_paths", "base", "staged", "since_hash",
            "approval", "override_reason", "token_budget", "session_id", "clone_id",
            "worktree_id", "branch", "repository_id", "repository_revision", "include_diagnostics",
        )
        unexpected = next((field for field in guard_fields if field in payload), None)
        if unexpected is not None:
            self._send(400, {"success": False, "terminal": True, "retryable": False, "error": f"guard-related fields require guarded=true, task_id, or phase: {unexpected}"}); return
    if guarded_requested:
        if payload.get("focus") is not None and not isinstance(payload.get("focus"), list):
            self._send(400, {"success": False, "terminal": True, "retryable": False, "error": "focus must be a list"}); return
        if payload.get("changed_paths") is not None and not isinstance(payload.get("changed_paths"), list):
            self._send(400, {"success": False, "terminal": True, "retryable": False, "error": "changed_paths must be a list"}); return
        for field, limit in (("focus", 16), ("changed_paths", 64)):
            values = payload.get(field)
            if values is not None and len(values) > limit:
                self._send(400, {"success": False, "terminal": True, "retryable": False, "error": f"{field} exceeds maximum of {limit} items"}); return
            if values is not None and any(not isinstance(item, str) for item in values):
                self._send(400, {"success": False, "terminal": True, "retryable": False, "error": f"{field} items must be strings"}); return
        if payload.get("staged") is not None and not isinstance(payload.get("staged"), bool):
            self._send(400, {"success": False, "terminal": True, "retryable": False, "error": "staged must be boolean"}); return
        for field in ("task_id", "session_id", "phase", "query", "preload_profile", "base", "since_hash", "override_reason"):
            if payload.get(field) is not None and not isinstance(payload.get(field), str):
                self._send(400, {"success": False, "terminal": True, "retryable": False, "error": f"{field} must be string"}); return
        for field in ("clone_id", "worktree_id", "branch", "repository_id", "repository_revision"):
            if payload.get(field) is not None and not isinstance(payload.get(field), str):
                self._send(400, {"success": False, "terminal": True, "retryable": False, "error": f"{field} must be string"}); return
        if payload.get("include_diagnostics") is not None and not isinstance(payload.get("include_diagnostics"), bool):
            self._send(400, {"success": False, "terminal": True, "retryable": False, "error": "include_diagnostics must be boolean"}); return
        from .agent_consistency import ConsistencyRequest, normalize_context_phase
        try:
            phase = normalize_context_phase(payload.get("phase", ""))
        except ValueError as exc:
            self._send(400, {"success": False, "terminal": True, "retryable": False, "error": str(exc)}); return
        approval = payload.get("approval", "")
        if not isinstance(approval, (bool, str)):
            self._send(400, {"success": False, "terminal": True, "retryable": False, "error": "approval must be boolean or string"}); return
        focus_values = tuple(str(item).strip() for item in (payload.get("focus") or []) if str(item).strip())
        guarded_query = query_text.strip() or " ".join(focus_values[:8]).strip()
        if not guarded_query:
            guarded_query = f"repository context {str(payload.get('phase', '')).strip() or 'unspecified phase'}"

        request = ConsistencyRequest(root=root, task_id=str(payload.get("task_id", "")), session_id=str(payload.get("session_id", "")), query=guarded_query, phase=phase, focus=focus_values, workspace=str(payload.get("workspace", "")), preload_profile=str(payload.get("preload_profile", "")), token_budget=max_tokens, changed_paths=tuple(str(item) for item in (payload.get("changed_paths") or [])), base=str(payload.get("base", "HEAD")), staged=bool(payload.get("staged", False)), override_reason=str(payload.get("override_reason", "")), approval=approval, path_hints=path_controls.path_hints if path_controls else (), directory_hints=path_controls.directory_hints if path_controls else (), exclude_paths=path_controls.exclude_paths if path_controls else (), force_include_paths=path_controls.force_include_paths if path_controls else (), project_config_digest=project_config_digest)
        has_task_id = bool(str(payload.get("task_id", "")).strip())
        if guarded_requested and has_task_id:
            preflight = services_module.APP.services.preflight_guard_task_state(request)
            if preflight is not None:
                status_code = int(preflight.get("status_code", 503))
                response = {key: value for key, value in preflight.items() if key != "status_code"}
                self._send(status_code, response); return
        context_preparation_ms = round(
            (services_module.time.perf_counter() - context_request_started) * 1000.0, 1,
        )
        context_retrieval_started = services_module.time.perf_counter()
        try:
            result = services_module.APP.services.adaptive_context_pack(
                request,
                mode=mode,
                since_hash=str(payload.get("since_hash", "")),
            )
            if isinstance(result, dict) and result.get("success") is True:
                try:
                    capture = services_module.APP.capture_laya_context_source_from_context(
                        request,
                        result,
                    )
                    if capture.get("status") not in {"queued", "disabled"}:
                        services_module.APP.logger.debug(
                            "Laya shadow capture skipped: %s",
                            capture.get("reason", capture.get("status", "unknown")),
                        )
                except Exception as exc:
                    services_module.APP.logger.warning(
                        "Laya shadow capture scheduling failed: %s",
                        type(exc).__name__,
                    )
        except Exception as exc:
            result = {
                "success": False,
                "terminal": False,
                "retryable": True,
                "degraded": True,
                "degraded_reason": "repository_context_unavailable",
                "error": f"repository context unavailable: {type(exc).__name__}",
            }
        context_retrieval_ms = round(
            (services_module.time.perf_counter() - context_retrieval_started) * 1000.0, 1,
        )
        repository_failed = isinstance(result, dict) and result.get("success") is False
        if repository_failed and (not (guarded_requested and has_task_id) or auto_injected_task):
            status_code = 503 if result.get("retryable") is True else 500
            self._send(status_code, result); return
        if guarded_requested and has_task_id and not getattr(services_module.APP, "agent_context", None):
            if not auto_injected_task:
                self._send(503, {
                    "success": False, "terminal": False, "retryable": True,
                    "stop_code": "context_task_context_unavailable",
                    "error": "task context compiler unavailable",
                }); return
        if guarded_requested and has_task_id and getattr(services_module.APP, "agent_context", None):
            task_request_payload = {
                "task_id": payload.get("task_id", ""),
                "session_id": payload.get("session_id", ""),
                "token_budget": max_tokens,
                "root": root,
                "phase": payload.get("phase", ""),
                "focus": payload.get("focus") or [],
                "preload_profile": payload.get("preload_profile", ""),
                "changed_paths": payload.get("changed_paths") or [],
                "repository_revision": payload.get("repository_revision", payload.get("repo_revision", "")),
                "since_hash": payload.get("task_since_hash", ""),
                "_scoped_task_only": True,
                "clone_id": payload.get("clone_id", ""),
                "worktree_id": payload.get("worktree_id", ""),
                "branch": payload.get("branch", ""),
                "repository_id": payload.get("repository_id", ""),
                "include_diagnostics": payload.get("include_diagnostics", False),
            }
            task_request = services_module.build_context_request(
                task_request_payload,
                project_context=services_module._trusted_project_context(root),
            )
            unified = None
            try:
                compiled = services_module.APP.agent_context.compile(task_request)
                unified = services_module.compose_task_context(
                    task_id=task_request.task_id,
                    compiled=compiled,
                    repository=result if isinstance(result, dict) else {"success": False, "error": "repository context response must be an object"},
                    token_budget=task_request.token_budget,
                )
            except Exception as exc:
                if not auto_injected_task:
                    self._send(503, {
                        "success": False, "terminal": False, "retryable": True,
                        "stop_code": "context_task_context_unavailable",
                        "error": f"task context receipt unavailable: {type(exc).__name__}",
                    }); return
            if unified is not None:
                provenance = unified.get("provenance") if isinstance(unified, dict) else None
                receipt_complete = bool(
                    isinstance(unified, dict)
                    and unified.get("success") is True
                    and unified.get("complete") is True
                    and isinstance(unified.get("text"), str)
                    and str(unified.get("context_id") or "").strip()
                    and str(unified.get("etag") or "").strip()
                    and isinstance(provenance, dict)
                    and str(provenance.get("repository_revision") or "").strip()
                    and provenance.get("status") == "success"
                )
                if not receipt_complete:
                    if repository_failed and not auto_injected_task:
                        if isinstance(result, dict):
                            result.setdefault("stop_code", "context_task_context_incomplete")
                            if isinstance(unified, dict) and isinstance(unified.get("text"), str) and unified["text"].strip():
                                result["task_context"] = unified
                        status_code = 503 if isinstance(result, dict) and result.get("retryable") is True else 500
                        self._send(status_code, result); return
                    if not auto_injected_task:
                        self._send(503, {
                            "success": False, "terminal": True, "retryable": False,
                            "stop_code": "context_task_context_incomplete",
                            "error": "task context receipt is missing, stale, or incomplete",
                            "task_context": unified if isinstance(unified, dict) else {},
                        }); return
                else:
                    if isinstance(result, dict):
                        from .context_delivery import persist_compiled_context
                        try:
                            context_artifact_id = persist_compiled_context(
                                services_module.APP.artifacts, unified, root=root,
                                coordination_id=task_request.coordination_id,
                                session_id=task_request.session_id,
                            )
                            unified["artifact_id"] = context_artifact_id
                            result["task_context_artifact_id"] = context_artifact_id
                        except Exception:
                            unified["artifact_unavailable"] = True
                        unified.pop("_omitted_task_goal", None)
                        result["task_context"] = unified
                        result["task_context_id"] = unified["context_id"]
                        if auto_injected_task:
                            result["task_id"] = payload.get("task_id", "")
        if isinstance(result, dict) and "query" not in result:
            result["query"] = guarded_query
        attach_context_phase_timings(
            result, context_preparation_ms, context_retrieval_ms,
        )
        self._send(200, result); return
    if mode == "fast":
        context_preparation_ms = round(
            (services_module.time.perf_counter() - context_request_started) * 1000.0, 1,
        )
        context_retrieval_started = services_module.time.perf_counter()
        from .agent_context import ContextRequest
        result = services_module.APP.services.fast_context(
            ContextRequest(task_id=query_text, root=root, token_budget=max_tokens, phase="fast")
        )
        context_retrieval_ms = round(
            (services_module.time.perf_counter() - context_retrieval_started) * 1000.0, 1,
        )
        if isinstance(result, dict):
            result["delivery_mode"] = mode
        attach_context_phase_timings(
            result, context_preparation_ms, context_retrieval_ms,
        )
        self._send(200, result); return
    context_preparation_ms = round(
        (services_module.time.perf_counter() - context_request_started) * 1000.0, 1,
    )
    context_retrieval_started = services_module.time.perf_counter()
    result = services_module.APP.services._hybrid_context(
        root, query_text,
        workspace=payload.get("workspace"), max_tokens=max_tokens,
        quality_first=mode == "adaptive",
        context_identity={
            "path_hints": path_controls.path_hints if path_controls else (),
            "directory_hints": path_controls.directory_hints if path_controls else (),
            "exclude_paths": path_controls.exclude_paths if path_controls else (),
            "force_include_paths": path_controls.force_include_paths if path_controls else (),
            "project_config_digest": project_config_digest,
            "memory_revision": project_memory_revision,
        },
        path_hints=path_controls.path_hints if path_controls else (),
        directory_hints=path_controls.directory_hints if path_controls else (),
        exclude_paths=path_controls.exclude_paths if path_controls else (),
        force_include_paths=path_controls.force_include_paths if path_controls else (),
        retrieval_weights=project_retrieval_weights,
    )
    context_retrieval_ms = round(
        (services_module.time.perf_counter() - context_retrieval_started) * 1000.0, 1,
    )
    if isinstance(result, dict):
        result["delivery_mode"] = mode
    attach_context_phase_timings(
        result, context_preparation_ms, context_retrieval_ms,
    )
    self._send(200, result); return

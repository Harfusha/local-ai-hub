from __future__ import annotations

from .http_server_proxy import services_module


class HttpGetMixin:
    def do_GET(self) -> None:
        self._handler_execution_started = services_module.time.perf_counter()
        parsed = services_module.urlparse(self.path)
        path = parsed.path
        if not self._reject_identity_fields(query_params := services_module.parse_qs(parsed.query, keep_blank_values=True)):
            return
        if "root" in query_params and query_params["root"]:
            self._request_root = str(query_params["root"][0])
        if path == "/health":
            self._handle_health_route(path)
            return
        if path == "/ready":
            self._handle_health_route(path)
            return
        if path.rstrip("/") in {"", "/dashboard", "/favicon.ico"}:
            self._send(404, {"success": False, "error": "Web UI removed; use Local AI Hub Desktop."})
            return
        if services_module.APP is None:
            self._send(503, {"success": False, "error": "hub starting up; please retry", "status_code": 503, "retryable": True})
            return
        # Loopback mode reads expose only local
        # runtime state, while mode mutations remain authenticated.
        if path == "/api/mode" and not services_module._is_loopback_peer(self):
            self._send(403, {"success": False, "error": "local_control_requires_loopback"})
            return
        elif path == "/api/mode":
            if not self._validate_host_and_origin():
                return
        elif not self._require_authorized():
            return
        if path == "/api/updates":
            self._handle_dashboard_updates()
            return
        mode_error = services_module._http_mode_gate_error("GET", path)
        if mode_error is not None:
            self._send(503, mode_error)
            return
        self._begin_trace(path)
        query = services_module.parse_qs(parsed.query)
        trace_store = getattr(services_module.APP, "debug_traces", None) if services_module.APP is not None else None
        trace_id = str(getattr(self, "_debug_trace_id", "") or "")
        detail_enabled = services_module.detailed_diagnostics_enabled(getattr(services_module.APP, "config", {}), store=trace_store)
        if not detail_enabled and services_module.diagnostic_http_operation("GET", path):
            self._send(409, services_module.diagnostics_disabled_response())
            return
        if not detail_enabled and path in {"/api/status", "/api/live/status"}:
            full_requested = (query.get("detail") or [""])[0] == "full"
            full_live_requested = path == "/api/live/status" and "light" in query and (
                str(query["light"][0]).lower() not in {"1", "true", "yes"}
            )
            if full_requested or full_live_requested:
                self._send(409, services_module.diagnostics_disabled_response())
                return
        if not detail_enabled:
            if path == "/api/debug-traces":
                self._send(200, {"success": True, "enabled": False, "items": [], "total": 0})
                return
            if path.startswith("/api/debug-traces/") or path in {"/api/telemetry/timeline", "/api/logs/tail"}:
                self._send(409, {
                    "success": False, "error_code": "detailed_diagnostics_disabled",
                    "error": "Enable detailed diagnostics in desktop settings to read diagnostic detail.",
                    "terminal": True, "retryable": False,
                })
                return
        if trace_store is not None and trace_id and query:
            try:
                trace_store.update(trace_id, request={"query": query})
            except Exception:
                pass
        allowed_agent_state_get = {
            "/api/agent-state/memory",
            "/api/agent-state/tasks",
            "/api/agent-state/incidents",
            "/api/agent-state/events",
            "/api/agent-state/events/stream",
            "/api/agent-state/blackboard",
            "/api/agent-state/swarm",
        }
        if path.startswith("/api/agent-state/") and path not in allowed_agent_state_get and not path.startswith("/api/agent-state/swarm/"):
            self._send(403, {"success": False, "error": "agent_state route has no root-scoped access contract", "terminal": True, "retryable": False}); return
        if path == "/api/agent-state/memory" and not self._bind_memory_query(query):
            return
        if path in {"/api/agent-state/events", "/api/agent-state/events/stream"}:
            if services_module.APP is None or not getattr(services_module.APP, "agent_state", None) or not services_module.APP.agent_state.enabled:
                self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False})
                return
            if not self._bind_task_event_query(query):
                return
        if path == "/api/agent-state/blackboard" and not self._bind_task_board_query(query):
            return
        if path == "/api/agent-state/swarm" or path.startswith("/api/agent-state/swarm/"):
            if not self._bind_swarm_query(query):
                return
        root_scoped_repo_get_paths = {
            "/api/git/status", "/api/git/diff", "/api/git/history_search", "/api/git/synthesize_commit",
            "/api/hotspots", "/api/symbol_callgraph", "/api/audit_dependencies", "/api/refactor_impact", "/api/test_matrix",
            "/api/resolve_imports", "/api/security_audit", "/api/search",
            "/api/preprocess", "/api/preprocess/status", "/api/coord/worktrees", "/api/project/config",
        }
        if (
            path.startswith("/api/repo/")
            or path.startswith("/api/code/")
            or path in root_scoped_repo_get_paths
        ) and not self._bind_repository_root_query(query):
            return
        if path == "/api/cross_project_graph" and not self._bind_multi_repository_query(query):
            return
        if path in {"/api/agent-state/tasks", "/api/agent-state/incidents"}:
            roots = query.get("root", [])
            if roots and roots[0] not in ("", "all", "__all__"):
                if not self._bind_repository_root_query(query):
                    return
            else:
                query["root"] = [""]
        try:
            get_handler_name = services_module.select_get_handler(path)
            if get_handler_name is not None:
                getattr(self, get_handler_name)(query)
                return
            if path == "/api/mode":
                try:
                    mode_api = services_module._operational_mode_api()
                    jobs_path = getattr(getattr(services_module.APP, "async_jobs", None), "path", None)
                    config = getattr(services_module.APP, "config", {})
                    state_dir = services_module.Path(jobs_path).parent if jobs_path is not None else config.get("server", {}).get("state_dir", "state")
                    snapshot = mode_api.load_operational_mode(state_dir=state_dir)
                except Exception:
                    self._send(503, {"success": False, "error": "operational mode state unavailable", "retryable": True})
                    return
                response = {
                    "success": True,
                    "mode": str(getattr(snapshot, "mode", "maintenance")),
                    "revision": int(getattr(snapshot, "revision", -1)),
                    "degraded": bool(getattr(snapshot, "degraded", True)),
                }
                if response["mode"] == "preprocessing":
                    from .operational_mode import preprocessing_mode_ready
                    response["preprocessing_ready"] = preprocessing_mode_ready(state_dir, snapshot)
                if response["mode"] == "gaming":
                    unload_status = services_module._get_mode_unload_status(services_module.APP, response["revision"])
                    if unload_status is not None:
                        response["runtime_unload"] = services_module._public_gaming_unload_status(unload_status)
                if response["degraded"]:
                    response["error"] = "operational mode state is invalid"
                self._send(200, response); return
            if path == "/api/status":
                self._handle_api_status(path, query, detail_enabled)
                return
            if path == "/api/repair-priorities":
                self._handle_repair_priorities(path, query)
                return
            if path == "/api/agent-state/tasks":
                if not getattr(services_module.APP, "agent_tasks", None) or not services_module.APP.agent_tasks.state_store.enabled:
                    self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
                request_root = (query.get("root") or [""])[0]
                if request_root in ("all", "__all__"):
                    request_root = ""
                task_id = (query.get("task_id") or [""])[0]
                if task_id:
                    task = self._request_task(task_id, request_root) if request_root else services_module.APP.agent_tasks.get(task_id)
                    if task is None:
                        self._send(404, {"success": False, "error": "task not found", "terminal": True, "retryable": False}); return
                    self._send(200, {"success": True, "task": task.to_dict()}); return
                status_filter = None
                if query.get("status"):
                    try:
                        status_filter = services_module.TaskStatus(str(query.get("status")[0]).strip().lower())
                    except ValueError:
                        pass
                try:
                    limit = int((query.get("limit") or [20])[0])
                    offset = int((query.get("offset") or [0])[0])
                    if not 1 <= limit <= 1000:
                        raise ValueError("limit must be between 1 and 1000")
                    if not 0 <= offset <= (1 << 31) - 1:
                        raise ValueError("offset must be between 0 and 2147483647")
                except (TypeError, ValueError) as exc:
                    self._send(400, {
                        "success": False,
                        "error": str(exc) or "limit and offset must be integers",
                        "terminal": True,
                        "retryable": False,
                    }); return
                include_stale = str((query.get("include_stale") or ["false"])[0]).lower() in ("true", "1", "yes")
                task_query = (query.get("query") or [""])[0]
                if request_root:
                    from .agent_tasks import _task_matches_scope
                    from .http_scoped_tasks import page_scoped_tasks
                    page = page_scoped_tasks(
                        services_module.APP.agent_tasks.list_tasks,
                        lambda task: _task_matches_scope(task, request_root),
                        status=status_filter,
                        limit=limit,
                        offset=offset,
                        include_stale=include_stale,
                        query=task_query,
                        repo_root=request_root,
                    )
                    # The query root was authorized before scanning. Revalidate the returned page before disclosure.
                    if any(not self._task_matches_request(task, request_root) for task in page["tasks"]):
                        self._send(409, {
                            "success": False, "error": "repository scope changed during task paging",
                            "terminal": True, "retryable": False,
                        }); return
                    response = {
                        "success": True,
                        "tasks": [task.to_dict() for task in page["tasks"]],
                        "total_count": services_module.APP.agent_tasks.count(repo_root=request_root),
                        "active_count": services_module.APP.agent_tasks.count(services_module.TaskStatus.ACTIVE, repo_root=request_root),
                        "global_total_count": services_module.APP.agent_tasks.count(),
                        "global_active_count": services_module.APP.agent_tasks.count(services_module.TaskStatus.ACTIVE),
                        "count_scope": "repository",
                        "root": request_root,
                        "offset": offset,
                        "limit": limit,
                        "next_offset": page["next_offset"],
                        "has_more": page["has_more"],
                        "query_truncated": page["incomplete"],
                    }
                else:
                    task_page = services_module.APP.agent_tasks.list_tasks(
                        status=status_filter,
                        limit=limit + 1,
                        offset=offset,
                        include_stale=include_stale,
                        query=task_query,
                    )
                    has_more = len(task_page.tasks) > limit
                    response = {
                        "success": True,
                        "tasks": [t.to_dict() for t in task_page.tasks[:limit] if not request_root or self._task_matches_request(t, request_root)],
                        "total_count": services_module.APP.agent_tasks.count(),
                        "active_count": services_module.APP.agent_tasks.count(services_module.TaskStatus.ACTIVE),
                        "offset": offset,
                        "limit": limit,
                        "next_offset": offset + min(len(task_page.tasks), limit),
                        "has_more": has_more,
                    }
                    if task_page.query_truncated:
                        response["query_truncated"] = True
                self._send(200, response); return
            if path == "/api/agent-state/incidents":
                if not getattr(services_module.APP, "agent_incidents", None) or not services_module.APP.agent_incidents.state_store.enabled:
                    self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
                limit = int((query.get("limit") or [100])[0])
                resolved_raw = (query.get("resolved") or [None])[0]
                status_raw = (query.get("status") or [None])[0]
                request_root = (query.get("root") or [""])[0]
                if request_root in ("all", "__all__"):
                    request_root = ""
                if request_root:
                    incidents = services_module.APP.agent_incidents.list_incidents(
                        resolved=resolved_raw, limit=limit, status=status_raw, root=request_root,
                    )
                else:
                    incidents = services_module.APP.agent_incidents.list_incidents(resolved=resolved_raw, limit=limit, status=status_raw)
                self._send(200, {"success": True, "incidents": [i.to_dict() if hasattr(i, "to_dict") else i for i in incidents]}); return
            if path == "/api/agent-state/memory":
                if not getattr(services_module.APP, "agent_memory", None) or not services_module.APP.agent_memory.state_store.enabled:
                    self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
                rec_id = (query.get("record_id") or [""])[0]
                if rec_id:
                    scope_raw = (query.get("scope") or [None])[0]
                    scope_val = services_module._parse_memory_scope(scope_raw)
                    scope_id_val = (query.get("scope_id") or [None])[0]
                    requested_root = (query.get("root") or [None])[0]
                    project_identity = self._memory_project_identity(requested_root)
                    if requested_root and project_identity is None:
                        self._send(400, {"success": False, "error": "memory project identity could not be resolved", "terminal": True, "retryable": False}); return
                    root_val, repository_id_val = project_identity or (None, None)
                    task_id_val = (query.get("task_id") or [None])[0]
                    session_id_val = (query.get("session_id") or [None])[0]
                    clone_id_val = (query.get("clone_id") or [None])[0]
                    worktree_id_val = (query.get("worktree_id") or [None])[0]
                    branch_val = (query.get("branch") or [None])[0]
                    scope_val, scope_id_val, ambiguous_scope = services_module._resolve_memory_scope(
                        scope_val,
                        scope_id=scope_id_val,
                        root=root_val,
                        repository_id=repository_id_val,
                        task_id=task_id_val,
                        session_id=session_id_val,
                        clone_id=clone_id_val,
                        worktree_id=worktree_id_val,
                        branch=branch_val,
                    )
                    if ambiguous_scope:
                        self._send(400, {"success": False, "error": "ambiguous memory scope identity", "terminal": True, "retryable": False}); return
                    if scope_val is None:
                        scope_val = services_module.AgentScope.GLOBAL
                    scope_id_val = self._bound_memory_scope_id(scope_val, scope_id_val, task_id_val)
                    if scope_val is services_module.AgentScope.TASK:
                        task_id_val = scope_id_val
                    elif scope_val is services_module.AgentScope.SESSION:
                        session_id_val = scope_id_val
                    matches = services_module.APP.agent_memory.find(
                            record_id=rec_id,
                            scope=scope_val,
                            scope_id=str(scope_id_val) if scope_id_val is not None else None,
                            root=str(root_val) if root_val else None,
                            repository_id=str(repository_id_val) if repository_id_val else None,
                            task_id=str(task_id_val) if task_id_val else None,
                            session_id=str(session_id_val) if session_id_val else None,
                            clone_id=str(clone_id_val) if clone_id_val else None,
                            worktree_id=str(worktree_id_val) if worktree_id_val else None,
                            branch=str(branch_val) if branch_val else None,
                            limit=1,
                    )
                    rec = matches[0] if matches else None
                    if not rec:
                        self._send(404, {"success": False, "error": "memory record not found", "terminal": True, "retryable": False}); return
                    self._send(200, {"success": True, "record": rec.to_dict()}); return
                scope_raw = (query.get("scope") or [None])[0]
                scope_val = services_module._parse_memory_scope(scope_raw)
                key_val = (query.get("key") or [None])[0]
                query_val = (query.get("query") or [None])[0]
                status_raw = (query.get("status") or [None])[0]
                status_val = None
                if status_raw:
                    try:
                        status_val = services_module.MemoryStatus(str(status_raw).lower())
                    except ValueError:
                        pass
                limit_val = services_module._memory_query_limit((query.get("limit") or [20])[0])
                scope_id_val = (query.get("scope_id") or [None])[0]
                requested_root = (query.get("root") or [None])[0]
                project_identity = self._memory_project_identity(requested_root)
                if requested_root and project_identity is None:
                    self._send(400, {"success": False, "error": "memory project identity could not be resolved", "terminal": True, "retryable": False}); return
                root_val, repository_id_val = project_identity or (None, None)
                task_id_val = (query.get("task_id") or [None])[0]
                session_id_val = (query.get("session_id") or [None])[0]
                clone_id_val = (query.get("clone_id") or [None])[0]
                worktree_id_val = (query.get("worktree_id") or [None])[0]
                branch_val = (query.get("branch") or [None])[0]
                if scope_val not in (None, services_module.AgentScope.GLOBAL) and not services_module._memory_lookup_has_identity(
                    scope_id_val, root_val, repository_id_val, task_id_val,
                    session_id_val, clone_id_val, worktree_id_val, branch_val,
                ):
                    self._send(400, {"success": False, "error": "memory lookup requires explicit root or identity", "terminal": True, "retryable": False}); return
                scope_val, scope_id_val, ambiguous_scope = services_module._resolve_memory_scope(
                    scope_val,
                    scope_id=scope_id_val,
                    root=root_val,
                    repository_id=repository_id_val,
                    task_id=task_id_val,
                    session_id=session_id_val,
                    clone_id=clone_id_val,
                    worktree_id=worktree_id_val,
                    branch=branch_val,
                )
                if ambiguous_scope:
                    self._send(400, {"success": False, "error": "ambiguous memory scope identity", "terminal": True, "retryable": False}); return
                scope_id_val = self._bound_memory_scope_id(scope_val, scope_id_val, task_id_val)
                if scope_val is services_module.AgentScope.TASK:
                    task_id_val = scope_id_val
                elif scope_val is services_module.AgentScope.SESSION:
                    session_id_val = scope_id_val
                include_all_scopes = str((query.get("all") or ["false"])[0]).lower() in ("true", "1", "yes") or (not root_val and not scope_raw)
                records = services_module.APP.agent_memory.find(
                    scope=scope_val if scope_raw is not None else None,
                    scope_id=str(scope_id_val) if scope_id_val is not None else None,
                    root=str(root_val) if root_val else None,
                    repository_id=str(repository_id_val) if repository_id_val else None,
                    task_id=str(task_id_val) if task_id_val else None,
                    session_id=str(session_id_val) if session_id_val else (str(scope_id_val) if (scope_raw is None and scope_val == services_module.AgentScope.SESSION) else None),
                    clone_id=str(clone_id_val) if clone_id_val else None,
                    worktree_id=str(worktree_id_val) if worktree_id_val else None,
                    branch=str(branch_val) if branch_val else None,
                    key=key_val,
                    query=query_val,
                    status=status_val,
                    limit=limit_val,
                    include_all_scopes=include_all_scopes,
                )
                self._send(200, {"success": True, "records": [r.to_dict() for r in records]}); return
            if path == "/api/agent-state/events":
                agent_state = getattr(services_module.APP, "agent_state", None)
                stream_id = (query.get("stream_id") or [""])[0]
                after_seq = (query.get("after_seq") or [0])[0]
                through_seq = (query.get("through_seq") or [None])[0]
                limit = (query.get("limit") or [100])[0]
                try:
                    after_seq = max(0, min(int(after_seq), services_module.MAX_EVENT_SEQUENCE))
                except (TypeError, ValueError, OverflowError):
                    after_seq = 0
                if agent_state is None:
                    self._send(403, {
                        "success": False, "events": [], "next_seq": 0,
                        "first_retained_seq": 0, "last_seq": 0, "has_more": False,
                        "gap_ranges": [], "cursor_reset": False,
                        "error": {"code": "agent_state_disabled", "message": "agent state is disabled"},
                    }); return
                try:
                    requested_limit = int(limit)
                except (TypeError, ValueError, OverflowError):
                    requested_limit = 100
                snapshot_bound = None
                if through_seq is not None:
                    try:
                        snapshot_bound = int(through_seq)
                        if snapshot_bound < 0:
                            raise ValueError("through_seq cannot be negative")
                    except (TypeError, ValueError, OverflowError):
                        try:
                            error_cursor = max(0, int(after_seq))
                        except (TypeError, ValueError, OverflowError):
                            error_cursor = 0
                        self._send(400, {
                            "success": False, "events": [], "next_seq": error_cursor,
                            "first_retained_seq": 0, "last_seq": 0, "has_more": False,
                            "gap_ranges": [], "cursor_reset": False,
                            "error": {"code": "invalid_through_seq", "message": "through_seq must be a non-negative integer"},
                        }); return
                page_kwargs = {
                    "stream_id": stream_id,
                    "after_seq": after_seq,
                    "limit": max(1, min(requested_limit, services_module.AGENT_EVENT_PAGE_MAX_LIMIT)),
                }
                if snapshot_bound is not None:
                    page_kwargs["through_seq"] = through_seq
                try:
                    page = agent_state.event_page(**page_kwargs)
                except Exception as exc:
                    logger = getattr(services_module.APP, "logger", None)
                    if logger is not None:
                        logger.warning("agent event page failed error_type=%s", type(exc).__name__)
                    try:
                        error_cursor = max(0, int(after_seq))
                    except (TypeError, ValueError, OverflowError):
                        error_cursor = 0
                    self._send(503, {
                        "success": False,
                        "events": [],
                        "next_seq": error_cursor,
                        "first_retained_seq": 0,
                        "last_seq": 0,
                        "has_more": False,
                        "gap_ranges": [],
                        "cursor_reset": False,
                        "error": {"code": "event_page_unavailable", "message": "agent event page is temporarily unavailable"},
                        "retryable": True,
                        "terminal": False,
                    }); return
                status = 200 if page.get("success") is True else (
                    403 if (page.get("error") or {}).get("code") == "agent_state_disabled" else 503
                )
                status, page = services_module._bound_agent_event_page(status, page, after_seq)
                self._send(status, page); return
            if path == "/api/agent-state/blackboard":
                if not getattr(services_module.APP, "agent_blackboard", None):
                    self._send(503, {"success": False, "error": "blackboard unavailable"}); return
                board_id = (query.get("board_id") or query.get("task_id") or [""])[0]
                section = (query.get("section") or [None])[0]
                self._send(200, services_module.APP.agent_blackboard.get(board_id, section=section)); return
            if path == "/api/agent-state/swarm":
                if not getattr(services_module.APP, "swarm", None):
                    self._send(503, {"success": False, "error": "swarm coordinator unavailable"}); return
                st = (query.get("state") or [None])[0]
                lim = int((query.get("limit") or [50])[0])
                root = (query.get("root") or [None])[0]
                self._send(200, services_module.APP.swarm.list_swarms(state=st, limit=lim, root=root)); return
            if path.startswith("/api/agent-state/swarm/"):
                swarm_id = path.split("/api/agent-state/swarm/", 1)[1].strip()
                if not getattr(services_module.APP, "swarm", None):
                    self._send(503, {"success": False, "error": "swarm coordinator unavailable"}); return
                root = (query.get("root") or [None])[0]
                self._send(200, services_module.APP.swarm.get_status(swarm_id, root=root)); return
            if path == "/api/agent-state/events/stream":
                if not getattr(services_module.APP, "agent_state", None) or not services_module.APP.agent_state.enabled:
                    self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
                stream_filter = (query.get("stream_id") or [""])[0]
                kind_filter = (query.get("kind") or [""])[0]
                after_seq = max(0, min(int((query.get("after_seq") or [0])[0]), services_module.MAX_EVENT_SEQUENCE))
                timeout = float((query.get("timeout") or [0.0])[0])
                last_event_id = str(self.headers.get("Last-Event-ID", "") or (query.get("last_event_id") or [""])[0])
                self._stream_agent_events(
                    stream_id=stream_filter,
                    kind=kind_filter,
                    after_seq=after_seq,
                    timeout=timeout,
                    last_event_id=last_event_id,
                )
                return
            if path == "/api/capabilities":
                self._send(200, services_module.APP.capabilities()); return
            if path == "/api/benchmark/summary":
                if not getattr(services_module.APP, "benchmark_runner", None):
                    self._send(200, {"available": False}); return
                self._send(200, services_module.APP.benchmark_runner.get_latest_summary()); return
            if path == "/api/adoption":
                store = getattr(getattr(services_module.APP, "services", None), "adoption_metrics", None)
                if store is None:
                    self._send(200, {"success": True, "available": False}); return
                self._send(200, {"success": True, "available": True, "adoption": store.report(days=7)}); return
            if path == "/api/metrics":
                try:
                    days = int((query.get("days") or [30])[0])
                except (TypeError, ValueError, OverflowError):
                    self._send(400, {
                        "success": False,
                        "error": "days must be an integer",
                        "terminal": True,
                        "retryable": False,
                    }); return
                scope = str((query.get("scope") or ["window"])[0])
                flush_requested = str((query.get("flush") or ["0"])[0]).lower() in {"1", "true", "yes"}
                try:
                    metrics = services_module.APP.telemetry.summary(days, scope=scope, _flush=flush_requested)
                except ValueError as exc:
                    self._send(400, {
                        "success": False, "error": str(exc), "terminal": True, "retryable": False,
                    }); return
                self._send(200, {"success": True, "metrics": metrics}); return
            if path == "/api/telemetry/report":
                try:
                    days = int((query.get("days") or [30])[0])
                except (TypeError, ValueError, OverflowError):
                    self._send(400, {
                        "success": False,
                        "error": "days must be an integer",
                        "terminal": True,
                        "retryable": False,
                    }); return
                scope = str((query.get("scope") or ["window"])[0])
                try:
                    recent_errors = int((query.get("recent_errors") or query.get("error_limit") or [25])[0])
                    query_values = services_module.parse_qs(parsed.query, keep_blank_values=True)
                    if "error_offset" in query_values:
                        raise ValueError("error_offset is retired; use error_cursor")
                    error_cursor_values = query_values.get("error_cursor")
                    error_cursor = error_cursor_values[0] if error_cursor_values else ""
                except (TypeError, ValueError):
                    self._send(400, {
                        "success": False,
                        "error": "recent_errors must be an integer; use error_cursor for paging",
                        "terminal": True,
                        "retryable": False,
                    }); return
                flush_requested = str((query.get("flush") or ["0"])[0]).lower() in {"1", "true", "yes"}
                try:
                    report = services_module.APP.telemetry.report(
                        days, recent_errors=recent_errors, error_cursor=error_cursor,
                        scope=scope, _flush=flush_requested,
                    )
                except ValueError as exc:
                    self._send(400, {
                        "success": False, "error": str(exc), "terminal": True, "retryable": False,
                    }); return
                self._send(200, {"success": True, "report": report}); return
            if path == "/api/telemetry/timeline":
                limit = (query.get("limit") or [100])[0]
                before_id = (query.get("before_id") or [None])[0]
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
                    }); return
                self._send(200, {"success": True, **page}); return
            if path == "/api/telemetry/endpoint-stats":
                req_root = (query.get("root") or [""])[0]
                if req_root in ("all", "__all__"):
                    req_root = ""
                store = getattr(services_module.APP, "endpoint_stats", None)
                if store is None:
                    self._send(200, {"success": True, "available": False, "projects": [], "items": []}); return
                inc_unused = (query.get("unused", ["1"])[0].lower() not in ("0", "false", "no"))
                if query.get("scope", [""])[0].lower() == "active":
                    inc_unused = False
                inc_buckets = (query.get("buckets", ["0"])[0].lower() in ("1", "true", "yes"))
                stats = store.get_stats(root=req_root, include_unused=inc_unused, include_buckets=inc_buckets)
                self._send(200, stats); return
            if path == "/api/audit/tail":
                try:
                    limit = int((query.get("limit") or [20])[0])
                except (TypeError, ValueError, OverflowError):
                    self._send(400, {
                        "success": False,
                        "error": "limit must be an integer",
                        "terminal": True,
                        "retryable": False,
                    }); return
                self._send(200, {"success": True, "events": services_module.APP.telemetry.tail(limit)}); return
            if path == "/api/debug-traces":
                try:
                    trace_min_duration = int((query.get("min_duration_ms") or [0])[0])
                    trace_action = str((query.get("action") or [""])[0])
                    if not 0 <= trace_min_duration <= 86_400_000 or len(trace_action) > 64:
                        raise ValueError("trace filter outside allowed bounds")
                except (TypeError, ValueError, OverflowError):
                    self._send(400, {"success": False, "error": "trace filters require min_duration_ms=0..86400000 and action of at most 64 characters", "terminal": True, "retryable": False}); return
                result = services_module.APP.debug_traces.list(
                    kind=str((query.get("kind") or [""])[0]),
                    state=str((query.get("state") or [""])[0]),
                    agent=str((query.get("agent") or [""])[0]),
                    model=str((query.get("model") or [""])[0]),
                    action=trace_action.strip(),
                    min_duration_ms=trace_min_duration,
                    limit=services_module._query_int(query, "limit", 50),
                    offset=services_module._query_int(query, "offset", 0),
                )
                for item in result.get("items", []):
                    self._reconcile_debug_trace(item)
                self._send(200 if result.get("success") else 503 if result.get("retryable") else 400, result); return
            trace_prefix = "/api/debug-traces/"
            metrics_suffix = "/metrics"
            export_suffix = "/export"
            if path.startswith(trace_prefix) and path.endswith(export_suffix):
                trace_id = path[len(trace_prefix):-len(export_suffix)]
                if not trace_id or "/" in trace_id:
                    self._send(404, {"success": False, "error": "trace not found"}); return
                result = services_module.APP.debug_traces.detail(
                    trace_id,
                    since_seq=services_module._query_int(query, "since_seq", 0),
                    limit=max(1, min(services_module._query_int(query, "limit", 100), 1000)),
                    max_bytes=max(1024, min(services_module._query_int(query, "max_bytes", services_module.DEBUG_TRACE_HTTP_MAX_BYTES), services_module.DEBUG_TRACE_HTTP_MAX_BYTES)),
                    full_payload=True,
                )
                status = 200
                if result.get("error") == "trace not found":
                    status = 404
                elif result.get("error_code") == "trace_detail_oversize":
                    status = 413
                elif result.get("success") is not True:
                    status = 503 if result.get("retryable") else 500
                if status == 200:
                    result = services_module.redact_trace_export(result)
                    result["redacted_export"] = True
                self._send(status, result); return
            if path.startswith(trace_prefix) and path.endswith(metrics_suffix):
                trace_id = path[len(trace_prefix):-len(metrics_suffix)]
                if not trace_id or "/" in trace_id:
                    self._send(404, {"success": False, "error": "trace not found"}); return
                try:
                    request_id = services_module.APP.debug_traces.request_id_for_trace(trace_id)
                    if request_id is None:
                        self._send(404, {"success": False, "error": "trace not found"}); return
                    metrics_provider = getattr(getattr(services_module.APP, "telemetry", None), "request_metrics", None)
                    if not callable(metrics_provider):
                        raise RuntimeError("trace telemetry unavailable")
                    metrics = metrics_provider(request_id)
                except Exception as exc:
                    logger = getattr(services_module.APP, "logger", None)
                    warning = getattr(logger, "warning", None)
                    if callable(warning):
                        warning("debug trace metrics unavailable error_type=%s", type(exc).__name__)
                    self._send(503, {
                        "success": False,
                        "error": "trace metrics are temporarily unavailable",
                        "retryable": True,
                        "terminal": False,
                    }); return
                self._send(200, {"success": True, "trace_id": trace_id, "metrics": metrics}); return
            if path.startswith("/api/debug-traces/"):
                trace_id = path.rsplit("/", 1)[-1]
                detail_args = {
                    "since_seq": services_module._query_int(query, "since_seq", 0),
                    "limit": services_module._query_int(query, "limit", 100),
                    "max_bytes": max(
                        1024,
                        min(
                            services_module._query_int(query, "max_bytes", services_module.DEBUG_TRACE_HTTP_MAX_BYTES),
                            services_module.DEBUG_TRACE_HTTP_MAX_BYTES,
                        ),
                    ),
                    "before_seq": services_module._query_int(query, "before_seq", 0),
                    "full_payload": str((query.get("full") or [""])[0]).strip().lower()
                    in {"1", "true", "yes", "on"},
                    "content_field": str((query.get("content_field") or [""])[0])[:64],
                    "content_offset": services_module._query_int(query, "content_offset", 0),
                }
                result = services_module.APP.debug_traces.detail(trace_id, **detail_args)
                if result.get("error") == "trace not found":
                    self._send(404, result); return
                if result.get("error_code") == "trace_detail_oversize":
                    self._send(413, result); return
                if result.get("success") and isinstance(result.get("session"), dict):
                    session = result["session"]
                    session_before = services_module._json_bytes(session)
                    session = self._reconcile_debug_trace(session)
                    if services_module._json_bytes(session) != session_before:
                        # Rebuild page after reconciliation so response_bytes still
                        # describes exact response, including refreshed session data.
                        result = services_module.APP.debug_traces.detail(trace_id, **detail_args)
                        if result.get("error_code") == "trace_detail_oversize":
                            self._send(413, result); return
                        if result.get("error") == "trace not found":
                            self._send(404, result); return
                        session = result.get("session", {})
                    result["terminal"] = session.get("state") in services_module.APP.debug_traces.TERMINAL_STATES
                self._send(200, result); return
            if path == "/api/rag/workspaces":
                self._send(200, {"success": True, "workspaces": services_module.APP.rag.list_workspaces()}); return
            if path == "/api/leases":
                root = (query.get("root") or [""])[0]
                coordination_id = services_module._lease_coordination_id(root)
                self._send(200, {"success": True, "leases": services_module.APP.leases.list(root, coordination_id=coordination_id), "waits": services_module.APP.leases.waits(root, coordination_id=coordination_id)}); return
            if path == "/api/cross_project_graph":
                roots = [str(root) for root in query.get("roots", []) if root]
                if services_module.APP.deterministic is not None:
                    self._send(200, services_module.APP.deterministic.cross_project_graph(roots))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path in {"/api/repo/dead_code"}:
                root = (query.get("root") or ["."])[0]
                if services_module.APP.deterministic is not None:
                    self._send(200, services_module.APP.services.dead_code(root))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/api/symbol_callgraph":
                root = (query.get("root") or ["."])[0]
                sym = (query.get("symbol") or [None])[0]
                if services_module.APP.deterministic is not None:
                    self._send(200, services_module.APP.deterministic.symbol_callgraph(root, sym))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/api/hardware/gpu":
                from .gpu_monitor import get_gpu_telemetry
                self._send(200, get_gpu_telemetry())
                return
            if path == "/api/hardware/system":
                from .gpu_monitor import get_system_telemetry
                self._send(200, get_system_telemetry())
                return
            if path == "/api/audit_dependencies":
                root = (query.get("root") or ["."])[0]
                if services_module.APP.deterministic is not None:
                    self._send(200, services_module.APP.deterministic.audit_dependencies(root))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/api/refactor_impact":
                root = (query.get("root") or ["."])[0]
                file_param = (query.get("file") or [""])[0]
                symbol_param = (query.get("symbol") or [None])[0]
                if services_module.APP.deterministic is not None:
                    self._send(200, services_module.APP.services.refactor_impact(root, file_param, symbol_param))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/api/test_matrix":
                root = (query.get("root") or ["."])[0]
                if services_module.APP.deterministic is not None:
                    self._send(200, services_module.APP.services.test_matrix(root))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path in {"/api/repo/affected_tests"}:
                root = (query.get("root") or ["."])[0]
                paths = query.get("path") or query.get("paths") or None
                if services_module.APP.deterministic is not None:
                    self._send(200, services_module.APP.services.affected_tests(root, changed_paths=paths))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path in {"/api/repo/topology"}:
                root = (query.get("root") or ["."])[0]
                if services_module.APP.deterministic is not None:
                    self._send(200, services_module.APP.services.repo_topology(root))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/api/db/query":
                db_name = (query.get("db") or ["agent_state"])[0]
                sql_q = (query.get("query") or ["SELECT name FROM sqlite_master WHERE type='table'"])[0]
                self._send(200, self._handle_db_query(db_name, sql_q))
                return
            if self._handle_admin_get(path, query):
                return
            if path == "/api/code/ast_outline":
                root = (query.get("root") or ["."])[0]
                path_param = (query.get("path") or [""])[0]
                if services_module.APP.deterministic is not None:
                    self._send(200, services_module.APP.services.ast_outline(root, path_param))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path in {"/api/project/config"}:
                canonical = (query.get("root") or [None])[0]
                if not canonical:
                    self._send(400, {"success": False, "error": "root is required for project configuration", "terminal": True, "retryable": False})
                    return
                from .project_config import resolve_project_config
                try:
                    resolution = resolve_project_config(canonical)
                    settings = resolution.settings
                    config_file = services_module.Path(canonical) / ".local-ai.toml"
                    sources = list(getattr(resolution, "active_sources", getattr(resolution, "sources", ())))
                    self._send(200, {
                        "success": True,
                        "root": canonical,
                        "config_file": str(config_file),
                        "config_exists": config_file.is_file(),
                        "sources": sources,
                        "settings": {
                            "exclude_paths": list(settings.exclude_paths),
                            "force_include_paths": list(settings.force_include_paths),
                            "path_overrides": dict(settings.path_overrides),
                            "custom_extensions": list(settings.text_extensions),
                            "binary_extensions": list(settings.binary_extensions),
                            "skip_phases": list(settings.skip_phases),
                            "commands": {k: (list(v.argv) if hasattr(v, "argv") else str(v)) for k, v in settings.commands.items()},
                            "max_file_size_bytes": settings.max_file_size_bytes,
                            "model_profile": getattr(settings, "model_profile", None),
                            "system_prompt_prefix": getattr(settings, "system_prompt_prefix", None),
                        }
                    })
                except Exception as exc:
                    self._send(500, {"success": False, "error": str(exc), "terminal": True, "retryable": False})
                return
            if path == "/api/code/symbol":
                root = (query.get("root") or ["."])[0]
                sym = (query.get("symbol") or [""])[0]
                self._send(200, services_module.APP.services.code_inspect_symbol(root, sym))
                return
            if path == "/api/code/find_symbol":
                root = (query.get("root") or ["."])[0]
                pat = (query.get("pattern") or query.get("name_path_pattern") or [""])[0]
                depth = int((query.get("depth") or [0])[0])
                include_body = services_module._parse_include_body((query.get("include_body") or [None])[0], query=True)
                if include_body is None:
                    self._send(400, {"success": False, "error": "include_body must be a boolean"})
                    return
                rel_path = (query.get("path") or query.get("relative_path") or [None])[0]
                self._send(200, services_module.APP.services.code_find_symbol(root, pat, depth=depth, include_body=include_body, relative_path=rel_path))
                return
            if path == "/api/code/find_implementations":
                root = (query.get("root") or ["."])[0]
                sym = (query.get("symbol") or query.get("name") or [""])[0]
                rel_path = (query.get("path") or [None])[0]
                self._send(200, services_module.APP.services.code_find_implementations(root, sym, path=rel_path))
                return
            if path == "/api/code/find_referencing_symbols":
                root = (query.get("root") or ["."])[0]
                sym = (query.get("symbol") or query.get("name") or [""])[0]
                rel_path = (query.get("path") or [None])[0]
                self._send(200, services_module.APP.services.code_find_referencing_symbols(root, sym, path=rel_path))
                return
            if path == "/api/code/symbols_overview":
                root = (query.get("root") or ["."])[0]
                fpath = (query.get("path") or [""])[0]
                depth = int((query.get("depth") or [1])[0])
                self._send(200, services_module.APP.services.code_symbols_overview(root, fpath, depth=depth))
                return
            if path == "/api/code/diagnostics":
                root = (query.get("root") or ["."])[0]
                fpath = (query.get("path") or [""])[0]
                self._send(200, services_module.APP.services.code_diagnostics(root, fpath))
                return
            if path == "/api/resolve_imports":
                root = (query.get("root") or ["."])[0]
                lang = (query.get("language") or ["auto"])[0]
                symbols = [s for s in (query.get("symbols") or (query.get("symbol") or [])) if s]
                if services_module.APP.deterministic is not None:
                    self._send(200, services_module.APP.services.resolve_imports(root, symbols, lang))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path in {"/api/coord/worktrees"}:
                root = (query.get("root") or ["."])[0]
                self._send(200, services_module.APP.services.list_worktrees(root))
                return

            if path == "/api/git/status":
                root = (query.get("root") or ["."])[0]
                if services_module.APP.deterministic is not None:
                    self._send(200, services_module.APP.deterministic.git_status(root))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path in {"/api/repo/state"}:
                root = (query.get("root") or ["."])[0]
                tracker = getattr(services_module.APP, "repo_state", None) or (getattr(services_module.APP.services, "repo_state", None) if getattr(services_module.APP, "services", None) else None)
                if tracker is not None:
                    try:
                        self._send(200, tracker.fingerprint(root))
                    except Exception:
                        self._send(200, {
                            "success": False,
                            "error": "repo state unavailable",
                            "error_code": "repo_state_unavailable",
                        })
                else:
                    self._send(200, {"success": False, "error": "repo_state tracker unavailable"})
                return
            if path == "/api/git/diff":
                root = (query.get("root") or ["."])[0]
                p = (query.get("path") or [None])[0]
                staged = (query.get("staged") or ["false"])[0].lower() in {"1", "true", "yes"}
                if services_module.APP.deterministic is not None:
                    revisions = {key: query[key][0] for key in ("rev1", "rev2") if key in query}
                    max_lines = int((query.get("max_lines") or [1000])[0])
                    base_val = (query.get("base") or ["HEAD"])[0]
                    if not revisions and base_val != "HEAD":
                        revisions = {"rev1": base_val, "rev2": "HEAD"}
                    self._send(200, services_module.APP.services.git_diff(root, path=p, staged=staged, max_lines=max_lines, **revisions))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/api/git/history_search":
                from .git_history_search import _git_history_pathspec, _git_history_timestamp

                root = (query.get("root") or ["."])[0]
                q = (query.get("query") or [""])[0]
                raw_max_c = (query.get("max_commits") or ["20"])[0]
                if not isinstance(raw_max_c, str) or not raw_max_c.isascii() or not raw_max_c.isdigit():
                    self._send(400, {"success": False, "error": "max_commits must be an integer from 1 to 100", "terminal": True, "retryable": False}); return
                max_c = int(raw_max_c)
                if not 1 <= max_c <= 100:
                    self._send(400, {"success": False, "error": "max_commits must be an integer from 1 to 100", "terminal": True, "retryable": False}); return
                filters = {
                    name: (query.get(name) or [None])[0]
                    for name in ("author", "since", "until", "path")
                }
                if (
                    not isinstance(q, str)
                    or len(q) > 512
                    or any(ord(char) < 32 or ord(char) == 127 for char in q)
                ):
                    self._send(400, {"success": False, "error": "query must be a bounded literal string", "terminal": True, "retryable": False}); return
                for name, value in filters.items():
                    maximum = 256 if name == "author" else 64 if name in {"since", "until"} else 4096
                    if value is not None and (
                        not isinstance(value, str)
                        or len(value) > maximum
                        or any(ord(char) < 32 or ord(char) == 127 for char in value)
                    ):
                        self._send(400, {"success": False, "error": f"{name} must be a bounded string", "terminal": True, "retryable": False}); return
                try:
                    since_epoch, _since = _git_history_timestamp(filters["since"], "since", upper_bound=False)
                    until_epoch, _until = _git_history_timestamp(filters["until"], "until", upper_bound=True)
                    _git_history_pathspec(root, filters["path"])
                except (OSError, RuntimeError, TypeError, ValueError, OverflowError) as exc:
                    self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                if since_epoch is not None and until_epoch is not None and since_epoch > until_epoch:
                    self._send(400, {"success": False, "error": "since must be earlier than or equal to until", "terminal": True, "retryable": False}); return
                if services_module.APP.deterministic is not None:
                    result = services_module.APP.services.git_history_search(
                        root,
                        q,
                        max_commits=max_c,
                        author=filters["author"],
                        since=filters["since"],
                        until=filters["until"],
                        path=filters["path"],
                    )
                    result_status = result.get("status_code") if isinstance(result, dict) else None
                    status = (
                        result_status
                        if isinstance(result_status, int) and not isinstance(result_status, bool)
                        and 400 <= result_status <= 599
                        else 200
                    )
                    self._send(status, result)
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/api/git/synthesize_commit":
                root = (query.get("root") or ["."])[0]
                hint = (query.get("hint") or [""])[0]
                task_id = (query.get("task_id") or [""])[0]
                if services_module.APP.deterministic is not None:
                    self._send(200, services_module.APP.services.synthesize_commit(root, hint, task_id=task_id))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/api/models":
                models = services_module.APP.runtime.installed_models()
                self._send(200, {"object": "list", "data": [{"id": m, "object": "model", "owned_by": "ollama"} for m in models]}); return
            self._send(404, {"error": "not found"})
        except (ValueError, TypeError, services_module.RequestBodyError) as exc:
            self._send(400, {"success": False, "error": str(exc), "status_code": 400, "terminal": True, "retryable": False})
        except KeyError as exc:
            self._send(404, {"success": False, "error": str(exc), "status_code": 404, "terminal": True, "retryable": False})
        except Exception as exc:
            if services_module._is_client_disconnect(exc):
                self._finish_debug_trace(499, {"success": False, "terminal": True}, error="client disconnected")
                self._close_trace_context()
                return
            if services_module.is_busy_error(exc):
                self._send_database_locked()
                return
            try:
                logger = getattr(services_module.APP, "logger", None)
                if logger is not None:
                    services_module._log_http_failure(logger, "GET", path, exc)
                self._send(500, {
                    "success": False,
                    "error": "internal server error",
                    "error_code": "internal_error",
                    "terminal": True,
                    "retryable": False,
                })
            except Exception:
                pass

    def _handle_dashboard_updates(self, *, mutate: bool = False) -> None:
        if self.headers.get("X-LocalAI-Client") != "dashboard" or not services_module._is_loopback_peer(self):
            self._send(403, {"success": False, "error": "Update controls require the local dashboard."})
            return
        controller = getattr(services_module.APP, "dashboard_updates", None)
        if controller is None:
            self._send(503, {"success": False, "error": "Update controls are unavailable."})
            return
        if not mutate:
            self._send(200, controller.status())
            return
        try:
            payload = self._read_json()
        except services_module.RequestBodyError as exc:
            self._send(exc.status, {"success": False, "error": str(exc)})
            return
        if payload == {"action": "check"}:
            self._send(200, controller.status(refresh=True))
            return
        if set(payload) != {"action", "version", "revision", "confirm_restart"} or (
            payload.get("action") != "install" or payload.get("confirm_restart") is not True
        ):
            self._send(400, {"success": False, "error": "Review the release and confirm a Hub restart."})
            return
        try:
            result = controller.install(payload["version"], payload["revision"])
        except ValueError as exc:
            self._send(409, {"success": False, "error": str(exc)})
        except (OSError, RuntimeError) as exc:
            self._send(503, {"success": False, "error": str(exc)})
        else:
            self._send(202, result)


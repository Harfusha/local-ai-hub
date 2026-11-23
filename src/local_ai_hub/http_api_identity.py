from __future__ import annotations

from typing import Any, Mapping

from .http_server_proxy import services_module


class HttpIdentityMixin:
    def _bind_root(self, raw_root: Any) -> str | None:
        if not self._reject_retired_tenant_headers():
            return None
        try:
            config = services_module.APP.config if services_module.APP is not None else {}
            root = services_module.authorized_repository_root(config, raw_root)
        except services_module.RepositoryScopeError as exc:
            self._send(exc.status_code, {
                "success": False, "error": str(exc), "error_code": exc.code,
                "terminal": True, "retryable": False,
            })
            return None
        self._authorization_root = root
        return root

    def _reject_identity_fields(self, payload: Mapping[str, Any]) -> bool:
        try:
            services_module.reject_retired_tenancy_fields(payload)
        except services_module.RepositoryScopeError as exc:
            self._send(exc.status_code, {
                "success": False, "error": str(exc), "error_code": exc.code,
                "terminal": True, "retryable": False,
            })
            return False
        return self._reject_retired_tenant_headers()

    def _reject_retired_tenant_headers(self) -> bool:
        headers = getattr(self, "headers", {})
        requested_headers = {
            item.strip().lower()
            for item in str(headers.get("Access-Control-Request-Headers", "")).split(",")
            if item.strip()
        }
        for name in ("X-LocalAI-Tenant", "X-Tenant-ID"):
            if name in headers or name.lower() in requested_headers:
                self._send(400, {
                    "success": False, "error": f"retired request header: {name}",
                    "error_code": "retired_tenant_header", "terminal": True, "retryable": False,
                })
                return False
        return True

    def _agent_action_or_error(self, payload: dict[str, Any], default: str) -> str | None:
        try:
            return services_module._agent_action_selector(payload, default)
        except services_module.RequestBodyError as exc:
            self._send(exc.status, {
                "success": False,
                "error": str(exc),
                "terminal": True,
                "retryable": False,
            })
            return None

    def _bind_memory_payload(self, payload: dict[str, Any]) -> bool:
        if not self._reject_identity_fields(payload):
            return False
        record = payload.get("record") if isinstance(payload.get("record"), dict) else {}
        containers = [payload, record]
        for item in tuple(containers):
            provenance = item.get("provenance")
            if isinstance(provenance, dict):
                containers.append(provenance)
        action = self._agent_action_or_error(payload, "")
        if action is None:
            return False
        try:
            scopes = {services_module._parse_memory_scope(item["scope"]) for item in (payload, record) if "scope" in item}
            scopes.discard(None)
            if len(scopes) > 1:
                raise ValueError("conflicting memory scopes")
            scope = next(iter(scopes), None)
        except ValueError as exc:
            self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False})
            return False
        if action == "delete" and scope is services_module.AgentScope.WORKTREE:
            self._send(403, {"success": False, "error": "worktree-scoped memory delete requires verified worktree scope", "terminal": True, "retryable": False})
            return False
        roots = [item["root"] for item in containers if "root" in item]
        scoped_identity = any(
            item.get(name) for item in (payload, record)
            for name in ("task_id", "repository_id", "clone_id", "worktree_id", "branch")
        )
        if not roots and (scope in {
            services_module.AgentScope.REPOSITORY, services_module.AgentScope.CLONE, services_module.AgentScope.WORKTREE, services_module.AgentScope.BRANCH, services_module.AgentScope.TASK,
        } or scoped_identity):
            self._send(400, {"success": False, "error": "root is required for repository or task memory", "error_code": "root_required", "terminal": True, "retryable": False})
            return False
        canonical_root = None
        for raw_root in roots:
            root = self._bind_root(raw_root)
            if root is None:
                return False
            if canonical_root is not None and canonical_root != root:
                self._send(403, {"success": False, "error": "root identity mismatch", "error_code": "root_not_allowed", "terminal": True, "retryable": False})
                return False
            canonical_root = root
        if canonical_root is not None:
            payload["root"] = canonical_root
            for item in containers[1:]:
                if "root" in item:
                    item["root"] = canonical_root
            task_ids = [item.get("task_id") for item in containers if item.get("task_id") not in (None, "")]
            if scope is services_module.AgentScope.TASK:
                task_ids.extend(item.get("scope_id") for item in (payload, record) if item.get("scope_id") not in (None, ""))
            if not self._validate_memory_task_identity(canonical_root, task_ids):
                return False
        if scope is services_module.AgentScope.SESSION:
            identities = [
                item[name] for item in (payload, record)
                for name in ("session_id", "scope_id") if name in item and item[name] != ""
            ]
            if not identities or any(
                not isinstance(value, str) or not value or value != value.strip() or "\x00" in value
                for value in identities
            ) or len(set(identities)) != 1:
                self._send(400, {"success": False, "error": "explicit matching session identity is required", "terminal": True, "retryable": False})
                return False
            payload.update(session_id=identities[0], scope_id=identities[0])
            if record:
                record.update(session_id=identities[0], scope_id=identities[0])
        return True

    def _bind_memory_query(self, query: dict[str, list[str]]) -> bool:
        if not self._reject_identity_fields(query):
            return False
        scalar: dict[str, Any] = {"action": "find"}
        for name, values in query.items():
            if not isinstance(values, list) or not values or any(not isinstance(value, str) for value in values):
                self._send(400, {"success": False, "error": "invalid memory query values", "terminal": True, "retryable": False})
                return False
            if name == "root":
                roots = [self._bind_root(value) for value in values]
                if any(root is None for root in roots):
                    return False
                if len(set(roots)) != 1:
                    self._send(403, {"success": False, "error": "root identity mismatch", "terminal": True, "retryable": False})
                    return False
                scalar[name] = roots[0]
            elif len(set(values)) != 1:
                self._send(400, {"success": False, "error": f"conflicting query field: {name}", "terminal": True, "retryable": False})
                return False
            else:
                scalar[name] = values[0]
        if not self._bind_memory_payload(scalar):
            return False
        for name in ("root", "session_id", "scope_id"):
            if name in scalar:
                query[name] = [scalar[name]]
        return True

    def _bind_task_payload(self, payload: dict[str, Any]) -> bool:
        if not self._reject_identity_fields(payload):
            return False
        root = self._bind_root(payload.get("root"))
        if root is None:
            return False
        context = payload.get("context")
        if context is None:
            context = {}
        if not isinstance(context, dict) or not self._reject_identity_fields(context):
            if not isinstance(context, dict):
                self._send(400, {"success": False, "error": "context must be an object", "terminal": True, "retryable": False})
            return False
        for name in ("repository_id", "clone_id", "worktree_id", "branch", "task_id", "session_id"):
            if name in context and (
                not isinstance(context[name], str) or context[name] != context[name].strip() or "\x00" in context[name]
            ):
                self._send(400, {"success": False, "error": f"{name} must be a canonical string", "terminal": True, "retryable": False})
                return False
        project_context = services_module._trusted_project_context(root)
        coordination_id = getattr(project_context, "coordination_id", None)
        if (
            not isinstance(coordination_id, str)
            or not coordination_id
            or coordination_id != coordination_id.strip()
            or "\x00" in coordination_id
        ):
            self._send(403, {
                "success": False, "error": "task root has no resolved project coordination identity",
                "error_code": "repository_identity_unavailable", "terminal": True, "retryable": False,
            })
            return False
        if "repository_id" in context and context["repository_id"] != coordination_id:
            self._send(403, {
                "success": False, "error": "task repository identity does not match the authorized root",
                "error_code": "repository_identity_mismatch", "terminal": True, "retryable": False,
            })
            return False
        if "repo_root" in payload:
            supplied_root = self._bind_root(payload["repo_root"])
            if supplied_root is None:
                return False
            if supplied_root != root:
                self._send(403, {"success": False, "error": "task root identity mismatch", "error_code": "root_not_allowed", "terminal": True, "retryable": False})
                return False
        context = dict(context)
        context["repository_id"] = coordination_id
        payload.update(root=root, repo_root=root, context=context)
        return True

    def _bind_incident_payload(self, payload: dict[str, Any]) -> bool:
        return self._bind_repository_root_payload(payload)

    def _bind_swarm_payload(self, payload: dict[str, Any]) -> bool:
        return self._bind_repository_root_payload(payload)

    def _bind_swarm_query(self, query: dict[str, list[str]]) -> bool:
        return self._bind_repository_root_query(query)

    def _bind_repository_root_payload(self, payload: dict[str, Any]) -> bool:
        if not self._reject_identity_fields(payload):
            return False
        root = self._bind_root(payload.get("root"))
        if root is None:
            return False
        payload["root"] = root
        return True

    def _bind_repository_root_query(self, query: dict[str, list[str]]) -> bool:
        if not self._reject_identity_fields(query):
            return False
        values = query.get("root", [])
        if not values:
            self._send(400, {"success": False, "error": "root is required for repository queries", "error_code": "root_required", "terminal": True, "retryable": False})
            return False
        roots = []
        for value in values:
            root = self._bind_root(value)
            if root is None:
                return False
            roots.append(root)
        if len(set(roots)) != 1:
            self._send(403, {"success": False, "error": "root identity mismatch", "error_code": "root_not_allowed", "terminal": True, "retryable": False})
            return False
        query["root"] = [roots[0]]
        return True

    def _bind_multi_repository_query(self, query: dict[str, list[str]]) -> bool:
        if not self._reject_identity_fields(query):
            return False
        payload: dict[str, Any] = {"roots": query.get("roots")}
        if not self._bind_multi_repository_payload(payload):
            return False
        query["roots"] = payload["roots"]
        return True

    def _bind_multi_repository_payload(self, payload: dict[str, Any], *, cross_repo_contract: bool = False) -> bool:
        if not self._reject_identity_fields(payload):
            return False
        roots = [payload.get("backend_root"), payload.get("frontend_root")] if cross_repo_contract else payload.get("roots")
        if not isinstance(roots, list) or not roots:
            self._send(400, {"success": False, "error": "explicit roots are required", "terminal": True, "retryable": False})
            return False
        canonical = []
        for raw_root in roots:
            root = self._bind_root(raw_root)
            if root is None:
                return False
            canonical.append(root)
        if cross_repo_contract:
            payload["backend_root"], payload["frontend_root"] = canonical
        else:
            payload["roots"] = canonical
            if payload.get("origin_root") not in (None, ""):
                origin = self._bind_root(payload["origin_root"])
                if origin is None:
                    return False
                if origin not in canonical:
                    self._send(400, {"success": False, "error": "origin_root must be one of the explicit roots", "terminal": True, "retryable": False})
                    return False
                payload["origin_root"] = origin
        self._authorization_root = canonical[0]
        return True

    @staticmethod
    def _task_matches_request(task: Any, root: str) -> bool:
        try:
            from .agent_tasks import _task_matches_scope

            return _task_matches_scope(task, str(services_module._strict_root_path(root)))
        except (AttributeError, OSError, TypeError, ValueError):
            return False

    def _handle_task_automation(self, payload: dict[str, Any]) -> None:
        if not self._authorized(permission="write"):
            self._send(403, {"success": False, "error": "automation requires write authorization", "terminal": True, "retryable": False}); return
        if set(payload) - {"root", "task_id", "automation"}:
            self._send(400, {"success": False, "error": "unexpected automation fields", "terminal": True, "retryable": False}); return
        if not self._bind_task_payload(payload):
            return
        task_id = payload.get("task_id")
        if not isinstance(task_id, str) or not task_id or task_id != task_id.strip():
            self._send(400, {"success": False, "error": "canonical task_id required", "terminal": True, "retryable": False}); return
        task = self._request_task(task_id, payload["root"])
        if task is None:
            return
        request = payload.get("automation")
        if not isinstance(request, dict):
            self._send(400, {"success": False, "error": "automation must be an object", "terminal": True, "retryable": False}); return
        status = getattr(task.status, "value", task.status)
        if request.get("op") != "close" and status not in {"planned", "running"}:
            self._send(409, {"success": False, "error": "task is not active", "terminal": True, "retryable": False}); return
        result = services_module.APP.automation.execute(root=payload["root"], task_id=task_id, request=request)
        self._send(result.get("status_code", 200), result)

    def _task_budget_increase(self, payload: dict[str, Any]) -> None:
        if not self._authorized(permission="write"):
            self._send(403, {"success": False, "error": "task budget write authorization required",
                             "terminal": True, "retryable": False}); return
        # Reauthorization clears root context; rebind through the
        # same repository/task identity checks as other task mutations.
        if not self._bind_task_payload(payload):
            return
        permitted = {"action", "root", "repo_root", "context", "task_id",
                     "reason", "budget", "response_budget_tokens"}
        if set(payload) - permitted:
            self._send(400, {"success": False, "error": "unexpected budget action fields",
                             "terminal": True, "retryable": False}); return
        task_id = payload.get("task_id")
        if not isinstance(task_id, str) or not task_id or task_id != task_id.strip():
            self._send(400, {"success": False, "error": "canonical task_id required"}); return
        if self._request_task(task_id, payload["root"]) is None:
            return
        # The broker persists the real transport actor and before/after budget
        # atomically with the update. This ordinary write is not an admin action.
        try:
            result = services_module.APP.commands.increase_task_budget(
                task_id, root=payload["root"], reason=payload.get("reason"),
                limits=payload.get("budget"),
                authorization_actor=self._authorization_actor,
                authorization_permissions=self._authorization_permissions,
                response_budget_tokens=payload.get("response_budget_tokens"),
            )
        except services_module.CheckpointResponseBudgetError as exc:
            self._send(413, {"success": False, "error": str(exc), "terminal": True,
                             "retryable": False, "mutation_applied": False,
                             "operation_not_started": True,
                             "response_budget": {"requested_tokens": exc.requested_tokens,
                                                 "required_tokens": exc.required_tokens}}); return
        except PermissionError as exc:
            self._send(403, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
        except (TypeError, ValueError, KeyError) as exc:
            self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
        self._send(200, result); return

    def _task_repair_session(self, payload: dict[str, Any]) -> None:
        if not self._authorized(permission="write"):
            self._send(403, {"success": False, "error": "task session write authorization required", "terminal": True, "retryable": False}); return
        if not self._bind_task_payload(payload):
            return
        permitted = {"action", "root", "repo_root", "context", "task_id", "session_id", "reason", "response_budget_tokens"}
        if set(payload) - permitted:
            self._send(400, {"success": False, "error": "unexpected session repair fields", "terminal": True, "retryable": False}); return
        task_id = payload.get("task_id")
        if not isinstance(task_id, str) or not task_id or task_id != task_id.strip():
            self._send(400, {"success": False, "error": "canonical task_id required"}); return
        if self._request_task(task_id, payload["root"]) is None:
            return
        try:
            result = services_module.APP.commands.repair_task_session(
                task_id, root=payload["root"], session_id=payload.get("session_id"), reason=payload.get("reason"),
                authorization_actor=self._authorization_actor, authorization_permissions=self._authorization_permissions,
                response_budget_tokens=payload.get("response_budget_tokens"),
            )
        except services_module.CheckpointResponseBudgetError as exc:
            self._send(413, {"success": False, "error": str(exc), "terminal": True, "retryable": False,
                             "mutation_applied": False, "operation_not_started": True,
                             "response_budget": {"requested_tokens": exc.requested_tokens, "required_tokens": exc.required_tokens}}); return
        except PermissionError as exc:
            self._send(403, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
        except (TypeError, ValueError, KeyError) as exc:
            self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
        self._send(200, {"success": True, "task": result.to_dict()}); return

    def _request_task(self, task_id: str, root: str) -> Any | None:
        task = services_module.APP.agent_tasks.get(task_id) if services_module.APP is not None and getattr(services_module.APP, "agent_tasks", None) else None
        if task is None or not self._task_matches_request(task, root):
            self._send(404, {"success": False, "error": "task not found", "terminal": True, "retryable": False})
            return None
        return task

    def _require_scoped_task(self, task_id: str) -> Any | None:
        root = getattr(self, "_authorization_root", None)
        if not root:
            self._send(400, {"success": False, "error": "root is required for task access", "terminal": True, "retryable": False})
            return None
        return self._request_task(task_id, root)

    def _bind_context_payload(self, payload: dict[str, Any]) -> bool:
        if not self._reject_identity_fields(payload):
            return False
        if "_scoped_task_only" in payload and type(payload["_scoped_task_only"]) is not bool:
            self._send(400, {"success": False, "error": "_scoped_task_only must be boolean", "terminal": True, "retryable": False})
            return False
        task_id = payload.get("task_id")
        if not isinstance(task_id, str) or not task_id or task_id != task_id.strip():
            self._send(400, {"success": False, "error": "task_id is required for context compilation", "terminal": True, "retryable": False})
            return False
        task = services_module.APP.agent_tasks.get(task_id) if services_module.APP is not None and getattr(services_module.APP, "agent_tasks", None) else None
        if task is None:
            self._send(404, {"success": False, "error": "task not found", "terminal": True, "retryable": False})
            return False
        from .agent_tasks import _task_scope_root

        task_root = self._bind_root(_task_scope_root(task))
        if task_root is None:
            return False
        for name in ("root",):
            if name not in payload:
                continue
            supplied_repository = payload[name]
            if supplied_repository == "":
                continue
            root = self._bind_root(supplied_repository)
            if root is None:
                return False
            if root != task_root:
                self._send(403, {"success": False, "error": "context root does not match task", "terminal": True, "retryable": False})
                return False
        task_repository_id = getattr(task.context, "repository_id", "")
        if "repository_id" in payload and payload["repository_id"] not in ("", task_repository_id):
            self._send(403, {"success": False, "error": "context repository identity does not match task", "terminal": True, "retryable": False})
            return False
        session = payload.get("session_id")
        task_session = getattr(task.context, "session_id", None)
        if session not in (None, "") and task_session not in (None, "") and session != task_session:
            self._send(403, {"success": False, "error": "context session does not match task", "terminal": True, "retryable": False})
            return False
        payload.update(root=task_root, repository_id=task_repository_id, _scoped_task_only=True)
        return True

    def _bind_task_event_query(self, query: dict[str, list[str]]) -> bool:
        if not self._bind_repository_root_query(query):
            return False
        stream_id = (query.get("stream_id") or [""])[0]
        if not isinstance(stream_id, str) or not stream_id.startswith("task:") or not stream_id[5:]:
            self._send(403, {"success": False, "error": "only task-scoped event streams are available", "terminal": True, "retryable": False})
            return False
        task_id = stream_id[5:]
        if any(value != task_id for value in query.get("task_id", [])):
            self._send(403, {"success": False, "error": "event stream task identity mismatch", "terminal": True, "retryable": False})
            return False
        return self._validate_memory_task_identity(query["root"][0], [task_id])

    def _bind_task_event_payload(self, payload: dict[str, Any]) -> bool:
        action = self._agent_action_or_error(payload, "export")
        if action is None:
            return False
        if action != "export":
            self._send(403, {"success": False, "error": "global event import is unavailable through root-scoped access", "terminal": True, "retryable": False})
            return False
        if not self._bind_repository_root_payload(payload):
            return False
        stream_id = payload.get("stream_id")
        if not isinstance(stream_id, str) or not stream_id.startswith("task:") or not stream_id[5:]:
            self._send(403, {"success": False, "error": "only task-scoped event export is available", "terminal": True, "retryable": False})
            return False
        task_id = stream_id[5:]
        if payload.get("task_id") not in (None, "", task_id):
            self._send(403, {"success": False, "error": "event stream task identity mismatch", "terminal": True, "retryable": False})
            return False
        if not self._validate_memory_task_identity(payload["root"], [task_id]):
            return False
        payload.update(action="export", task_id=task_id)
        return True

    @staticmethod
    def _task_board_id_allowed(board_id: str, task_id: str) -> bool:
        return board_id in {task_id, f"task:{task_id}"}

    def _bind_task_board_query(self, query: dict[str, list[str]]) -> bool:
        if not self._bind_repository_root_query(query):
            return False
        task_id = (query.get("task_id") or [""])[0]
        if not isinstance(task_id, str) or not task_id:
            self._send(400, {"success": False, "error": "task_id is required for blackboard access", "terminal": True, "retryable": False})
            return False
        if not self._validate_memory_task_identity(query["root"][0], [task_id]):
            return False
        board_id = (query.get("board_id") or [task_id])[0]
        if not self._task_board_id_allowed(board_id, task_id):
            self._send(403, {"success": False, "error": "blackboard access requires task-owned board id", "terminal": True, "retryable": False})
            return False
        query.update(task_id=[task_id], board_id=[board_id])
        return True

    def _bind_task_board_payload(self, payload: dict[str, Any]) -> bool:
        retired_fields = sorted(services_module._AGENT_BLACKBOARD_RETIRED_FIELDS.intersection(payload))
        if retired_fields:
            fields = ", ".join(retired_fields)
            self._send(400, {
                "success": False,
                "error": f"unsupported blackboard field(s): {fields}",
                "terminal": True,
                "retryable": False,
            })
            return False
        action = self._agent_action_or_error(payload, "get")
        if action is None:
            return False
        if action == "list":
            self._send(403, {"success": False, "error": "global blackboard listing is unavailable through root-scoped access", "terminal": True, "retryable": False})
            return False
        if action not in {"update", "get", "merge", "delete"}:
            self._send(400, {"success": False, "error": "unknown blackboard action", "terminal": True, "retryable": False})
            return False
        if not self._bind_task_payload(payload):
            return False
        task_id = str(payload.get("task_id", "") or "").strip()
        if self._require_scoped_task(task_id) is None:
            return False
        board_id = str(payload.get("board_id", task_id)).strip()
        if not self._task_board_id_allowed(board_id, task_id):
            self._send(403, {"success": False, "error": "blackboard access requires task-owned board id", "terminal": True, "retryable": False})
            return False
        payload["board_id"] = board_id
        payload["action"] = action
        return True

    def _bind_workspace_memory_payload(self, path: str, payload: dict[str, Any]) -> bool:
        return self._bind_repository_root_payload(payload)

    def _validate_memory_task_identity(self, root: str, task_ids: list[Any]) -> bool:
        if any(not isinstance(value, str) or not value or value != value.strip() or "\x00" in value for value in task_ids):
            self._send(400, {"success": False, "error": "invalid memory task identity", "terminal": True, "retryable": False})
            return False
        supplied = set(task_ids)
        if len(supplied) > 1:
            self._send(400, {"success": False, "error": "conflicting memory task identities", "terminal": True, "retryable": False})
            return False
        return not supplied or self._request_task(next(iter(supplied)), root) is not None

    def _bound_memory_scope_id(self, scope: services_module.AgentScope | None, scope_id: Any, task_id: Any = None) -> str | None:
        value = task_id if scope is services_module.AgentScope.TASK and scope_id in (None, "") else scope_id
        if value in (None, ""):
            return None
        if not isinstance(value, str) or value != value.strip() or "\x00" in value:
            raise ValueError("scope identity must be a canonical string")
        return value

    def _get_bound_memory_record(self, payload: dict[str, Any], record_id: str) -> Any | None:
        scope_val = services_module._parse_memory_scope(payload.get("scope"))
        scope_id_val = payload.get("scope_id")
        requested_root = payload.get("root")
        project_identity = self._memory_project_identity(requested_root)
        if requested_root and project_identity is None:
            return None
        root_val, repository_id_val = project_identity or (None, None)
        task_id_val = payload.get("task_id")
        session_id_val = payload.get("session_id")
        clone_id_val = payload.get("clone_id")
        worktree_id_val = payload.get("worktree_id")
        branch_val = payload.get("branch")
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
            return None
        if scope_val is None:
            scope_val = services_module.AgentScope.GLOBAL
        scope_id_val = self._bound_memory_scope_id(scope_val, scope_id_val, task_id_val)
        if scope_val is services_module.AgentScope.TASK:
            task_id_val = scope_id_val
        elif scope_val is services_module.AgentScope.SESSION:
            session_id_val = scope_id_val
        rec = services_module.APP.agent_memory.get(
            record_id,
            scope=scope_val,
            scope_id=str(scope_id_val) if scope_id_val is not None else None,
            root=str(root_val) if root_val else None,
            repository_id=str(repository_id_val) if repository_id_val else None,
            task_id=str(task_id_val) if task_id_val else None,
            session_id=str(session_id_val) if session_id_val else None,
            clone_id=str(clone_id_val) if clone_id_val else None,
            worktree_id=str(worktree_id_val) if worktree_id_val else None,
            branch=str(branch_val) if branch_val else None,
        )
        return rec


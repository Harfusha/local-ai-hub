from __future__ import annotations

from typing import Any


def handle_agent_state_memory(self: Any, payload: dict[str, Any]) -> None:
    from . import http_server as services_module
    if not getattr(services_module.APP, "agent_memory", None) or not services_module.APP.agent_memory.state_store.enabled:
        self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
    action = payload.get("action", "")
    idempotency_key = str(payload.get("idempotency_key", "")).strip()
    actor = self._agent() or "agent"
    if action == "record":
        raw_record = payload.get("record")
        if raw_record is not None and not isinstance(raw_record, dict):
            self._send(400, {"success": False, "error": "memory record must be an object", "terminal": True, "retryable": False}); return
        requested_root = payload.get("root")
        if (
            not isinstance(requested_root, str)
            or not requested_root.strip()
            or not services_module.Path(requested_root).expanduser().is_absolute()
        ):
            self._send(400, {"success": False, "error": "memory record requires an explicit absolute root", "terminal": True, "retryable": False}); return
        rec_data = raw_record or {}
        value_supplied = "value" in rec_data if rec_data else "value" in payload
        if not rec_data:
            rec_data = {
                "kind": payload.get("kind", services_module.MemoryKind.FACT.value),
                # Resolve the scope below from the supplied identity.
                # Defaulting here to TASK made a repository-only
                # write impossible to read back by root.
                "scope": payload.get("scope"),
                "key": payload.get("key"),
                "value": payload.get("value"),
                "scope_id": str(payload.get("scope_id", "")),
                "confidence": payload.get("confidence", 1.0),
                "status": payload.get("status"),
                "source": payload.get("source", actor),
                "evidence_ids": payload.get("evidence_ids") or [],
                "sensitivity": payload.get("sensitivity", "normal"),
                "provenance": payload.get("provenance"),
                "expires_at": payload.get("expires_at"),
                "ttl_seconds": payload.get("ttl_seconds"),
            }
        if rec_data.get("scope") is not None and (not isinstance(rec_data["scope"], str) or not rec_data["scope"].strip()):
            self._send(400, {"success": False, "error": "memory record scope must be a non-empty string when provided", "terminal": True, "retryable": False}); return
        if not isinstance(rec_data.get("key"), str) or not rec_data["key"].strip():
            self._send(400, {"success": False, "error": "memory record requires a non-empty key", "terminal": True, "retryable": False}); return
        if not value_supplied:
            self._send(400, {"success": False, "error": "memory record requires an explicit value", "terminal": True, "retryable": False}); return
        try:
            raw_kind = str(rec_data.get("kind", services_module.MemoryKind.FACT.value)).lower()
            try:
                kind_val = services_module.MemoryKind(raw_kind)
            except ValueError:
                kind_val = services_module.MemoryKind.FACT
            raw_scope = rec_data.get("scope")
            requested_scope = services_module._parse_memory_scope(raw_scope)
            provenance = dict(rec_data.get("provenance") or {})
            project_identity = self._memory_project_identity(requested_root)
            if requested_root and project_identity is None:
                self._send(400, {"success": False, "error": "memory project identity could not be resolved", "terminal": True, "retryable": False}); return
            root_val, repository_id_val = project_identity or (None, None)
            scope_val, resolved_scope_id, ambiguous_scope = services_module._resolve_memory_scope(
                requested_scope,
                scope_id=rec_data.get("scope_id") or payload.get("scope_id"),
                root=root_val,
                repository_id=repository_id_val,
                task_id=payload.get("task_id") or rec_data.get("task_id"),
                session_id=payload.get("session_id") or rec_data.get("session_id"),
                clone_id=payload.get("clone_id") or rec_data.get("clone_id"),
                worktree_id=payload.get("worktree_id") or rec_data.get("worktree_id"),
                branch=payload.get("branch") or rec_data.get("branch"),
            )
            if ambiguous_scope:
                self._send(400, {"success": False, "error": "ambiguous memory scope identity", "terminal": True, "retryable": False}); return
            if (
                requested_scope is None
                and (root_val or repository_id_val)
                and kind_val in (
                    services_module.MemoryKind.FACT,
                    services_module.MemoryKind.DECISION,
                    services_module.MemoryKind.CONVENTION,
                    services_module.MemoryKind.PLAYBOOK,
                    services_module.MemoryKind.GOTCHA,
                )
            ):
                scope_val = services_module.AgentScope.REPOSITORY
                resolved_scope_id = str(root_val or repository_id_val)
            else:
                scope_val = scope_val or services_module.AgentScope.GLOBAL
            resolved_scope_id = self._bound_memory_scope_id(
                scope_val,
                resolved_scope_id,
                payload.get("task_id") or rec_data.get("task_id"),
            )
            raw_status = rec_data.get("status")
            status_val = None
            if raw_status:
                try:
                    status_val = services_module.MemoryStatus(str(raw_status).lower())
                except ValueError:
                    status_val = None
            record_expiry = rec_data.get("expires_at", payload.get("expires_at"))
            record_ttl = rec_data.get("ttl_seconds", payload.get("ttl_seconds"))
            if record_expiry is None and record_ttl is not None and float(record_ttl) > 0:
                record_expiry = services_module.time.time() + float(record_ttl)
            reserved_identity = {"root", "repository_id"}
            discarded_identity_fields = sorted(
                identity_key
                for identity_key in reserved_identity
                if identity_key in payload
                or identity_key in rec_data
                or identity_key in provenance
            )
            for identity_key in reserved_identity:
                provenance.pop(identity_key, None)
            provenance.pop("discarded_identity_fields", None)
            if root_val:
                provenance["root"] = root_val
            if repository_id_val:
                provenance["repository_id"] = repository_id_val
            if discarded_identity_fields:
                provenance["discarded_identity_fields"] = discarded_identity_fields
            for identity_key in (
                "task_id", "session_id", "clone_id", "worktree_id", "branch",
            ):
                identity_value = payload.get(identity_key) or rec_data.get(identity_key)
                if identity_value not in (None, ""):
                    provenance[identity_key] = str(identity_value)
            if scope_val is services_module.AgentScope.REPOSITORY:
                provenance = services_module._bind_repository_memory_provenance(
                    provenance,
                    root=str(root_val or ""),
                    project_context=services_module._trusted_project_context(str(root_val or "")),
                )
                project_context = services_module._trusted_project_context(str(root_val or ""))
                if project_context is not None and str(
                    getattr(project_context, "root", "") or ""
                ).strip():
                    resolved_scope_id = str(project_context.root)
            record = services_module.MemoryRecord.create(
                kind=kind_val,
                scope=scope_val,
                key=str(rec_data.get("key", "")),
                value=rec_data.get("value"),
                scope_id=str(resolved_scope_id or rec_data.get("scope_id", "")),
                confidence=float(rec_data.get("confidence", 1.0)),
                status=status_val,
                source=str(rec_data.get("source", actor)),
                evidence_ids=tuple(rec_data.get("evidence_ids") or ()),
                sensitivity=str(rec_data.get("sensitivity", "normal")),
                provenance=provenance,
                expires_at=(float(record_expiry) if record_expiry is not None else None),
                contradicts_record_id=rec_data.get("contradicts_record_id", payload.get("contradicts_record_id")),
                supersedes_record_id=rec_data.get("supersedes_record_id", payload.get("supersedes_record_id")),
                quarantine_reason=rec_data.get("quarantine_reason", payload.get("quarantine_reason")),
            )
            saved = services_module.APP.agent_memory.record(record, actor=actor, idempotency_key=idempotency_key)
            self._send(200, {"success": True, "record": saved.to_dict()}); return
        except Exception as exc:
            self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
    if action == "get":
        scope_raw = payload.get("scope")
        scope_val = services_module._parse_memory_scope(scope_raw)
        scope_id_val = payload.get("scope_id")
        requested_root = payload.get("root")
        project_identity = self._memory_project_identity(requested_root)
        if requested_root and project_identity is None:
            self._send(400, {"success": False, "error": "memory project identity could not be resolved", "terminal": True, "retryable": False}); return
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
            self._send(400, {"success": False, "error": "ambiguous memory scope identity", "terminal": True, "retryable": False}); return
        if scope_val is None:
            scope_val = services_module.AgentScope.GLOBAL
        scope_id_val = self._bound_memory_scope_id(scope_val, scope_id_val, task_id_val)
        if scope_val is services_module.AgentScope.TASK:
            task_id_val = scope_id_val
        elif scope_val is services_module.AgentScope.SESSION:
            session_id_val = scope_id_val
        rec = services_module.APP.agent_memory.get(
            str(payload.get("record_id", "")),
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
        if not rec:
            self._send(404, {"success": False, "error": "memory record not found", "terminal": True, "retryable": False}); return
        self._send(200, {"success": True, "record": rec.to_dict()}); return
    if action == "delete":
        record_id_val = str(payload.get("record_id", "")).strip()
        if not record_id_val:
            self._send(400, {"success": False, "error": "memory delete requires record_id", "terminal": True, "retryable": False}); return
        rec = self._get_bound_memory_record(payload, record_id_val)
        if not rec:
            if not payload.get("scope") and getattr(services_module.APP, "agent_memory", None) and getattr(services_module.APP.agent_memory, "state_store", None) and services_module.APP.agent_memory.state_store.db_path.exists():
                try:
                    con = services_module.connect_sqlite(services_module.APP.agent_memory.state_store.db_path, timeout_seconds=5.0, read_only=True)
                    try:
                        row = con.execute("SELECT scope FROM agent_memory_records WHERE record_id = ?", (record_id_val,)).fetchone()
                        if row:
                            self._send(400, {"success": False, "error": "memory delete requires an explicit scope identity", "terminal": True, "retryable": False}); return
                    finally:
                        con.close()
                except Exception:
                    pass
            self._send(404, {"success": False, "error": "memory record not found", "terminal": True, "retryable": False}); return
        requested_root = payload.get("root")
        project_identity = self._memory_project_identity(requested_root)
        if requested_root and project_identity is None:
            self._send(400, {"success": False, "error": "memory project identity could not be resolved", "terminal": True, "retryable": False}); return
        root_val, repository_id_val = project_identity or (None, None)
        requested_scope = services_module._parse_memory_scope(payload.get("scope"))
        scope_val, scope_id_val, ambiguous_scope = services_module._resolve_memory_scope(
            requested_scope,
            scope_id=payload.get("scope_id"),
            root=root_val,
            repository_id=repository_id_val,
            task_id=payload.get("task_id"),
            session_id=payload.get("session_id"),
            clone_id=payload.get("clone_id"),
            worktree_id=payload.get("worktree_id"),
            branch=payload.get("branch"),
        )
        if ambiguous_scope:
            self._send(400, {"success": False, "error": "ambiguous memory scope identity", "terminal": True, "retryable": False}); return
        if scope_val is None:
            scope_val = services_module.AgentScope.GLOBAL
        if scope_val is services_module.AgentScope.WORKTREE:
            self._send(403, {"success": False, "error": "worktree-scoped memory delete requires verified worktree scope", "terminal": True, "retryable": False}); return
        bound_scope_id = self._bound_memory_scope_id(
            scope_val,
            scope_id_val,
            payload.get("task_id"),
        )
        bound_task_id = (
            bound_scope_id
            if scope_val is services_module.AgentScope.TASK
            else payload.get("task_id")
        )
        deleted = services_module.APP.agent_memory.delete(
            record_id_val,
            scope=scope_val,
            scope_id=str(bound_scope_id) if bound_scope_id is not None else None,
            root=str(root_val or "") or None,
            repository_id=str(repository_id_val or "") or None,
            task_id=str(bound_task_id or "") or None,
            session_id=str(payload.get("session_id") or "") or None,
            clone_id=str(payload.get("clone_id") or "") or None,
            worktree_id=str(payload.get("worktree_id") or "") or None,
            branch=str(payload.get("branch") or "") or None,
        )
        self._send(200 if deleted else 404, {
            "success": bool(deleted),
            "deleted": bool(deleted),
            "record_id": record_id_val,
            **({} if deleted else {"error": "memory record not found", "terminal": True, "retryable": False}),
        }); return
    if action == "find":
        scope_raw = payload.get("scope")
        scope_val = services_module._parse_memory_scope(scope_raw)
        key_val = str(payload["key"]) if payload.get("key") else None
        query_val = str(payload["query"]) if payload.get("query") else None
        status_val = services_module.MemoryStatus(str(payload["status"])) if payload.get("status") else None
        limit_val = services_module._memory_query_limit(payload.get("limit", 100))
        scope_id_val = payload.get("scope_id")
        requested_root = payload.get("root")
        project_identity = self._memory_project_identity(requested_root)
        if requested_root and project_identity is None:
            self._send(400, {"success": False, "error": "memory project identity could not be resolved", "terminal": True, "retryable": False}); return
        root_val, repository_id_val = project_identity or (None, None)
        task_id_val = payload.get("task_id")
        session_id_val = payload.get("session_id")
        clone_id_val = payload.get("clone_id")
        worktree_id_val = payload.get("worktree_id")
        branch_val = payload.get("branch")
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
        )
        self._send(200, {"success": True, "records": [r.to_dict() for r in records]}); return
    def _memory_mutation_identity() -> tuple[dict[str, Any] | None, str | None]:
        scope_val = services_module._parse_memory_scope(payload.get("scope"))
        scope_id_val = payload.get("scope_id")
        requested_root = payload.get("root")
        project_identity = self._memory_project_identity(requested_root)
        if requested_root and project_identity is None:
            return None, "memory project identity could not be resolved"
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
            return None, "ambiguous memory scope identity"
        scope_id_val = self._bound_memory_scope_id(scope_val, scope_id_val, task_id_val)
        if scope_val is services_module.AgentScope.TASK:
            task_id_val = scope_id_val
        elif scope_val is services_module.AgentScope.SESSION:
            session_id_val = scope_id_val
        if scope_val not in (None, services_module.AgentScope.GLOBAL) and not services_module._memory_lookup_has_identity(
            scope_id_val,
            root_val,
            repository_id_val,
            task_id_val,
            session_id_val,
            clone_id_val,
            worktree_id_val,
            branch_val,
        ) or scope_val is None:
            return None, "memory mutation requires explicit scope identity"
        return {
            "scope": scope_val,
            "scope_id": str(scope_id_val) if scope_id_val is not None else None,
            "root": str(root_val) if root_val else None,
            "repository_id": str(repository_id_val) if repository_id_val else None,
            "task_id": str(task_id_val) if task_id_val else None,
            "session_id": str(session_id_val) if session_id_val else None,
            "clone_id": str(clone_id_val) if clone_id_val else None,
            "worktree_id": str(worktree_id_val) if worktree_id_val else None,
            "branch": str(branch_val) if branch_val else None,
        }, None

    if action == "promote":
        identity, identity_error = _memory_mutation_identity()
        if identity_error:
            self._send(400, {"success": False, "error": identity_error, "terminal": True, "retryable": False}); return
        target_scope_str = str(payload.get("target_scope", "")).strip().lower()
        target_scope = services_module.AgentScope.parse(target_scope_str, default=None)
        if not target_scope:
            self._send(400, {"success": False, "error": f"invalid target scope '{target_scope_str}'", "terminal": True, "retryable": False}); return
        record_id_val = str(payload.get("record_id", "")).strip()
        if not record_id_val or not self._get_bound_memory_record(payload, record_id_val):
            self._send(404, {"success": False, "error": "memory record not found", "terminal": True, "retryable": False}); return
        if target_scope is services_module.AgentScope.GLOBAL:
            self._send(403, {"success": False, "error": "global memory promotion is unavailable through this endpoint", "terminal": True, "retryable": False}); return
        # Request payloads and agent headers are not user approval.
        # Only server-authenticated actor classification may authorize
        # a global promotion; current HTTP auth modes deliberately do
        # not identify a human approver, so they fail closed.
        approver = str(getattr(self, "_authorization_actor", "unrecognized"))
        try:
            promoted = services_module.APP.agent_memory.promote(
                record_id_val,
                target_scope,
                approver=approver,
                **(identity or {}),
            )
            self._send(200, {"success": True, "record": promoted.to_dict()}); return
        except services_module.ApprovalRequiredError as exc:
            self._send(403, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
        except ValueError as exc:
            self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
        except KeyError as exc:
            self._send(404, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
    if action == "quarantine":
        identity, identity_error = _memory_mutation_identity()
        if identity_error:
            self._send(400, {"success": False, "error": identity_error, "terminal": True, "retryable": False}); return
        reason = str(payload.get("reason", "manual quarantine"))
        record_id_val = str(payload.get("record_id", "")).strip()
        if not record_id_val or not self._get_bound_memory_record(payload, record_id_val):
            self._send(404, {"success": False, "error": "memory record not found", "terminal": True, "retryable": False}); return
        try:
            quarantined = services_module.APP.agent_memory.quarantine(
                record_id_val,
                reason=reason,
                actor=actor,
                **(identity or {}),
            )
        except KeyError as exc:
            self._send(404, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
        self._send(200, {"success": True, "record": quarantined.to_dict()}); return
    if action == "compact":
        self._send(403, {"success": False, "error": "memory compaction is unavailable through this endpoint", "terminal": True, "retryable": False}); return
    if action == "reap":
        self._send(403, {"success": False, "error": "memory reaping is unavailable through this endpoint", "terminal": True, "retryable": False}); return
    if action in {"relation_record", "record_relation"}:
        self._send(403, {"success": False, "error": "memory relations are unavailable through this endpoint", "terminal": True, "retryable": False}); return
    if action in {"relation_find", "find_relations"}:
        self._send(403, {"success": False, "error": "memory relations are unavailable through this endpoint", "terminal": True, "retryable": False}); return
    if action in {"relation_traverse", "traverse_graph"}:
        self._send(403, {"success": False, "error": "memory relations are unavailable through this endpoint", "terminal": True, "retryable": False}); return
    self._send(400, {"success": False, "error": f"unknown memory action '{action}'", "terminal": True, "retryable": False}); return

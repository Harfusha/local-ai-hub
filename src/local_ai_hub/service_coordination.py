from __future__ import annotations

from .services import (
    Any as Any,
    Path as Path,
    pagination_bounds_error as pagination_bounds_error,
    re as re,
    time as time,
)


class ServiceCoordinationMixin:
    def generate_tests_for_diff(self, root: str, diff: str | None = None, path: str | None = None) -> dict[str, Any]:
        return self.deterministic_operation("generate-tests-for-diff", root, {"diff": bool(diff), "path": path}, lambda: self.deterministic.generate_tests_for_diff(root, diff=diff, path=path))

    def cross_repo_contract(self, backend_root: str, frontend_root: str) -> dict[str, Any]:
        return self.deterministic_operation("cross-repo-contract", backend_root, {"frontend_root": frontend_root}, lambda: self.deterministic.cross_repo_contract(backend_root, frontend_root))

    def simulate_merge(self, root: str, source_branch: str, target_branch: str = "HEAD") -> dict[str, Any]:
        from .git_worktrees import simulate_git_merge
        return simulate_git_merge(root, source_branch, target_branch=target_branch)

    def pubsub_publish(self, topic: str, message: dict[str, Any] | str, sender: str = "agent") -> dict[str, Any]:
        from .agent_events import SwarmPubSub
        return SwarmPubSub.get_default(state_store=self.agent_state).publish(topic, message, sender=sender)

    def pubsub_poll(
        self,
        topic: str,
        since_timestamp: float = 0.0,
        limit: int = 50,
        after_seq: int = 0,
    ) -> dict[str, Any]:
        from .agent_events import SwarmPubSub
        bus = SwarmPubSub.get_default(state_store=self.agent_state)
        return bus.poll(
            topic,
            since_timestamp=since_timestamp,
            limit=limit,
            after_seq=after_seq,
        )

    def wait_for_event(
        self,
        topic: str,
        timeout: float = 60.0,
        filter_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from .agent_events import SwarmPubSub
        bus = SwarmPubSub.get_default(state_store=self.agent_state)
        return bus.wait_for_event(topic, timeout=timeout, filter_payload=filter_payload)

    def semaphore_acquire(
        self,
        name: str,
        owner: str = "agent",
        capacity: int = 1,
        ttl_seconds: float | None = None,
        purpose: str = "",
        timeout: float = 0.0,
    ) -> dict[str, Any]:
        if self.semaphores is None:
            from .agent_semaphores import SemaphoreStore
            from .agent_events import SwarmPubSub
            state_dir = Path(self.config.get("server", {}).get("state_dir", "~/.local-ai-hub/state")).expanduser()
            bus = SwarmPubSub.get_default(state_store=self.agent_state)
            self.semaphores = SemaphoreStore(state_dir / "agent_semaphores.sqlite", pubsub=bus)
        return self.semaphores.acquire(
            name=name, owner=owner, capacity=capacity,
            ttl_seconds=ttl_seconds, purpose=purpose, timeout=timeout,
        )

    def semaphore_release(self, name: str, lease_id: str, owner: str = "") -> dict[str, Any]:
        if self.semaphores is None:
            from .agent_semaphores import SemaphoreStore
            from .agent_events import SwarmPubSub
            state_dir = Path(self.config.get("server", {}).get("state_dir", "~/.local-ai-hub/state")).expanduser()
            bus = SwarmPubSub.get_default(state_store=self.agent_state)
            self.semaphores = SemaphoreStore(state_dir / "agent_semaphores.sqlite", pubsub=bus)
        return self.semaphores.release(name=name, lease_id=lease_id, owner=owner)

    def semaphore_status(self, name: str | None = None) -> dict[str, Any]:
        if self.semaphores is None:
            from .agent_semaphores import SemaphoreStore
            from .agent_events import SwarmPubSub
            state_dir = Path(self.config.get("server", {}).get("state_dir", "~/.local-ai-hub/state")).expanduser()
            bus = SwarmPubSub.get_default(state_store=self.agent_state)
            self.semaphores = SemaphoreStore(state_dir / "agent_semaphores.sqlite", pubsub=bus)
        return self.semaphores.status(name=name)

    def session_briefing(self, root: str, include: list[str] | None = None) -> dict[str, Any]:
        from .agent_tasks import _task_scope_root
        from .repo_plan.schema_validation import RepoPlanValidationError

        ws = self._plan_workspace(root, "session_briefing", {"include": include or []})
        selected = set(include or ["board", "plans", "active_tasks"])
        result: dict[str, Any] = {"success": True, "timestamp": time.time(),
                                  "root": str(ws.repo_root)}
        if "plans" in selected:
            result["plans"] = ws.list_plans()
        if "board" in selected or "plan_board" in selected:
            try:
                board = ws.get_board_view()
            except RepoPlanValidationError as exc:
                result["partial"] = True
                result.setdefault("warnings", []).append(f"Plan board unavailable: {exc}")
            else:
                counts = {name: len(items) for name, items in board["columns"].items()}
                counts["total"] = sum(counts.values())
                recent = [item for items in board["columns"].values() for item in items][:5]
                summary = {"success": True, "counts": counts, "by_status": counts,
                           "total_items": counts["total"], "source": "repo_plan",
                           "root": str(ws.repo_root)}
                result["board_summary"] = counts
                result["board"] = {"summary": summary, "recent_items": recent}
                result["plan_board"] = board["columns"]
        task_store = getattr(self, "task_store", None)
        if "active_tasks" in selected and task_store is not None:
            active_items = []
            for task in task_store.list_tasks(status=None, limit=100):
                if _task_scope_root(task) != str(ws.repo_root):
                    continue
                if task.status.value not in {"planned", "active", "waiting", "verifying"}:
                    continue
                active_items.append({"task_id": task.task_id,
                                     "goal": task.contract.goal,
                                     "status": task.status.value,
                                     "phase": task.checkpoint.phase})
                if len(active_items) >= 5:
                    break
            result["active_tasks"] = active_items
        return result

    def _plan_workspace(self, root: str, action: str, arguments: dict[str, Any]) -> Any:
        if (
            not isinstance(root, str)
            or not root
            or root != root.strip()
            or "\x00" in root
            or not Path(root).is_absolute()
        ):
            raise ValueError("root must be an explicit absolute repository directory")
        from .operation_contracts import validate_operation_arguments
        from .repository_scope import authorized_repository_root
        from .repo_plan.workspace import RepoPlanWorkspace

        error = validate_operation_arguments("local_ai_coord", action, {"root": root, **arguments})
        if error:
            raise ValueError(error)
        return RepoPlanWorkspace(authorized_repository_root(self.config, root))

    def plan_init(self, root: str = "") -> dict[str, Any]:
        return self._plan_workspace(root, "plan_init", {}).init_workspace()

    def plan_list(self, root: str = "", query: str = "", lifecycle: str | None = None,
                  limit: int = 5) -> dict[str, Any]:
        arguments = {"query": query, "limit": limit}
        if lifecycle is not None:
            arguments["lifecycle"] = lifecycle
        ws = self._plan_workspace(root, "plan_list", arguments)
        plans = ws.list_plans(**arguments)
        return {"success": True, "root": str(ws.repo_root), "plans": plans, "count": len(plans)}

    def plan_get(self, root: str = "", plan_id: str = "") -> dict[str, Any]:
        return self._plan_workspace(root, "plan_get", {"plan_id": plan_id}).get_plan(plan_id)

    def plan_create(self, root: str = "", plan_id: str = "", title: str = "",
                    description: str = "", lifecycle: str = "draft",
                    default_target_ref: str | None = "refs/heads/master",
                    spec_refs: list[dict[str, Any]] | None = None,
                    tasks: dict[str, Any] | None = None,
                    accountable_role: str | None = None, owner: str = "agent",
                    idempotency_key: str = "") -> dict[str, Any]:
        if not plan_id:
            import uuid
            plan_id = f"plan_{uuid.uuid4().hex[:12]}"
        elif not plan_id.startswith("plan_"):
            clean_plan = re.sub(r"[^A-Za-z0-9_-]", "_", plan_id).strip("_")
            plan_id = f"plan_{clean_plan}"[:80]
        arguments = dict(plan_id=plan_id, title=title, description=description,
                         lifecycle=lifecycle, default_target_ref=default_target_ref,
                         owner=owner, idempotency_key=idempotency_key)
        if spec_refs is not None:
            arguments["spec_refs"] = spec_refs
        if tasks is not None:
            arguments["tasks"] = tasks
        if accountable_role is not None:
            arguments["accountable_role"] = accountable_role
        return self._plan_workspace(root, "plan_create", arguments).create_plan(**arguments)

    def plan_update(self, root: str = "", plan_id: str = "", expected_revision: str = "",
                    owner: str = "agent", idempotency_key: str = "", **changes: Any) -> dict[str, Any]:
        arguments = dict(plan_id=plan_id, expected_revision=expected_revision, owner=owner,
                         idempotency_key=idempotency_key, **changes)
        return self._plan_workspace(root, "plan_update", arguments).update_plan(**arguments)

    def plan_task_edit(self, root: str = "", plan_id: str = "", task_id: str = "",
                       task_data: dict[str, Any] | None = None, expected_revision: str = "",
                       idempotency_key: str = "", owner: str = "agent") -> dict[str, Any]:
        arguments = dict(plan_id=plan_id, task_id=task_id, task_data=task_data,
                         expected_revision=expected_revision, idempotency_key=idempotency_key, owner=owner)
        ws = self._plan_workspace(root, "plan_task_edit", arguments)
        allowed = {"title", "description", "kind", "work_status", "depends_on", "clarifications",
                   "acceptance_criteria", "next_action", "blocker", "order", "accountable_role",
                   "work_phase", "spec_refs", "scope", "results", "deliveries"}
        if set(task_data) - allowed:
            raise ValueError(f"invalid task_data field: {sorted(set(task_data) - allowed)[0]}")
        return ws.edit_task(plan_id=plan_id, task_id=task_id, expected_revision=expected_revision,
                            idempotency_key=idempotency_key, owner=owner, **task_data)

    def plan_task_delete(self, root: str = "", plan_id: str = "", task_id: str = "",
                         expected_revision: str = "", idempotency_key: str = "",
                         owner: str = "agent") -> dict[str, Any]:
        arguments = dict(plan_id=plan_id, task_id=task_id, expected_revision=expected_revision,
                         idempotency_key=idempotency_key, owner=owner)
        return self._plan_workspace(root, "plan_task_delete", arguments).delete_task(**arguments)

    def plan_validate(self, root: str = "", plan_id: str = "") -> dict[str, Any]:
        return self._plan_workspace(root, "plan_validate", {"plan_id": plan_id}).validate_plan(plan_id)

    def plan_archive(self, root: str = "", plan_id: str = "", expected_revision: str = "",
                     idempotency_key: str = "", owner: str = "agent") -> dict[str, Any]:
        arguments = dict(plan_id=plan_id, expected_revision=expected_revision,
                         idempotency_key=idempotency_key, owner=owner)
        return self._plan_workspace(root, "plan_archive", arguments).archive_plan(**arguments)

    def plan_board_view(self, root: str = "", plan_id: str = "", query: str = "",
                        worktree_id: str = "") -> dict[str, Any]:
        arguments = dict(plan_id=plan_id, query=query, worktree_id=worktree_id)
        return self._plan_workspace(root, "plan_board_view", arguments).get_board_view(**arguments)

    def plan_adopt_legacy_board(self, root: str = "", plan_id: str = "", title: str = "",
                               owner: str = "agent", idempotency_key: str = "") -> dict[str, Any]:
        arguments = dict(plan_id=plan_id, title=title, owner=owner, idempotency_key=idempotency_key)
        ws = self._plan_workspace(root, "plan_adopt_legacy_board", arguments)
        from .legacy_board_archive import ARCHIVE_NAME, read_legacy_board_archive
        from .repo_plan.schema_validation import RepoPlanConflictError

        state_dir = Path(self.config.get("server", {}).get("state_dir", "~/.local-ai-hub/state")).expanduser()
        if not (state_dir / ARCHIVE_NAME).is_file():
            raise RepoPlanConflictError("no update-migrated global board archive is available")
        try:
            items = read_legacy_board_archive(state_dir)
        except (OSError, ValueError) as exc:
            raise RepoPlanConflictError(f"global board archive cannot be imported: {exc}") from exc
        if len(items) > 1000:
            raise RepoPlanConflictError("legacy board exceeds the 1000-item plan capacity")
        return ws.adopt_legacy_board_items(board_items=items, **arguments)

    def plan_bind_task(self, root: str = "", task_id: str = "", plan_id: str = "",
                       plan_task_id: str = "", expected_revision: str | None = None,
                       session_id: str = "") -> dict[str, Any]:
        from .repo_plan.agent_bridge import bind_plan_execution
        arguments = dict(task_id=task_id, plan_id=plan_id, plan_task_id=plan_task_id, session_id=session_id)
        if expected_revision is not None:
            arguments["expected_revision"] = expected_revision
        ws = self._plan_workspace(root, "plan_bind_task", arguments)
        return bind_plan_execution(self.task_store, root=str(ws.repo_root), **arguments)

    def plan_reconcile_steering(self, root: str = "", task_id: str = "", steering_id: str = "",
                                spec_rel_path: str = "", spec_content: str = "",
                                acceptance_criteria: list[str] | None = None,
                                expected_revision: str = "", expected_spec_revision: str = "",
                                summary: str = "") -> dict[str, Any]:
        from .repo_plan.agent_bridge import reconcile_task_steering
        arguments = dict(task_id=task_id, steering_id=steering_id, spec_rel_path=spec_rel_path,
                         spec_content=spec_content, acceptance_criteria=acceptance_criteria,
                         expected_revision=expected_revision, expected_spec_revision=expected_spec_revision,
                         summary=summary)
        ws = self._plan_workspace(root, "plan_reconcile_steering", arguments)
        return reconcile_task_steering(self.task_store, root=str(ws.repo_root), **arguments)

    def synthesize_commit(self, root: str, hint: str = "", task_id: str = "") -> dict[str, Any]:
        tasks_data: list[dict[str, Any]] = []
        receipts_data: list[dict[str, Any]] = []

        if self.task_store is not None:
            if task_id:
                t = self.task_store.get(task_id)
                if t:
                    tasks_data.append(t.to_dict())
            else:
                active = self.task_store.list_tasks(status=None, limit=5)
                for t in active:
                    tasks_data.append(t.to_dict())

        if self.verification_store is not None:
            tids = [task_id] if task_id else [str(t.get("task_id")) for t in tasks_data if t.get("task_id")]
            for tid in tids[:5]:
                comp = self.verification_store.completion(tid)
                for r in comp.receipts:
                    if r.passed:
                        receipts_data.append(r.to_dict())

        params = {"hint": hint, "task_id": task_id, "tasks_count": len(tasks_data), "receipts_count": len(receipts_data)}
        return self.deterministic_operation(
            "commit-synthesis",
            root,
            params,
            lambda: self.deterministic.synthesize_commit(
                root, hint, task_id=task_id, tasks=tasks_data, receipts=receipts_data
            ),
        )

    def code_inspect_symbol(self, root: str, symbol: str) -> dict[str, Any]:
        if self.code_index is None:
            return {"success": False, "error": "code index disabled"}
        return self._repo_cached("ci:inspect_symbol", root, {"symbol": symbol}, lambda: self.code_index.inspect_symbol(root, symbol))

    def code_find_symbol(self, root: str, pattern: str, depth: int = 0, include_body: bool = False, include_info: bool = True, relative_path: str | None = None, limit: int = 30) -> dict[str, Any]:
        if self.code_index is None:
            return {"success": False, "error": "code index disabled"}
        params = {"pattern": pattern, "depth": depth, "include_body": include_body, "include_info": include_info, "path": relative_path, "limit": limit}
        return self._repo_cached("ci:find_symbol", root, params, lambda: self.code_index.find_symbol(root, pattern, depth=depth, include_body=include_body, include_info=include_info, relative_path=relative_path, limit=limit))

    def code_find_declaration(self, root: str, symbol: str, path: str | None = None) -> dict[str, Any]:
        if self.code_index is None:
            return {"success": False, "error": "code index disabled"}
        return self._repo_cached("ci:find_declaration", root, {"symbol": symbol, "path": path}, lambda: self.code_index.find_declaration(root, symbol, path=path))

    def code_find_implementations(self, root: str, symbol: str, path: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        if self.code_index is None:
            return {"success": False, "error": "code index disabled"}
        bounds_error = pagination_bounds_error(limit, offset)
        if bounds_error:
            return {"success": False, "status_code": 400, "terminal": True, "retryable": False, "error": bounds_error}
        return self._repo_cached(
            "ci:find_implementations", root,
            {"symbol": symbol, "path": path, "limit": limit, "offset": offset},
            lambda: self.code_index.find_implementations(root, symbol, path=path, limit=limit, offset=offset),
        )

    def code_find_referencing_symbols(self, root: str, symbol: str, path: str | None = None) -> dict[str, Any]:
        if self.code_index is None:
            return {"success": False, "error": "code index disabled"}
        return self._repo_cached("ci:find_referencing_symbols", root, {"symbol": symbol, "path": path}, lambda: self.code_index.find_referencing_symbols(root, symbol, path=path))

    def code_symbols_overview(self, root: str, path: str, depth: int = 1) -> dict[str, Any]:
        if self.code_index is None:
            return {"success": False, "error": "code index disabled"}
        return self._repo_cached("ci:symbols_overview", root, {"path": path, "depth": depth}, lambda: self.code_index.get_symbols_overview(root, path, depth=depth))

    def code_diagnostics(self, root: str, path: str) -> dict[str, Any]:
        if self.code_index is None:
            return {"success": False, "error": "code index disabled"}
        return self._repo_cached("ci:diagnostics", root, {"path": path}, lambda: self.code_index.get_diagnostics_for_file(root, path))

    def audit_dependencies(self, root: str) -> dict[str, Any]:
        if self.deterministic is None:
            return {"success": False, "error": "deterministic engine disabled"}
        return self.deterministic_operation("audit-dependencies", root, {}, lambda: self.deterministic.audit_dependencies(root))

    def symbol_callgraph(self, root: str, symbol: str | None = None, limit: int = 50) -> dict[str, Any]:
        if self.deterministic is None:
            return {"success": False, "error": "deterministic engine disabled"}
        return self.deterministic_operation("symbol-callgraph", root, {"symbol": symbol, "limit": limit}, lambda: self.deterministic.symbol_callgraph(root, symbol, limit))

    def repo_impact(self, root: str, base: str = "HEAD", staged: bool = False, max_symbols: int = 48, max_dependents: int = 30) -> dict[str, Any]:
        diff_result = None
        def compute() -> dict[str, Any]:
            nonlocal diff_result
            # Local AI deterministic primary path: refresh only changed files in the code
            # index, then resolve dependents/tests through SQLite refs/edges. A full
            # repository scan is only a bounded fallback for sparse indexes.
            if self.code_index is not None and hasattr(self.code_index, "impact"):
                diff = self.repo_tools.git_diff(root, base, staged, max_tokens=24000)
                diff_result = diff if diff.get("success") else None
                if diff.get("terminal"):
                    return diff
                if diff.get("success"):
                    changed = [str(x) for x in diff.get("changed_files", [])]
                    if not changed:
                        return {
                            "success": True, "root": str(Path(root).expanduser().resolve()), "changed_files": [],
                            "changed_symbols": [], "likely_dependents": [], "suggested_tests": [],
                            "risk": {"score": 0, "level": "low", "reasons": ["no changed files"]}, "method": "code-index",
                        }
                    try:
                        indexed = self.code_index.impact(root, changed, max_symbols, max_dependents)
                    except Exception:
                        indexed = {"success": False}
                    if indexed.get("success") and (indexed.get("changed_symbols") or float(indexed.get("confidence", 0.0) or 0.0) >= 0.70):
                        det = {}
                        if self.deterministic is not None:
                            try: det = self.deterministic.diff_facts(str(diff.get("diff", "")))
                            except Exception: det = {}
                        signals = det.get("risk_signals", {}) if isinstance(det, dict) else {}
                        score = 0; reasons: list[str] = []
                        if len(changed) >= 6: score += 2; reasons.append("multi-file change")
                        if det.get("manifest_files"): score += 2; reasons.append("manifest/build metadata changed")
                        if det.get("breaking_changes"): score += 4; reasons.append(f"{len(det['breaking_changes'])} breaking change(s) detected")
                        for key, weight, label in (("security",2,"security-sensitive code"),("concurrency",2,"concurrency-sensitive code"),("database",1,"database/persistence code"),("shell-exec",2,"process/shell execution"),("dynamic-eval",3,"dynamic evaluation")):
                            if int(signals.get(key, 0) or 0): score += weight; reasons.append(label)
                        if len(indexed.get("likely_dependents", [])) >= 10: score += 1; reasons.append("many indexed dependents")
                        if not indexed.get("suggested_tests") and any(Path(x).suffix.lower() in self.repo_tools.extensions for x in changed):
                            score += 1; reasons.append("no indexed tests found")
                        level = "high" if score >= 5 else "medium" if score >= 2 else "low"
                        if not reasons: reasons.append("localized indexed change")
                        return {
                            "success": True, "root": str(Path(root).expanduser().resolve()), "changed_files": changed,
                            "changed_symbols": indexed.get("changed_symbols", []), "likely_dependents": indexed.get("likely_dependents", []),
                            "suggested_tests": indexed.get("suggested_tests", []), "risk": {"score": score, "level": level, "reasons": reasons},
                            "diff_sha256": diff.get("diff_sha256"), "method": "code-index", "index_confidence": indexed.get("confidence", 0.0),
                            "deterministic_diff": det,
                        }
            fallback = self.repo_tools.impact_analysis(
                root, base, staged, max_symbols, max_dependents,
                diff_result=diff_result,
            )
            if isinstance(fallback, dict): fallback.setdefault("method", "scan-fallback")
            return fallback
        return self._repo_cached(
            "impact", root, {"base": base, "staged": staged, "max_symbols": max_symbols, "max_dependents": max_dependents}, compute,
        )

    def repo_diff(self, root: str, base: str = "HEAD", staged: bool = False, max_tokens: int = 10000,
                  *, path: str | None = None) -> dict[str, Any]:
        return self._repo_cached(
            "diff", root, {"base": base, "staged": staged, "max_tokens": max_tokens, "path": path},
            lambda: self.repo_tools.git_diff(root, base, staged, max_tokens, path=path),
        )


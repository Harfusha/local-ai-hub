from __future__ import annotations

from typing import Any


def handle_agent_state_incidents(self: Any, payload: dict[str, Any]) -> None:
    from . import http_server as services_module
    if not getattr(services_module.APP, "agent_incidents", None) or not services_module.APP.agent_incidents.state_store.enabled:
        self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
    action = payload.get("action", "")
    if action not in {"decision", "record", "find"}:
        self._send(403, {"success": False, "error": "incident action requires a scoped mutation contract", "terminal": True, "retryable": False}); return
    if action == "decision":
        fp = services_module.IncidentFingerprint.from_dict(payload["fingerprint"])
        rev = payload.get("state_revision", "")
        decision = services_module.APP.agent_incidents.retry_decision(
            fp,
            rev,
            root=str(payload.get("root", "")),
        )
        self._send(200, {"success": True, "decision": decision.to_dict()}); return
    if action == "record":
        root_cause = payload.get("root_cause", "")
        verified_fix = payload.get("verified_fix", "")
        if str(verified_fix).strip().casefold() == "resolved":
            self._send(400, {
                "success": False,
                "error": "verified_fix must describe a verified fix",
                "terminal": True,
                "retryable": False,
            }); return
        msg = payload.get("message", "")
        op = payload.get("operation_class", "agent")
        rev = payload.get("state_revision", "")
        evidence_ids = tuple(payload.get("evidence_ids", ()))
        aff_paths = tuple(payload.get("affected_paths", ()))
        outcome = services_module.ToolOutcome(
            tool_name=op, error=msg or "recorded incident", exit_code=payload.get("exit_code", 1),
            state_revision=rev, evidence_ids=evidence_ids,
            metadata={"root_cause": root_cause, "verified_fix": verified_fix},
            affected_paths=aff_paths,
            repository_root=str(payload.get("root", "")),
        )
        inc = services_module.APP.agent_incidents.capture(outcome)
        if inc and verified_fix:
            inc = services_module.APP.agent_incidents.resolve(inc.incident_id, verified_fix=verified_fix, root_cause=root_cause or None)
        self._send(200, {"success": True, "incident": inc.to_dict() if inc else None}); return
    if action == "find":
        query = payload["query"]
        limit_val = payload.get("limit", 100)
        scoped = services_module.APP.agent_incidents.find_negative_knowledge(
            query,
            limit=limit_val,
            root=payload["root"],
        )
        self._send(200, {"success": True, "negative_knowledge": scoped, "incidents": scoped}); return

def handle_agent_state_verification(self: Any, payload: dict[str, Any]) -> None:
    from . import http_server as services_module
    if not getattr(services_module.APP, "agent_verification", None) or not services_module.APP.agent_verification.state_store.enabled:
        self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
    action = payload.get("action", "")
    if action == "receipt":
        rcpt_data = payload.get("receipt")
        if not isinstance(rcpt_data, dict):
            self._send(400, {"success": False, "error": "receipt must be an object", "terminal": True, "retryable": False}); return
        receipt_task_id = str(rcpt_data.get("task_id", "") or "").strip()
        request_task_id = str(payload.get("task_id", "") or "").strip()
        if request_task_id and receipt_task_id and request_task_id != receipt_task_id:
            self._send(404, {"success": False, "error": "task not found", "terminal": True, "retryable": False}); return
        if not self._require_scoped_task(receipt_task_id or request_task_id):
            return
        if type(rcpt_data.get("passed")) is not bool:
            self._send(400, {"success": False, "error": "receipt.passed must be boolean", "terminal": True, "retryable": False}); return
        try:
            if "receipt_id" in rcpt_data:
                rcpt = services_module.VerificationReceipt.from_dict(rcpt_data)
            else:
                rcpt = services_module.VerificationReceipt.create(
                    task_id=str(rcpt_data.get("task_id", "")),
                    criterion=str(rcpt_data.get("criterion", "")),
                    passed=rcpt_data["passed"],
                    change_intent_id=str(rcpt_data.get("change_intent_id", "")),
                    evidence_id=str(rcpt_data.get("evidence_id", "")),
                    command_id=str(rcpt_data.get("command_id", "")),
                    repository_revision=str(rcpt_data.get("repository_revision", "")),
                    owner=self._agent() or "agent",
                    expires_at=rcpt_data.get("expires_at"),
                    details=rcpt_data.get("details"),
                )
            saved = services_module.APP.agent_verification.record(rcpt)
            collector = getattr(services_module.APP, "training_collector", None)
            if collector and getattr(collector, "enabled", False):
                try:
                    import json
                    collector.record_dpo_pair(
                        category="verification_receipt",
                        prompt=f"Task {saved.task_id} criterion: {saved.criterion}",
                        chosen=json.dumps(saved.to_dict()),
                        rejected="",
                        verification_passed=bool(saved.passed),
                        metadata={"receipt_id": str(saved.receipt_id), "evidence_id": str(saved.evidence_id)},
                    )
                except Exception:
                    pass
            self._send(200, {"success": True, "receipt": saved.to_dict()}); return
        except Exception as exc:
            self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
    if action == "native_receipt":
        try:
            task_id = str(payload.get("task_id", "")).strip()
            criterion = str(payload.get("criterion", "")).strip()
            command_id = payload.get("command_id")
            root = str(payload.get("root", "")).strip()
            if not task_id or not criterion or not command_id or not root:
                raise ValueError("task_id, criterion, command_id and explicit root are required")
            from .repo_plan.agent_bridge import record_authentic_native_receipt

            imported = record_authentic_native_receipt(
                services_module.APP.agent_tasks, services_module.APP.agent_verification, services_module.APP.artifacts,
                task_id, criterion, None, root, command_id=command_id,
            )
            collector = getattr(services_module.APP, "training_collector", None)
            if collector and getattr(collector, "enabled", False):
                try:
                    import json
                    rcpt_obj = imported["receipt"]
                    collector.record_dpo_pair(
                        category="verification_receipt",
                        prompt=f"Task {rcpt_obj.task_id} criterion: {rcpt_obj.criterion}",
                        chosen=json.dumps(rcpt_obj.to_dict()),
                        rejected="",
                        verification_passed=bool(rcpt_obj.passed),
                        metadata={"receipt_id": str(imported.get("receipt_id")), "evidence_id": str(imported.get("evidence_id"))},
                    )
                except Exception:
                    pass
            self._send(200, {"success": True, "receipt": imported["receipt"].to_dict(),
                             "receipt_id": imported["receipt_id"],
                             "evidence_id": imported["evidence_id"]}); return
        except Exception as exc:
            self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
    if action == "completion":
        task_id = str(payload.get("task_id", "")).strip()
        if not self._require_scoped_task(task_id):
            return
        current_revision = ""
        root = str(payload.get("root", "")).strip()
        requested_revision = payload.get("repository_revision", "")
        has_requested_revision = bool(requested_revision)
        repo_tools = getattr(services_module.APP, "repo_tools", None)
        if root or requested_revision:
            current_revision, revision_stop = services_module._completion_revision_or_stop(
                root, repo_tools, getattr(services_module.APP, "repo_state", None)
            )
            if revision_stop:
                self._send(409, revision_stop); return
        if has_requested_revision and requested_revision != current_revision:
            self._send(409, {
                "success": False,
                "terminal": True,
                "retryable": False,
                "stop_code": "completion_repository_revision_mismatch",
                "error": "requested repository revision does not match the current repository revision",
            }); return
        verifier = services_module.APP.agent_verification
        from .verified_execution import EXECUTION_KEY
        from .verification_rules import evaluate_project_completion

        task_store = getattr(verifier, "task_store", None)
        task = task_store.get(task_id) if task_store is not None else None
        if (task is not None and EXECUTION_KEY in task.contract.slo_profile and current_revision):
            res = evaluate_project_completion(
                verifier, task_id, root=root, current_revision=current_revision,
                state_dir=verifier.state_store.db_path.parent,
            )
        else:
            res = verifier.completion(task_id, current_revision=current_revision)
        if not current_revision and any(
            str(getattr(receipt, "repository_revision", "") or "").strip()
            for receipt in res.receipts
        ):
            _, revision_stop = services_module._completion_revision_or_stop(
                root, repo_tools, getattr(services_module.APP, "repo_state", None)
            )
            self._send(409, revision_stop or {
                "success": False,
                "terminal": True,
                "retryable": False,
                "stop_code": "completion_repository_revision_unavailable",
                "error": "completion requires a repository snapshot with a non-empty revision",
            }); return
        self._send(200, {"success": True, "completion": res.to_dict()}); return
    if action == "export":
        task_id = str(payload.get("task_id", "")).strip()
        if not self._require_scoped_task(task_id):
            return
        format_val = str(payload.get("format", "markdown")).strip().lower()
        res = services_module.APP.agent_verification.export_receipts(task_id, format=format_val)
        self._send(200, res); return
    self._send(400, {"success": False, "error": f"unknown verification action '{action}'", "terminal": True, "retryable": False}); return

def handle_agent_state_context(self: Any, payload: dict[str, Any]) -> None:
    from . import http_server as services_module
    if not getattr(services_module.APP, "agent_context", None) or not services_module.APP.agent_context.state_store.enabled:
        self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
    action = payload.get("action", "")
    if action == "compile":
        requested_mode = self._context_retrieval_mode(payload)
        if requested_mode is None:
            self._send(400, {
                "success": False,
                "error": "context mode must be adaptive, full or fast",
                "terminal": True,
                "retryable": False,
            }); return
        req = services_module.build_context_request(payload, project_context=services_module._trusted_project_context(str(payload.get("root") or "")))
        if not req.task_id:
            self._send(400, {
                "success": False,
                "error": "task_id is required for context compilation",
                "terminal": True,
                "retryable": False,
            }); return
        compiled = services_module.APP.agent_context.compile(req)
        since_hash = str(payload.get("since_hash") or "").strip()
        compact_mode = bool(payload.get("compact", False))
        root = req.root.strip()
        if root:
            from .agent_consistency import ConsistencyRequest

            repository_query = str(payload.get("query", "")).strip()
            if not repository_query:
                repository_query = " ".join(req.focus[:8])
            repository_mode = requested_mode

            repository_request = ConsistencyRequest(root=root, task_id=req.task_id, session_id=req.session_id, query=repository_query, phase=req.phase, focus=req.focus, workspace=str(payload.get("workspace", "")), preload_profile=req.preload_profile, token_budget=req.token_budget, changed_paths=req.changed_paths, base=str(payload.get("base", "HEAD")), staged=bool(payload.get("staged", False)), override_reason=str(payload.get("override_reason", "")), approval=payload.get("approval", ""))
            try:
                repository = services_module.APP.services.adaptive_context_pack(
                    repository_request,
                    mode=repository_mode,
                    since_hash=str(payload.get("repo_since_hash", "")),
                )
            except Exception as exc:
                repository = {
                    "success": False,
                    "terminal": False,
                    "retryable": True,
                    "error": f"repository context unavailable: {exc}",
                }
            task_context = services_module.compose_task_context(
                task_id=req.task_id,
                compiled=compiled,
                repository=repository if isinstance(repository, dict) else {
                    "success": False,
                    "terminal": True,
                    "retryable": True,
                    "error": "repository context response must be an object",
                },
                token_budget=req.token_budget,
                repository_required=True,
            )
            if since_hash and since_hash == task_context["etag"]:
                self._send(200, {
                    "success": True,
                    "unchanged": True,
                    "etag": task_context["etag"],
                    "context_id": task_context["context_id"],
                    "estimated_tokens": 10,
                }); return
            response = {
                "success": bool(task_context["success"]),
                "complete": bool(task_context["complete"]),
                "partial": bool(task_context["partial"]),
                "context_id": task_context["context_id"],
                "etag": task_context["etag"],
                "context": compiled.to_dict(compact=compact_mode),
                "task_context": task_context,
                "text": task_context["text"],
                "evidence_ids": task_context["evidence_ids"],
                "repo_revision": task_context["repo_revision"],
                "source_layers": task_context["source_layers"],
                "stale": task_context["stale"],
                "truncated": task_context["truncated"],
                "omitted_sections": task_context["omitted_sections"],
                "next_action": task_context["next_action"],
                "estimated_tokens": task_context["estimated_tokens"],
                "warnings": task_context["warnings"],
            }
            from .context_delivery import attach_compiled_context_artifact
            response = attach_compiled_context_artifact(
                response, services_module.APP.artifacts, root=req.root,
                coordination_id=req.coordination_id, session_id=req.session_id,
            )
            self._send(200, response); return
        task_context = services_module.compose_task_context(
            task_id=req.task_id,
            compiled=compiled,
            repository={},
            token_budget=req.token_budget,
            repository_required=False,
        )
        etag = task_context["etag"]
        if since_hash and since_hash == etag:
            self._send(200, {
                "success": True,
                "complete": True,
                "unchanged": True,
                "etag": etag,
                "context_id": task_context["context_id"],
                "estimated_tokens": 10,
            }); return
        response = {
            "success": bool(task_context["success"]),
            "complete": bool(task_context["complete"]),
            "partial": bool(task_context["partial"]),
            "context_id": task_context["context_id"],
            "etag": etag,
            "context": compiled.to_dict(compact=compact_mode),
            "task_context": task_context,
            "text": task_context["text"],
            "evidence_ids": task_context["evidence_ids"],
            "source_layers": task_context["source_layers"],
            "stale": task_context["stale"],
            "truncated": task_context["truncated"],
            "omitted_sections": task_context["omitted_sections"],
            "next_action": task_context["next_action"],
            "estimated_tokens": task_context["estimated_tokens"],
            "warnings": task_context["warnings"],
        }
        from .context_delivery import attach_compiled_context_artifact
        response = attach_compiled_context_artifact(
            response, services_module.APP.artifacts, root=req.root,
            coordination_id=req.coordination_id, session_id=req.session_id,
        )
        self._send(200, response); return
    self._send(400, {"success": False, "error": f"unknown context action '{action}'", "terminal": True, "retryable": False}); return

def handle_agent_state_learning(self: Any, payload: dict[str, Any]) -> None:
    from . import http_server as services_module
    if not getattr(services_module.APP, "agent_learning", None) or not services_module.APP.agent_learning.state_store.enabled:
        self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
    action = payload.get("action", "")
    if action == "create_candidate":
        cand_data = payload.get("candidate") or {}
        try:
            if "candidate_id" in cand_data:
                cand = services_module.ImprovementCandidate.from_dict(cand_data)
            else:
                cand = services_module.ImprovementCandidate.create(
                    name=str(cand_data.get("name", "")),
                    baseline_version=str(cand_data.get("baseline_version", "baseline")),
                    candidate_version=str(cand_data.get("candidate_version", "candidate")),
                    slo_thresholds=cand_data.get("slo_thresholds"),
                    metrics=cand_data.get("metrics"),
                )
            saved = services_module.APP.agent_learning.create_candidate(cand)
            self._send(200, {"success": True, "candidate": saved.to_dict()}); return
        except Exception as exc:
            self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
    if action == "promote":
        candidate_id = str(payload.get("candidate_id", "")).strip()
        approval_receipt = payload.get("approval_receipt")
        try:
            receipt = approval_receipt if isinstance(approval_receipt, services_module.Mapping) else None
            dec = services_module.APP.agent_learning.promote(
                candidate_id,
                approval_receipt=receipt,
            )
            self._send(200, {"success": True, "decision": dec.to_dict()}); return
        except services_module.ApprovalRequiredError as exc:
            self._send(403, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
        except ValueError as exc:
            self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
        except KeyError as exc:
            self._send(404, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
    if action == "observe":
        candidate_id = str(payload.get("candidate_id", "")).strip()
        obs_data = payload.get("observation") or {}
        obs = services_module.SLOObservation(
            latency_ms=float(obs_data.get("latency_ms", 0.0)),
            success=bool(obs_data.get("success", True)),
            cost=float(obs_data.get("cost", 0.0)),
            error_count=int(obs_data.get("error_count", 0)),
        )
        try:
            trigger = services_module.APP.agent_learning.observe(candidate_id, obs)
            self._send(200, {"success": True, "rollback_trigger": trigger.to_dict() if trigger else None}); return
        except KeyError as exc:
            self._send(404, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
    if action == "list":
        limit_val = int(payload.get("limit", 100))
        candidates = services_module.APP.agent_learning.list_candidates(limit=limit_val)
        self._send(200, {"success": True, "candidates": [c.to_dict() for c in candidates]}); return
    self._send(400, {"success": False, "error": f"unknown learning action '{action}'", "terminal": True, "retryable": False}); return

def handle_agent_state_blackboard(self: Any, payload: dict[str, Any]) -> None:
    from . import http_server as services_module
    if not getattr(services_module.APP, "agent_blackboard", None):
        self._send(503, {"success": False, "error": "blackboard unavailable"}); return
    action = payload.get("action", "get")
    board_id = str(payload.get("board_id", payload.get("task_id", "default")))
    if action == "update":
        section = str(payload.get("section", "main"))
        content = payload.get("content")
        author = str(payload.get("author", "agent"))
        clock = payload.get("clock")
        exp_v = payload.get("expected_version")
        exp_v_int = int(exp_v) if exp_v is not None else None
        res = services_module.APP.agent_blackboard.update(board_id, section, content, author, clock=clock, expected_version=exp_v_int)
        self._send(200, res); return
    if action == "get":
        section = payload.get("section")
        res = services_module.APP.agent_blackboard.get(board_id, section=str(section) if section else None)
        self._send(200, res); return
    if action == "list":
        boards = services_module.APP.agent_blackboard.list_boards()
        self._send(200, {"success": True, "boards": boards, "count": len(boards)}); return
    if action == "merge":
        remote = payload.get("remote_sections", {})
        res = services_module.APP.agent_blackboard.merge(board_id, remote)
        self._send(200, res); return
    if action == "delete":
        section = payload.get("section")
        res = services_module.APP.agent_blackboard.delete(board_id, section=str(section) if section else None)
        self._send(200, res); return
    self._send(400, {"success": False, "error": f"unknown blackboard action '{action}'"}); return

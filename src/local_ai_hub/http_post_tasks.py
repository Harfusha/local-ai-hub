from __future__ import annotations

from typing import Any


def handle_agent_state_tasks(self: Any, payload: dict[str, Any]) -> None:
    from . import http_server as services_module
    if not getattr(services_module.APP, "agent_tasks", None) or not services_module.APP.agent_tasks.state_store.enabled:
        self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
    action = payload.get("action", "")
    idempotency_key = str(payload.get("idempotency_key", "")).strip()
    actor = self._agent() or "agent"
    if action not in services_module._AGENT_TASK_ACTIONS:
        self._send(400, {
            "success": False,
            "error": f"unknown task action '{action}'",
            "terminal": True,
            "retryable": False,
        }); return
    if "handoff_resume" in payload and action != "create":
        self._send(400, {"success": False, "error": "handoff_resume is only supported for task creation",
                         "terminal": True, "retryable": False}); return
    if action == "budget_increase":
        self._task_budget_increase(payload)
        return
    if action == "repair_session":
        self._task_repair_session(payload)
        return
    if action in {"projection_restore_preview", "projection_restore"}:
        root = str(payload.get("root", ""))
        task_id = str(payload.get("task_id", "")).strip()
        if not root or not task_id:
            self._send(400, {"success": False, "error": "root and task_id are required", "terminal": True, "retryable": False}); return
        if action == "projection_restore_preview":
            result = services_module.APP.agent_tasks.preview_task_projection_restore(task_id, root)
            self._send(200 if result.get("success") else 400, result); return
        result = services_module.APP.agent_tasks.restore_task_projection(
            task_id, root, str(payload.get("event_digest", ""))
        )
        self._send(200 if result.get("success") else 409, result); return
    if action == "projection_restore_batch_preview":
        root = str(payload.get("root", ""))
        if not root:
            self._send(400, {"success": False, "error": "root is required", "terminal": True, "retryable": False}); return
        result = services_module.APP.agent_tasks.preview_missing_task_projection_recovery(
            root, limit=payload.get("limit", 100), offset=payload.get("offset", 0)
        )
        self._send(200 if result.get("success") else 400, result); return
    if action == "projection_restore_batch":
        root = str(payload.get("root", ""))
        if not root:
            self._send(400, {"success": False, "error": "root is required", "terminal": True, "retryable": False}); return
        result = services_module.APP.agent_tasks.restore_task_projections(root, payload.get("entries"))
        self._send(200 if result.get("success") else 409, result); return
    scoped_task_actions = {
        "curate_dataset",
        "ask", "answer",
        "projection_restore_preview", "projection_restore", "projection_restore_batch_preview",
        "projection_restore_batch",
    }
    repo_root = str(getattr(self, "_authorization_root", "") or "")
    if action in scoped_task_actions and not repo_root:
        self._send(403, {"success": False, "error": "task root scope is required", "terminal": True, "retryable": False}); return
    if action == "curate_dataset":
        laya_operation = payload.get("laya_operation")
        if laya_operation is not None:
            if type(laya_operation) is not dict:
                self._send(400, {"success": False, "error": "laya_operation must be an object", "terminal": True, "retryable": False}); return
            try:
                if laya_operation.get("action") in {
                    "evaluate_context_source", "evaluate_decision", "runtime_status",
                }:
                    self._send(400, {
                        "success": False,
                        "error": "request-scoped Laya inference uses POST /api/laya/decision",
                        "terminal": True,
                        "retryable": False,
                    }); return
                result = services_module.APP.laya_candidates.handle(
                    laya_operation,
                    root=repo_root,
                    task_store=services_module.APP.agent_tasks,
                    evidence_store=services_module.APP.evidence,
                )
                self._send(200, result); return
            except RuntimeError as exc:
                self._send(503, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
            except Exception as exc:
                self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
        if "include_laya_candidates" in payload or "candidate_file_path" in payload:
            self._send(400, {"success": False, "error": "repo-root Laya JSONL import is retired; use laya_operation", "terminal": True, "retryable": False}); return
        task_id = str(payload.get("task_id", "")).strip() or None
        output_path = str(payload.get("output_path", payload.get("path", "training_dataset.jsonl")))
        min_receipts = int(payload.get("min_receipts", 1))
        dataset_format = str(payload.get("format", "jsonl"))
        include_laya_candidates = payload.get("include_laya_candidates", False)
        if type(include_laya_candidates) is not bool:
            self._send(400, {"success": False, "error": "include_laya_candidates must be a boolean", "terminal": True, "retryable": False}); return
        candidate_file_path = payload.get("candidate_file_path")
        if candidate_file_path is not None and not isinstance(candidate_file_path, str):
            self._send(400, {"success": False, "error": "candidate_file_path must be a string", "terminal": True, "retryable": False}); return
        if candidate_file_path is not None and not include_laya_candidates:
            self._send(400, {"success": False, "error": "candidate_file_path requires explicit opt-in", "terminal": True, "retryable": False}); return
        candidate_options = (
            {"include_laya_candidates": True, "candidate_file_path": candidate_file_path}
            if include_laya_candidates else {}
        )
        try:
            result = services_module.APP.agent_tasks.curate_training_dataset(
                output_path,
                min_receipts=min_receipts,
                format=dataset_format,
                repo_root=repo_root,
                task_id=task_id,
                **candidate_options,
            )
            self._send(200, result); return
        except Exception as exc:
            self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
    request_root = str(payload.get("root", ""))
    if action in {"ask", "answer"}:
        try:
            request_root = services_module._agent_question_scope(
                payload=payload,
                authorized_root=repo_root,
            )
        except ValueError as exc:
            self._send(403, {
                "success": False,
                "error": str(exc),
                "terminal": True,
                "retryable": False,
            }); return
    task_id = str(payload.get("task_id", "")).strip()
    if action not in {"create", "list", "reap_expired", "curate_dataset"} and task_id:
        if self._request_task(task_id, request_root) is None:
            return
    if action in {"ask", "answer"}:
        try:
            question_id = str(payload.get("question_id", "")).strip()
            if action == "ask":
                result = services_module.APP.agent_tasks.ask_question(
                    root=request_root,
                    session_id=payload.get("session_id", ""),
                    question=payload.get("question", ""),
                    task_id=task_id,
                    actor=actor,
                    question_id=question_id,
                    response_budget_tokens=payload.get("response_budget_tokens"),
                )
            else:
                result = services_module.APP.agent_tasks.answer_question(
                    question_id=question_id,
                    root=request_root,
                    answer=payload.get("answer", ""),
                    task_id=task_id,
                    actor=actor,
                    response_budget_tokens=payload.get("response_budget_tokens"),
                )
            if result is None:
                self._send(404, {
                    "success": False,
                    "error": "question not found in the requested repository/session/task scope",
                    "terminal": True,
                    "retryable": False,
                }); return
            self._send(200, {"success": True, "question": result}); return
        except services_module.CheckpointResponseBudgetError as exc:
            self._send(413, {
                "success": False, "error": str(exc), "terminal": True, "retryable": False,
                "mutation_applied": False, "operation_not_started": True,
                "response_budget": {
                    "requested_tokens": exc.requested_tokens,
                    "required_tokens": exc.required_tokens,
                    "unit": "estimated_tokens",
                },
            }); return
        except (TypeError, ValueError, RuntimeError) as exc:
            self._send(400, {
                "success": False,
                "error": str(exc),
                "terminal": True,
                "retryable": False,
            }); return
    if action == "create":
        from .repo_plan.schema_validation import RepoPlanError

        if "handoff_resume" in payload:
            from .repo_task_handoff import validate_resume_creation

            try:
                validate_resume_creation(payload)
            except (OSError, ValueError, RepoPlanError):
                self._send(409, {"success": False, "error": "Handoff preview invalid or source dependencies changed",
                                 "terminal": True, "retryable": False, "mutation_applied": False,
                                 "operation_not_started": True}); return
        auto_worktree = payload.get("auto_worktree", False)
        if not isinstance(auto_worktree, bool):
            self._send(400, {
                "success": False, "error": "auto_worktree must be a boolean",
                "terminal": True, "retryable": False,
            }); return
        try:
            from .execution_inventory import compile_repository_contract, repository_scope
            from .verified_execution import EXECUTION_KEY

            raw_contract = payload.get("contract")
            if isinstance(raw_contract, dict):
                profile = raw_contract.get("slo_profile")
                config = profile.get(EXECUTION_KEY) if isinstance(profile, dict) else None
                if repository_scope(config):
                    from .agent_task_models import _canonical_repository_root

                    requested = _canonical_repository_root(payload.get("repo_root", ""))
                    if not repo_root or requested != _canonical_repository_root(repo_root):
                        raise ValueError("repository inventory requires the authorized task repository root")
                    if auto_worktree or "handoff_resume" in payload:
                        raise ValueError("repository inventory must be created in the actual review checkout")
                    payload = {**payload, "contract": compile_repository_contract(raw_contract, requested)}
            contract = services_module._task_create_contract(payload)
        except (TypeError, ValueError, OSError, RuntimeError) as exc:
            self._send(400, {
                "success": False, "error": str(exc),
                "terminal": True, "retryable": False,
            }); return
        ctx_data = payload.get("context") or {}
        context = services_module.ScopeContext(
            repository_id=ctx_data.get("repository_id", ""),
            clone_id=ctx_data.get("clone_id", ""),
            worktree_id=ctx_data.get("worktree_id", ""),
            branch=ctx_data.get("branch", ""),
            task_id=ctx_data.get("task_id", ""),
            session_id=ctx_data.get("session_id", ""),
        )
        try:
            task = services_module.APP.agent_tasks.create(
                contract,
                context,
                task_id=str(payload.get("task_id", "") or ""),
                actor=actor,
                idempotency_key=idempotency_key,
                auto_worktree=auto_worktree,
                repo_root=str(payload.get("repo_root", "")),
                response_budget_tokens=payload.get("response_budget_tokens"),
                **({"_handoff_resume": payload["handoff_resume"]} if "handoff_resume" in payload else {}),
            )
        except RepoPlanError:
            self._send(409, {"success": False, "error": "Handoff adoption could not be verified",
                             "terminal": True, "retryable": False}); return
        except services_module.CheckpointResponseBudgetError as exc:
            self._send(413, {
                "success": False, "error": str(exc), "terminal": True, "retryable": False,
                "mutation_applied": False, "operation_not_started": True,
                "response_budget": {"requested_tokens": exc.requested_tokens,
                                    "required_tokens": exc.required_tokens,
                                    "unit": "estimated_tokens"},
            }); return
        except services_module.TaskIdempotencyConflictError as exc:
            self._send(409, {
                "success": False, "error": str(exc), "terminal": True, "retryable": False,
                "mutation_applied": False, "operation_not_started": True,
            }); return
        except services_module.TaskWorktreeError as exc:
            error_payload = {
                "success": False, "error": str(exc), "terminal": True, "retryable": False,
            }
            if exc.mutation_applied is not None:
                error_payload["mutation_applied"] = exc.mutation_applied
            error_payload["operation_not_started"] = exc.operation_not_started
            if exc.outcome_unknown:
                error_payload["outcome_unknown"] = True
            if exc.cleanup_succeeded is not None:
                error_payload["cleanup_succeeded"] = exc.cleanup_succeeded
            self._send(409 if exc.operation_not_started else 500, error_payload); return
        except ValueError as exc:
            self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
        # A prediction is optional and must never fail task persistence.
        try:
            warm = getattr(services_module.APP.services, "schedule_task_context_warmup", None)
            if callable(warm):
                paths = payload.get("changed_paths")
                if paths is not None and (not isinstance(paths, list) or any(not isinstance(p, str) for p in paths)):
                    paths = None
                warm(task, root=repo_root, changed_paths=paths)
        except Exception:
            pass
        self._send(200, {"success": True, "task": task.to_dict()}); return
    if action == "get":
        task = services_module.APP.agent_tasks.get(str(payload.get("task_id", "")))
        if not task:
            self._send(404, {"success": False, "error": "task not found", "terminal": True, "retryable": False}); return
        self._send(200, {"success": True, "task": task.to_dict()}); return
    if action == "transition":
        target_status_str = str(payload.get("status", "")).strip().lower()
        try:
            target_status = services_module.TaskStatus(target_status_str)
        except ValueError:
            self._send(400, {"success": False, "error": f"invalid status {target_status_str}", "terminal": True, "retryable": False}); return
        checkpoint_data = payload.get("checkpoint")
        if checkpoint_data is not None and not isinstance(checkpoint_data, dict):
            self._send(400, {"success": False, "error": "checkpoint must be an object", "terminal": True, "retryable": False}); return
        checkpoint = services_module.TaskCheckpoint.from_dict(checkpoint_data) if checkpoint_data is not None else None
        try:
            task = services_module.APP.agent_tasks.transition(
                str(payload.get("task_id", "")),
                target_status,
                reason=str(payload.get("reason", "")),
                actor=actor,
                idempotency_key=idempotency_key,
                checkpoint=checkpoint,
                response_budget_tokens=payload.get("response_budget_tokens"),
            )
            self._send(200, {"success": True, "task": task.to_dict()}); return
        except services_module.CheckpointResponseBudgetError as exc:
            self._send(413, {
                "success": False, "error": str(exc), "terminal": True, "retryable": False,
                "mutation_applied": False, "operation_not_started": True,
                "response_budget": {"requested_tokens": exc.requested_tokens,
                                    "required_tokens": exc.required_tokens,
                                    "unit": "estimated_tokens"},
            }); return
        except (KeyError, ValueError, services_module.CompletionGateError) as exc:
            self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
    if action in {"claim", "adopt"}:
        try:
            task_id = str(payload.get("task_id", "")).strip()
            new_owner = str(payload.get("owner") or actor or "").strip()
            task = services_module.APP.agent_tasks.claim(task_id, new_owner, actor=actor)
            self._send(200, {"success": True, "task": task.to_dict()}); return
        except (KeyError, ValueError) as exc:
            self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
    if action == "complete":
        current_revision = ""
        root = ""
        try:
            task_id = str(payload.get("task_id", ""))
            task_state = services_module.APP.agent_tasks.get(task_id)
            if task_state is None:
                raise KeyError(f"Task {task_id} not found")
            task_owner = str(getattr(task_state, "owner", "") or "").strip()
            allow_adopt = bool(payload.get("allow_adopt") or payload.get("adopt"))
            if "operator_waiver" in payload and allow_adopt:
                raise ValueError("operator waiver cannot adopt a task")
            if "operator_waiver" in payload and payload["operator_waiver"] is None:
                raise ValueError("operator waiver must be an explicit object")
            if ("expected_criteria" in payload or "expected_binding" in payload) and allow_adopt:
                raise ValueError("criteria-bound completion cannot adopt a task")
            if not task_owner or (str(actor or "").strip() != task_owner and not allow_adopt):
                self._send(403, {
                    "success": False,
                    "error": "task completion is restricted to its owner",
                    "error_code": "task_owner_mismatch",
                    "terminal": True,
                    "retryable": False,
                }); return
            if "expected_criteria" in payload:
                from .verification_rules import validate_expected_criteria
                validate_expected_criteria(task_state, payload["expected_criteria"])
            if "expected_binding" in payload:
                from .verification_rules import validate_expected_binding
                if "expected_criteria" not in payload:
                    raise services_module.CompletionGateError("expected goal binding requires acceptance criteria")
                validate_expected_binding(task_state, payload["expected_binding"])
            if allow_adopt and task_owner and str(actor or "").strip() != task_owner:
                task_state = services_module.APP.agent_tasks.claim(task_id, actor, actor=actor)
            task_context = getattr(task_state, "context", None)
            root = str(
                payload.get("root")
                or getattr(task_context, "repository_id", "")
                or ""
            ).strip()
            verification_store = getattr(services_module.APP, "agent_verification", None)
            if verification_store is None:
                raise services_module.CompletionGateError("completion verification store unavailable")
            if not root:
                self._send(400, {
                    "success": False,
                    "error": "project root is required for task completion verification",
                    "terminal": True,
                    "retryable": False,
                }); return
            current_revision, revision_stop = services_module._completion_revision_or_stop(
                root,
                getattr(services_module.APP, "repo_tools", None),
                getattr(services_module.APP, "repo_state", None),
            )
            if revision_stop:
                self._send(409, revision_stop); return
            from .verification_rules import complete_task_with_project_rules

            task = complete_task_with_project_rules(
                services_module.APP.agent_tasks,
                verification_store,
                task_id,
                root=root,
                state_dir=verification_store.state_store.db_path.parent,
                current_revision=current_revision,
                reason=str(payload.get("reason", "completed by agent")),
                actor=actor,
                idempotency_key=idempotency_key,
                response_budget_tokens=payload.get("response_budget_tokens"),
                **({"operator_waiver": payload["operator_waiver"]} if "operator_waiver" in payload else {}),
                **({"expected_criteria": payload["expected_criteria"]} if "expected_criteria" in payload else {}),
                **({"expected_binding": payload["expected_binding"]} if "expected_binding" in payload else {}),
            )
            self._send(200, {"success": True, "task": task.to_dict()}); return
        except services_module.CheckpointResponseBudgetError as exc:
            self._send(413, {
                "success": False, "error": str(exc), "terminal": True, "retryable": False,
                "mutation_applied": False, "operation_not_started": True,
                "response_budget": {"requested_tokens": exc.requested_tokens,
                                    "required_tokens": exc.required_tokens,
                                    "unit": "estimated_tokens"},
            }); return
        except services_module.CompletionGateError as exc:
            self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
        except (KeyError, ValueError) as exc:
            self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
    if action == "fail":
        try:
            fail_reason = str(payload.get("reason") or payload.get("error") or payload.get("message") or "failed by agent")
            task = services_module.APP.agent_tasks.fail(
                str(payload.get("task_id", "")),
                reason=fail_reason,
                actor=actor,
                idempotency_key=idempotency_key,
                response_budget_tokens=payload.get("response_budget_tokens"),
            )
            self._send(200, {"success": True, "task": task.to_dict()}); return
        except services_module.CheckpointResponseBudgetError as exc:
            self._send(413, {
                "success": False, "error": str(exc), "terminal": True, "retryable": False,
                "mutation_applied": False, "operation_not_started": True,
                "response_budget": {"requested_tokens": exc.requested_tokens,
                                    "required_tokens": exc.required_tokens,
                                    "unit": "estimated_tokens"},
            }); return
        except (KeyError, ValueError, services_module.CompletionGateError) as exc:
            self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
    if action == "checkpoint":
        chk_data = payload.get("checkpoint")
        if not isinstance(chk_data, dict):
            self._send(400, {
                "success": False, "error": "checkpoint must be an object",
                "terminal": True, "retryable": False,
            }); return
        checkpoint = services_module.TaskCheckpoint.from_dict(chk_data)
        try:
            task = services_module.APP.agent_tasks.checkpoint(
                str(payload.get("task_id", "")),
                checkpoint,
                response_budget_tokens=payload.get("response_budget_tokens"),
                actor=actor,
                idempotency_key=idempotency_key,
            )
            self._send(200, {"success": True, "task": task.to_dict()}); return
        except KeyError as exc:
            self._send(404, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
        except services_module.CheckpointResponseBudgetError as exc:
            self._send(413, {
                "success": False,
                "error": str(exc),
                "terminal": True,
                "retryable": False,
                "mutation_applied": False,
                "operation_not_started": True,
                "response_budget": {
                    "requested_tokens": exc.requested_tokens,
                    "required_tokens": exc.required_tokens,
                    "unit": "estimated_tokens",
                },
            }); return
        except ValueError as exc:
            self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
        except services_module.CompletionGateError as exc:
            self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
    if action == "rollback":
        try:
            task = services_module.APP.agent_tasks.rollback(
                str(payload.get("task_id", "")),
                actor=actor,
                idempotency_key=idempotency_key,
                reason=str(payload.get("reason", "manual rollback")),
                response_budget_tokens=payload.get("response_budget_tokens"),
            )
            self._send(200, {"success": True, "task": task.to_dict()}); return
        except KeyError as exc:
            self._send(404, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
        except services_module.CheckpointResponseBudgetError as exc:
            self._send(413, {
                "success": False, "error": str(exc), "terminal": True, "retryable": False,
                "mutation_applied": False, "operation_not_started": True,
                "response_budget": {"requested_tokens": exc.requested_tokens,
                                    "required_tokens": exc.required_tokens,
                                    "unit": "estimated_tokens"},
            }); return
        except Exception as exc:
            self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
    if action == "resume":
        try:
            task = services_module.APP.agent_tasks.resume(
                str(payload.get("task_id", "")),
                actor=actor,
                idempotency_key=idempotency_key,
                response_budget_tokens=payload.get("response_budget_tokens"),
            )
            self._send(200, {"success": True, "task": task.to_dict()}); return
        except KeyError as exc:
            self._send(404, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
        except services_module.CheckpointResponseBudgetError as exc:
            self._send(413, {
                "success": False, "error": str(exc), "terminal": True, "retryable": False,
                "mutation_applied": False, "operation_not_started": True,
                "response_budget": {"requested_tokens": exc.requested_tokens,
                                    "required_tokens": exc.required_tokens,
                                    "unit": "estimated_tokens"},
            }); return
        except ValueError as exc:
            self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
    if action == "heartbeat":
        t_id = str(payload.get("task_id", "")).strip()
        ttl_val = payload.get("ttl_seconds", payload.get("ttl"))
        ttl_sec = float(ttl_val) if ttl_val is not None and float(ttl_val) > 0 else None
        try:
            task = services_module.APP.agent_tasks.heartbeat(
                t_id,
                ttl_seconds=ttl_sec,
                actor=actor,
                idempotency_key=idempotency_key,
                response_budget_tokens=payload.get("response_budget_tokens"),
            )
            self._send(200, {"success": True, "task": task.to_dict()}); return
        except KeyError as exc:
            self._send(404, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
        except services_module.CheckpointResponseBudgetError as exc:
            self._send(413, {
                "success": False, "error": str(exc), "terminal": True, "retryable": False,
                "mutation_applied": False, "operation_not_started": True,
                "response_budget": {"requested_tokens": exc.requested_tokens,
                                    "required_tokens": exc.required_tokens,
                                    "unit": "estimated_tokens"},
            }); return
        except ValueError as exc:
            self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
    if action == "cleanup_worktree":
        t_id = str(payload.get("task_id", ""))
        del_br = bool(payload.get("delete_branch", True))
        try:
            result = services_module.APP.agent_tasks.cleanup_worktree(
                t_id,
                delete_branch=del_br,
                actor=self._agent(),
                response_budget_tokens=payload.get("response_budget_tokens"),
            )
            self._send(200, result); return
        except services_module.CheckpointResponseBudgetError as exc:
            self._send(413, {
                "success": False, "error": str(exc), "terminal": True, "retryable": False,
                "mutation_applied": False, "operation_not_started": True,
                "response_budget": {
                    "requested_tokens": exc.requested_tokens,
                    "required_tokens": exc.required_tokens,
                    "unit": "estimated_tokens",
                },
            }); return
        except ValueError as exc:
            self._send(400, {
                "success": False, "error": str(exc), "terminal": True, "retryable": False,
            }); return
    if action == "reap_expired":
        requested_task_id = payload.get("task_id")
        auto_recover = payload.get("auto_recover", False)
        if (
            not isinstance(requested_task_id, str)
            or not requested_task_id
            or requested_task_id != requested_task_id.strip()
            or type(auto_recover) is not bool
        ):
            self._send(400, {"success": False, "error": "reap_expired requires a nonempty canonical task_id and boolean auto_recover", "terminal": True, "retryable": False}); return
        if not repo_root:
            self._send(403, {"success": False, "error": "task root scope is required", "terminal": True, "retryable": False}); return
        scoped_task = self._request_task(requested_task_id, repo_root)
        if scoped_task is None:
            return
        if not self._task_matches_request(scoped_task, repo_root):
            self._send(404, {"success": False, "error": "task not found", "terminal": True, "retryable": False}); return
        try:
            reaped = services_module.APP.agent_tasks.reap_expired_heartbeats(
                auto_recover=auto_recover,
                repo_root=repo_root,
                task_id=requested_task_id,
                response_budget_tokens=payload.get("response_budget_tokens"),
            )
            self._send(200, {"success": True, "reaped": reaped}); return
        except services_module.CheckpointResponseBudgetError as exc:
            self._send(413, {
                "success": False, "error": str(exc), "terminal": True, "retryable": False,
                "mutation_applied": False, "operation_not_started": True,
                "response_budget": {
                    "requested_tokens": exc.requested_tokens,
                    "required_tokens": exc.required_tokens,
                    "unit": "estimated_tokens",
                },
            }); return
        except ValueError as exc:
            self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
    if action == "list":
        status_filter = None
        if payload.get("status"):
            try:
                status_filter = services_module.TaskStatus(str(payload.get("status")).strip().lower())
            except ValueError:
                pass
        limit = int(payload.get("limit", 100))
        include_stale = bool(payload.get("include_stale", False))
        task_query = payload.get("query")
        if task_query is not None and not isinstance(task_query, str):
            self._send(400, {
                "success": False,
                "error": "query must be a string",
                "terminal": True,
                "retryable": False,
            }); return
        task_page = services_module.APP.agent_tasks.list_tasks(
            status=status_filter,
            limit=limit,
            include_stale=include_stale,
            query=task_query,
        )
        owner_filter = payload.get("owner")
        request_root = getattr(self, "_request_root", "") or getattr(self, "_authorization_root", "")
        filtered_tasks = [t for t in task_page.tasks if (not owner_filter or getattr(t, "owner", "") == str(owner_filter)) and self._task_matches_request(t, request_root)]
        response = {"success": True, "tasks": [t.to_dict() for t in filtered_tasks]}
        if task_page.query_truncated:
            response["query_truncated"] = True
        self._send(200, response); return
    self._send(400, {"success": False, "error": f"unknown task action '{action}'", "terminal": True, "retryable": False}); return

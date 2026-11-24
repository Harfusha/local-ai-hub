from __future__ import annotations

from typing import Any, Literal, TypeAlias

from local_ai_hub.operation_contracts import operation_actions

CoordAction: TypeAlias = Literal.__getitem__(operation_actions("local_ai_coord", None))

def local_ai_coord(
    action: CoordAction,
    root: str = ".",
    paths: list[str] | None = None,
    lease_id: str = "",
    owner: str = "",
    purpose: str = "agent edit",
    key: str = "",
    value: str | None = None,
    query: str = "",
    command: str = "",
    command_id: str = "",
    ttl_seconds: int | None = None,
    max_tokens: int = 0,
    task: str = "",
    task_id: str = "",
    question_id: str = "",
    question: str = "",
    answer: str = "",
    contract: dict[str, Any] | None = None,
    receipt: dict[str, Any] | None = None,
    checkpoint: dict[str, Any] | None = None,
    budget: dict[str, Any] | None = None,
    status: str = "",
    reason: str = "",
    generation: str = "",
    consent: bool = False,
    audit_reason: str = "",
    record: dict[str, Any] | None = None,
    record_id: str = "",
    contradicts_record_id: str | None = None,
    supersedes_record_id: str | None = None,
    criterion: str = "",
    board_id: str = "",
    section: str = "",
    scope: str = "",
    scope_id: str = "",
    target_scope: str = "",
    approver: str = "",
    fingerprint: dict[str, Any] | None = None,
    tool_outcome: dict[str, Any] | None = None,
    state_revision: str = "",
    extra_fields: list[str] | None = None,
    max_response_tokens: int = 0,
    response_profile: str = "",
    reuse_key: str = "",
    include_diagnostics: bool = False,
    include_stale: bool = False,
    clone_id: str = "",
    worktree_id: str = "",
    branch: str = "",
    repository_id: str = "",
    session_id: str = "",
    repository_revision: str = "",
    phase: str = "",
    focus: list[str] | None = None,
    preload_profile: str = "",
    since_hash: str = "",
    expected_version: int | None = None,
    after_seq: int | None = None,
    after_ts: float | None = None,
    format: str | None = None,
    sync_action: str | None = None,
    stream_id: str | None = None,
    events: list[dict[str, Any]] | None = None,
    limit: int | None = None,
    offset: int | None = None,
    content: Any = None,
    author: str = "agent",
    remote_sections: dict[str, Any] | None = None,
    topic: str = "default",
    message: Any = None,
    publisher: str = "agent",
    goal: str = "",
    target_paths: list[str] | None = None,
    test_command: str = "",
    swarm_id: str = "",
    role: str = "Coder",
    swarm_action: str = "submit_patch",
    payload: dict[str, Any] | None = None,
    state: str = "",
    source_branch: str = "",
    target_branch: str = "HEAD",
    worktree_path: str = "",
    delete_branch: bool = True,
    output_path: str = "training_dataset.jsonl",
    min_receipts: int = 1,
    laya_operation: dict[str, Any] | None = None,
    name: str = "",
    title: str = "",
    description: str = "",
    capacity: int = 1,
    timeout: float = 0.0,
    filter: dict[str, Any] | None = None,
    filter_payload: dict[str, Any] | None = None,
    include: list[str] | None = None,
    confidence: float | None = None,
    allow_adopt: bool = False,
    operator_waiver: dict[str, Any] | None = None,
    acceptance_criteria: list[str] | None = None,
    criteria: list[str] | None = None,
    kind: str = "",
    next_action: str = "",
    blockers: list[str] | None = None,
    evidence_ids: list[str] | None = None,
    summary: str = "",
    result: str = "",
    plan_id: str = "",
    expected_revision: str | None = None,
    idempotency_key: str = "",
    task_data: dict[str, Any] | None = None,
    lifecycle: str | None = None,
    default_target_ref: str | None = None,
    spec_refs: list[dict[str, Any]] | None = None,
    accountable_role: str | None = None,
    tasks: dict[str, Any] | None = None,
    plan_task_id: str = "",
    steering_id: str = "",
    spec_rel_path: str = "",
    spec_content: str = "",
    expected_spec_revision: str = "",
) -> dict[str, Any]:
    """Coordination for Hub work and GPU reservations. `gpu_reservation_status` takes only `action` (no root) and reports owner, generation, state and expiry; reports `reaped=true` after expiry cleanup. Unresolved state includes a non-secret `reason_code` and remains fail-closed. `gpu_reservation_release` requires `generation`, `consent=true` and a non-empty `audit_reason`; release is allowed after expiry or when the owner process is confirmed gone. `gpu_reservation_release_authorized` requires explicit consent and an audit reason, without a status or owner-liveness preflight. It releases a valid reservation and capacity leases for that exact generation, or records a durable operator-release marker when the reservation file is already missing, allowing the scheduler to clear only stale in-memory external admission. Other generations are preserved; release can interrupt GPU work using the released generation. Malformed metadata and symlinks remain fail-closed. Never unlink reservation files directly. ask persists a repository/session-scoped question; retrieve it later with the same question_id, root and session_id. answer records an operator response under the authorized repository root. Public actions are limited to the contract enum; unscoped memory relation/reaping storage remains private. Claim overlapping edit paths before concurrent Hub work. Use scoped Agent OS memory_find/memory_record for reusable findings; workspace memo actions are operator-only and unavailable through this tool. Native peer subagents are coordinated by Codex rather than by this Hub tool."""
    from . import mcp_server as services_module
    if not services_module.FEATURES.coord:
        return {"success": False, "unsupported": True, "error": "local_ai_coord is disabled in configuration"}
    if action in {"gpu_reservation_status", "gpu_reservation_release", "gpu_reservation_release_authorized", "gpu_capacity_lease_release", "gpu_scheduler_capacity_lease_release"}:
        supplied = {"action": action}
        if action == "gpu_reservation_release":
            supplied.update(generation=generation, consent=consent, audit_reason=audit_reason)
        elif action == "gpu_reservation_release_authorized":
            supplied.update(consent=consent, audit_reason=audit_reason)
        elif action in {"gpu_capacity_lease_release", "gpu_scheduler_capacity_lease_release"}:
            supplied.update(lease_id=lease_id, owner=owner, generation=generation, consent=consent,
                            audit_reason=audit_reason)
        contract_error_value = services_module.validate_operation_arguments("local_ai_coord", action, supplied)
        if contract_error_value:
            return services_module.contract_error(contract_error_value, status_code=400)
        operation = {
            "action": {
                "gpu_reservation_status": "status",
                "gpu_reservation_release": "release",
                "gpu_reservation_release_authorized": "release_authorized",
                "gpu_capacity_lease_release": "release_laya_capacity_lease",
                "gpu_scheduler_capacity_lease_release": "release_scheduler_capacity_lease",
            }[action],
            "generation": generation,
            "consent": consent,
            "audit_reason": audit_reason,
        }
        if action in {"gpu_capacity_lease_release", "gpu_scheduler_capacity_lease_release"}:
            operation.update(lease_id=lease_id, owner=owner)
        try:
            return services_module.CLIENT.post("/api/gpu-reservation", operation, timeout=services_module._timeout("quick"))
        except Exception:
            # A lost response may follow a committed release; never replay it here.
            return {"success": False, "outcome_unknown": True,
                    "error": "GPU reservation operation response unavailable; inspect status before retrying"}
    if isinstance(action, str) and action.startswith("plan_"):
        # Preserve omission versus explicit null; do not inject other actions' defaults.
        options = services_module._CURRENT_RESPONSE_OPTIONS.get() or {}
        raw_call = services_module._CURRENT_MCP_CALL_ARGUMENTS.get()
        supplied = (
            raw_call[1] if raw_call is not None and raw_call[0] == "local_ai_coord"
            else options.get("arguments") if options.get("tool") == "local_ai_coord" else None
        )
        if not isinstance(supplied, dict):
            current = locals().copy()
            signature = services_module.inspect.signature(services_module.local_ai_coord)
            supplied = {name: value for name, value in current.items()
                        if name in signature.parameters and value != signature.parameters[name].default}
        else:
            supplied = dict(supplied)
        error = services_module.validate_operation_arguments("local_ai_coord", action, supplied)
        if error:
            return services_module.contract_error(error, status_code=400)
        metadata = services_module.operation_contract("local_ai_coord")["actions"][action]
        arguments = {name: value for name, value in supplied.items() if name in metadata["allowed"]}
        if action == "plan_task_edit":
            requested_budget, _, _, budget_enabled = services_module._response_budget("coord", options)
            if budget_enabled and 0 < requested_budget < 256:
                return {
                    "success": False,
                    "error": "plan_task_edit requires max_response_tokens >= 256 to preserve the write acknowledgement",
                    "terminal": True,
                    "retryable": False,
                    "operation_not_started": True,
                    "mutation_applied": False,
                    "plan_id": plan_id,
                    "task_id": task_id,
                }
        result = services_module.CLIENT.coord(action=action, **arguments)
        if action in {"plan_create", "plan_update", "plan_task_edit", "plan_task_delete", "plan_archive", "plan_adopt_legacy_board"} and isinstance(result, dict) and result.get("success") is True:
            no_op = result.get("no_op")
            if isinstance(no_op, bool):
                result = {**result, "mutation_applied": not no_op}
        if action == "plan_board_view" and isinstance(result, dict) and result.get("success") is True:
            raw_columns = result.get("columns", {})
            compact_columns = {}
            for col_name, items in raw_columns.items():
                if not isinstance(items, list):
                    compact_columns[col_name] = items
                    continue
                col_items = items[-8:] if col_name == "done" and len(items) > 8 else items
                compact_items = []
                for it in col_items:
                    if isinstance(it, dict):
                        card = {
                            "id": it.get("id") or it.get("task_id"),
                            "title": (it.get("title") or it.get("name") or "")[:120],
                            "status": it.get("status"),
                            "priority": it.get("priority", "medium"),
                        }
                        if it.get("assignee"):
                            card["assignee"] = it["assignee"]
                        if it.get("blocked_by"):
                            card["blocked_by"] = it["blocked_by"]
                        compact_items.append(card)
                    else:
                        compact_items.append(it)
                compact_columns[col_name] = compact_items
            result["columns"] = compact_columns

        plan_extra = [
            "plan", "plans", "file_revision", "plan_id", "rel_path", "git_branch", "git_head",
            "board", "columns", "items", "tasks",
            "project_root", "counts", "total_items", "plan_filter", "plan_task_id",
        ]
        projected = services_module._compact(
            result,
            "coord" if action.startswith("plan_") or action == "plan_bind_task" else "status",
            plan_extra if action.startswith("plan_") else None,
        )
        if (
            action == "plan_board_view"
            and isinstance(result, dict)
            and result.get("success") is True
            and isinstance(projected, dict)
        ):
            for key in ("columns", "counts", "total_items", "project_root"):
                if key in result:
                    projected[key] = services_module.copy.deepcopy(result[key])
        if action == "plan_get" and isinstance(result, dict) and result.get("success") is True:
            if (not isinstance(projected, dict) or projected.get("success") is not True or
                projected.get("plan") != result.get("plan") or
                projected.get("file_revision") != result.get("file_revision") or
                not isinstance(result.get("plan"), dict) or
                not isinstance(result.get("file_revision"), str)):
                incomplete = {
                    "success": False,
                    "error": "Plan response incomplete; request a larger budget or read the plan source in bounded slices.",
                    "terminal": True,
                    "retryable": False,
                }
                plan = result.get("plan")
                revision = result.get("file_revision")
                rel_path = result.get("rel_path")
                resolved_plan_id = result.get("plan_id") or (plan.get("id") if isinstance(plan, dict) else "") or plan_id
                if (
                    isinstance(revision, str) and revision and isinstance(rel_path, str) and rel_path):
                    incomplete.update(plan_id=resolved_plan_id, file_revision=revision, rel_path=rel_path)
                return services_module._compact(incomplete, "coord", ["plan_id", "file_revision", "rel_path"])
        if action in {"plan_list", "plan_board_view"} and isinstance(result, dict) and result.get("success") is True:
            if action == "plan_list":
                has_plans = "plans" in result
                required_fields = ("plans",) if has_plans else ()
                complete_source = isinstance(result.get("plans"), list) if has_plans else True
            else:
                required_fields = ("project_root", "counts", "total_items")
                complete_source = (
                    isinstance(result.get("project_root"), str) and bool(result.get("project_root"))
                    and isinstance(result.get("columns"), dict)
                    and isinstance(projected.get("columns"), dict)
                    and isinstance(result.get("counts"), dict)
                    and isinstance(result.get("total_items"), int)
                    and not isinstance(result.get("total_items"), bool)
                    and result["total_items"] >= 0
                )
            if not isinstance(projected, dict) or (
                projected.get("success") is True
                and (
                    not complete_source
                    or any(projected.get(key) != result.get(key) for key in required_fields)
                )
            ):
                incomplete_plan = {
                    "success": False,
                    "error": "Plan response incomplete; request a larger budget or read the plan source in bounded slices.",
                    "terminal": True,
                    "retryable": False,
                }
                if plan_id:
                    incomplete_plan["plan_id"] = plan_id
                if isinstance(result.get("project_root"), str) and result["project_root"]:
                    incomplete_plan["project_root"] = result["project_root"]
                return services_module._compact(incomplete_plan, "coord", ["plan_id", "project_root"])
        if action == "plan_task_edit" and isinstance(result, dict) and result.get("success") is True:
            identity_fields = ("mutation_applied", "plan_id", "task_id", "file_revision")
            mutation_applied = result.get("mutation_applied")
            valid_identity = (
                isinstance(mutation_applied, bool)
                and result.get("plan_id") == plan_id
                and result.get("task_id") == task_id
                and isinstance(result.get("file_revision"), str)
                and bool(result.get("file_revision"))
            )
            if isinstance(projected, dict) and projected.get("success") is False:
                failed_projection = dict(projected)
                failed_projection["projection_incomplete"] = True
                for key in identity_fields:
                    if key in result:
                        failed_projection[key] = result[key]
                if not isinstance(mutation_applied, bool):
                    failed_projection["outcome_unknown"] = True
                if isinstance(result.get("rel_path"), str) and result["rel_path"]:
                    failed_projection["rel_path"] = result["rel_path"]
                return failed_projection
            if (
                not valid_identity
                or not isinstance(projected, dict)
                or projected.get("success") is not True
                or any(projected.get(key) != result.get(key) for key in identity_fields)
            ):
                incomplete = {
                    "success": False,
                    "error": "Plan edit response incomplete; inspect persisted plan revision before continuing.",
                    "terminal": True,
                    "retryable": False,
                    "projection_incomplete": True,
                }
                for key in identity_fields:
                    if key in result:
                        incomplete[key] = result[key]
                if not isinstance(mutation_applied, bool):
                    incomplete["outcome_unknown"] = True
                if isinstance(result.get("rel_path"), str) and result["rel_path"]:
                    incomplete["rel_path"] = result["rel_path"]
                return incomplete
        return projected
    if after_seq is not None and (isinstance(after_seq, bool) or not isinstance(after_seq, int) or not 0 <= after_seq <= services_module.MAX_EVENT_SEQUENCE):
        return services_module.contract_error(f"after_seq must be an integer between 0 and {services_module.MAX_EVENT_SEQUENCE}")
    if not isinstance(action, str) or action not in services_module.operation_actions("local_ai_coord", None):
        return services_module._invalid_action(
            "local_ai_coord", action, services_module.operation_actions("local_ai_coord", None),
            "Use a canonical advertised coordination action.",
        )
    if action in {"memory_reap", "relation_record", "relation_find", "relation_traverse"}:
        return services_module._invalid_action(
            "local_ai_coord",
            action,
            tuple(services_module.CoordAction.__args__),
            "Unscoped memory maintenance and relations remain private until explicit repository scope is supported.",
        )
    if action in {"negative_knowledge_record", "negative_knowledge_find", "incident_decision"}:
        try:
            if not isinstance(root, str) or not root.strip() or root != root.strip() or not services_module.is_rooted_path(root):
                raise services_module.RepositoryScopeError(
                    "incident operations require an explicit absolute repository root",
                    "incident_root_required",
                )
            root = str(services_module.canonical_repository_root(root))
            if isinstance(record, dict):
                services_module.reject_retired_tenancy_fields(record)
                if "root" in record:
                    raise services_module.RepositoryScopeError("record cannot override root", "invalid_incident_root")
        except services_module.RepositoryScopeError as exc:
            return services_module.contract_error(str(exc), status_code=exc.status_code)
    if action == "task_sync":
        rejection = services_module._subminimum_budget_rejection({"max_response_tokens": max_response_tokens})
        if rejection is not None:
            return rejection
    if action == "task_sync":
        if status or key or task_id or ttl_seconds is not None or max_tokens != 0 or record is not None:
            return services_module.contract_error("task_sync accepts only sync_action, stream_id, after_seq, limit, and events")
        sync_inputs = {
            name: value for name, value in {
                "sync_action": sync_action,
                "stream_id": stream_id,
                "after_seq": after_seq,
                "limit": limit,
                "events": events,
            }.items() if value is not None
        }
        sync_error = services_module.validate_operation_arguments("local_ai_coord", action, sync_inputs)
        if sync_error is not None:
            return services_module.contract_error(sync_error, status_code=400)
        sync_act = "export" if sync_action is None else sync_action
        if sync_act == "export":
            sync_stream = "" if stream_id is None else stream_id
            sync_after_seq = 0 if after_seq is None else after_seq
            sync_limit = 1000 if limit is None else limit
            return services_module._compact(services_module.CLIENT.post("/api/agent-state/events/delta", {
                "action": "export", "stream_id": sync_stream,
                "after_seq": sync_after_seq, "limit": sync_limit,
            }, timeout=services_module._timeout("quick")), "status")
        return services_module._compact(services_module.CLIENT.post("/api/agent-state/events/delta", {
            "action": "import", "events": events,
        }, timeout=services_module._timeout("quick")), "status")
    incident_legacy_values: dict[str, dict[str, services_module.Any]] = {
        "negative_knowledge_record": {
            "key": key, "value": value, "query": query, "reason": reason, "status": status,
            "record_id": record_id, "tool_outcome": tool_outcome, "fingerprint": fingerprint,
            "state_revision": state_revision, "limit": limit,
        },
        "negative_knowledge_find": {
            "key": key, "value": value, "reason": reason, "status": status,
            "record_id": record_id, "tool_outcome": tool_outcome, "fingerprint": fingerprint,
            "record": record, "state_revision": state_revision,
        },
        "incident_decision": {
            "value": value, "query": query, "reason": reason, "status": status,
            "record_id": record_id, "tool_outcome": tool_outcome, "record": record,
            "repository_revision": repository_revision, "key": key, "limit": limit,
        },
    }
    if action in incident_legacy_values and any(
        item is not None and item != "" and item != 0
        for item in incident_legacy_values[action].values()
    ):
        return services_module.contract_error(f"action='{action}' accepts only canonical incident fields", status_code=400)
    sync_only_inputs = {
        name: value for name, value in {
            "sync_action": sync_action,
            "stream_id": stream_id,
            "events": events,
        }.items() if value is not None
    }
    if sync_only_inputs:
        sync_error = services_module.validate_operation_arguments("local_ai_coord", action, sync_only_inputs)
        if sync_error is not None:
            return services_module.contract_error(sync_error, status_code=400)
    board_actions = {
        "blackboard_update", "blackboard_get", "blackboard_list",
        "blackboard_merge", "blackboard_delete",
    }
    pubsub_actions = {"pubsub_publish", "pubsub_poll"}
    if action in board_actions | pubsub_actions:
        ignored_values = {
            "paths": paths, "lease_id": lease_id, "key": key, "value": value,
            "query": query, "command": command, "ttl_seconds": ttl_seconds,
            "max_tokens": max_tokens, "task": task, "question_id": question_id,
            "question": question, "answer": answer, "contract": contract,
            "receipt": receipt, "checkpoint": checkpoint, "status": status,
            "reason": reason, "record": record, "record_id": record_id,
            "criterion": criterion, "scope": scope, "scope_id": scope_id,
            "target_scope": target_scope, "approver": approver,
            "fingerprint": fingerprint, "tool_outcome": tool_outcome,
            "include_diagnostics": include_diagnostics, "include_stale": include_stale,
            "clone_id": clone_id, "worktree_id": worktree_id, "branch": branch,
            "repository_id": repository_id, "session_id": session_id,
            "repository_revision": repository_revision,
            "phase": phase, "focus": focus, "preload_profile": preload_profile,
            "since_hash": since_hash, "sync_action": sync_action,
            "stream_id": stream_id, "events": events, "format": format,
        }
        unexpected_values = {
            name: supplied for name, supplied in ignored_values.items()
            if supplied is not None and supplied is not False and supplied != "" and supplied != 0
            and not (name == "format" and supplied == "markdown")
        }
        if unexpected_values:
            return services_module.contract_error(
                f"action='{action}' accepts only canonical fields; unexpected field {sorted(unexpected_values)[0]!r}",
                status_code=400,
            )
        canonical_inputs: dict[str, services_module.Any] = {"root": root}
        if action in board_actions:
            if not isinstance(task_id, str) or not isinstance(board_id, str) or not isinstance(section, str):
                return services_module.contract_error("task_id, board_id, and section must be strings", status_code=400)
            if task_id:
                canonical_inputs["task_id"] = task_id
            if action != "blackboard_list":
                canonical_inputs["board_id"] = board_id or task_id or "default"
            if action in {"blackboard_update", "blackboard_get", "blackboard_delete"} and section:
                canonical_inputs["section"] = section
            if action == "blackboard_update":
                canonical_inputs.update(content=content, author=author)
                if expected_version is not None:
                    canonical_inputs["expected_version"] = expected_version
            elif action == "blackboard_merge" and remote_sections is not None:
                canonical_inputs["remote_sections"] = remote_sections
            if action != "blackboard_update" and (
                content is not None or author != "agent" or expected_version is not None
            ):
                return services_module.contract_error("content, author, and expected_version are only valid for action='blackboard_update'", status_code=400)
            if action != "blackboard_merge" and remote_sections is not None:
                return services_module.contract_error("remote_sections is only valid for action='blackboard_merge'", status_code=400)
            if action in {"blackboard_list", "blackboard_merge"} and section:
                return services_module.contract_error(f"section is not valid for action='{action}'", status_code=400)
            if action == "blackboard_list" and board_id:
                return services_module.contract_error("board_id is not valid for action='blackboard_list'", status_code=400)
        else:
            if task_id or board_id or section or content is not None or author != "agent" or remote_sections is not None or expected_version is not None:
                return services_module.contract_error(f"task and blackboard fields are not valid for action='{action}'", status_code=400)
            canonical_inputs.update(topic=topic)
            if action == "pubsub_publish":
                canonical_inputs.update(message=message, publisher=publisher)
                if after_seq is not None or limit is not None or after_ts is not None:
                    return services_module.contract_error("after_seq, limit, and after_ts are only valid for action='pubsub_poll'", status_code=400)
            else:
                if message is not None or publisher != "agent":
                    return services_module.contract_error("message and publisher are only valid for action='pubsub_publish'", status_code=400)
                if after_seq is not None:
                    canonical_inputs["after_seq"] = after_seq
                if limit is not None:
                    canonical_inputs["limit"] = limit
                if after_ts is not None:
                    canonical_inputs["after_ts"] = after_ts
        validation_error = services_module.validate_operation_arguments(
            "local_ai_coord", action, canonical_inputs,
        )
        if validation_error is not None:
            return services_module.contract_error(validation_error, status_code=400)
    legacy_coord_values: dict[str, dict[str, services_module.Any]] = {
        "ask": {"record_id": record_id, "key": key, "query": query, "value": value, "answer": answer},
        "answer": {"record_id": record_id, "key": key, "query": query, "value": value, "question": question},
        "task_cleanup_worktree": {"key": key},
        "context_compile": {
            "query": query, "value": value, "key": key, "record_id": record_id,
            "status": status, "fingerprint": fingerprint, "ttl_seconds": ttl_seconds,
        },
        "verify_receipt": {
            "checkpoint": checkpoint, "task_id": task_id, "criterion": criterion,
            "key": key, "value": value, "query": query, "status": status, "record": record,
        },
        "verify_completion": {"query": query, "value": value, "key": key},
        "verify_export": {"query": query, "value": value, "key": key, "section": section, "status": status},
        "swarm_dispatch": {
            "task": task, "value": value, "query": query, "paths": paths,
            "command": command, "approver": approver, "target_scope": target_scope,
            "key": key, "task_id": task_id,
        },
        "swarm_step": {
            "task": task, "task_id": task_id, "key": key, "target_scope": target_scope,
            "query": query, "record": record, "value": value, "paths": paths,
            "command": command, "approver": approver,
        },
        "swarm_status": {"task_id": task_id, "key": key, "task": task},
        "swarm_list": {"status": status},
        "swarm_cancel": {
            "task": task, "task_id": task_id, "key": key, "target_scope": target_scope,
            "query": query, "record": record, "value": value,
        },
        "worktree_lease": {"task": task, "task_id": task_id, "key": key, "value": value, "lease_id": lease_id, "worktree_path": worktree_path},
        "worktree_release": {
            "task": task, "task_id": task_id, "key": key, "value": value,
            "lease_id": lease_id, "target_scope": target_scope, "status": status,
        },
        "simulate_merge": {
            "task": task, "task_id": task_id, "key": key, "value": value,
            "branch": branch, "target_scope": target_scope, "query": query,
        },
        "curate_dataset": {
            "task": task, "task_id": task_id, "key": key, "value": value,
            "query": query, "status": status, "target_scope": target_scope,
        },
        "negative_knowledge_record": {
            "key": key, "value": value, "query": query, "reason": reason,
            "status": status, "record_id": record_id, "tool_outcome": tool_outcome,
            "fingerprint": fingerprint, "state_revision": state_revision,
            "repository_revision": repository_revision,
        },
        "negative_knowledge_find": {
            "key": key, "value": value, "reason": reason, "status": status,
            "record_id": record_id, "tool_outcome": tool_outcome, "fingerprint": fingerprint,
            "record": record, "state_revision": state_revision,
            "repository_revision": repository_revision,
        },
        "incident_decision": {
            "value": value, "query": query, "reason": reason, "status": status,
            "record_id": record_id, "tool_outcome": tool_outcome, "record": record,
            "repository_revision": repository_revision, "key": key,
        },
    }
    if action in legacy_coord_values and any(
        (value != "" if isinstance(value, str) else value != 0 if type(value) is int else value is not None)
        for value in legacy_coord_values[action].values()
    ):
        return services_module.contract_error(f"action='{action}' accepts only canonical fields", status_code=400)
    if action in {"negative_knowledge_record", "incident_decision"} and limit is not None:
        return services_module.contract_error(f"limit is not valid for action='{action}'", status_code=400)
    if receipt is not None and action != "verify_receipt":
        return services_module.contract_error("receipt is only valid for action='verify_receipt'", status_code=400)
    if since_hash != "" and action != "context_compile":
        return services_module.contract_error("since_hash is only valid for action='context_compile'", status_code=400)
    if format is not None and action not in {"verify_export", "curate_dataset"}:
        return services_module.contract_error("format is only valid for action='verify_export' or 'curate_dataset'", status_code=400)
    if action == "curate_dataset" and type(min_receipts) is not int:
        return services_module.contract_error("min_receipts must be an integer for action='curate_dataset'", status_code=400)
    if action == "curate_dataset" and laya_operation is not None and type(laya_operation) is not dict:
        return services_module.contract_error("laya_operation must be an object", status_code=400)
    coord_canonical_inputs: dict[str, dict[str, services_module.Any]] = {
        "task_checkpoint": {
            "root": root, "task_id": task_id, "checkpoint": checkpoint,
        },
        "ask": {
            "root": root, "session_id": session_id,
            "question_id": question_id, "question": question, "task_id": task_id,
        },
        "answer": {"root": root, "question_id": question_id, "answer": answer, "task_id": task_id},
        "task_cleanup_worktree": {"root": root, "task_id": task_id},
        "task_zombie_reap": {"root": root, "task_id": task_id},
        "context_compile": {
            "root": root, "task_id": task_id, "since_hash": since_hash,
            "max_tokens": max_tokens or 4000, "include_diagnostics": include_diagnostics,
            "clone_id": clone_id, "worktree_id": worktree_id, "branch": branch,
            "repository_id": repository_id, "session_id": session_id,
            "repository_revision": repository_revision, "phase": phase,
            "focus": focus or [], "preload_profile": preload_profile,
        },
        "verify_receipt": {"root": root, "receipt": receipt},
        "verify_completion": {"root": root, "task_id": task_id, "repository_revision": repository_revision},
        "verify_export": {"root": root, "task_id": task_id, "format": "markdown" if format is None else format},
        "swarm_dispatch": {
            "root": root, "goal": goal,
            "target_paths": [] if target_paths is None else target_paths,
            "test_command": test_command, "author": author,
        },
        "swarm_step": {
            "root": root, "swarm_id": swarm_id, "role": role,
            "swarm_action": swarm_action, "payload": {} if payload is None else payload,
        },
        "swarm_status": {"root": root, "swarm_id": swarm_id},
        "swarm_list": {"root": root, "state": state},
        "swarm_cancel": {"root": root, "swarm_id": swarm_id, "reason": reason},
        "worktree_lease": {"root": root, "branch": branch},
        "worktree_release": {
            "root": root, "worktree_path": worktree_path,
            "worktree_id": worktree_id, "delete_branch": delete_branch, "branch": branch,
        },
        "simulate_merge": {"root": root, "source_branch": source_branch, "target_branch": target_branch},
        "curate_dataset": {
            "root": root,
            "output_path": output_path,
            "min_receipts": min_receipts,
            "format": "jsonl" if format is None else format,
            "laya_operation": laya_operation,
        },
        "negative_knowledge_record": {"root": root, "record": record},
        "negative_knowledge_find": {
            "root": root, "query": query,
            "limit": 100 if limit is None else limit,
        },
        "incident_decision": {
            "root": root, "fingerprint": fingerprint,
            "state_revision": state_revision,
        },
        "wait_for_event": {k: v for k, v in {"root": root, "topic": topic, "timeout": timeout, "filter": filter or filter_payload}.items() if v is not None and v != ""},
        "semaphore_acquire": {k: v for k, v in {"root": root, "name": name, "capacity": capacity, "timeout": timeout, "ttl_seconds": ttl_seconds, "purpose": purpose, "owner": owner}.items() if v is not None and v != ""},
        "semaphore_release": {k: v for k, v in {"root": root, "name": name, "lease_id": lease_id, "owner": owner}.items() if v is not None and v != ""},
        "semaphore_status": {k: v for k, v in {"root": root, "name": name}.items() if v is not None and v != ""},
        "session_briefing": {k: v for k, v in {"root": root, "session_id": session_id, "include": include}.items() if v is not None and v != ""},
    }
    if action in coord_canonical_inputs:
        canonical_inputs = coord_canonical_inputs[action]
        if action == "context_compile" and paths is not None:
            canonical_inputs["paths"] = paths
        validation_error = services_module.validate_operation_arguments(
            "local_ai_coord", action, canonical_inputs,
        )
        if validation_error is not None:
            return services_module.contract_error(validation_error, status_code=400)
    if action == "task_checkpoint":
        required_checkpoint_fields = {
            "phase": str,
            "next_action": str,
            "affected_paths": list,
            "evidence_ids": list,
            "blockers": list,
            "state_data": dict,
        }
        if type(checkpoint) is not dict:
            return services_module.contract_error(
                "checkpoint must be a canonical object for action='task_checkpoint'",
                status_code=400,
            )
        missing = sorted(set(required_checkpoint_fields) - set(checkpoint))
        if missing:
            return services_module.contract_error(
                f"checkpoint is missing required field '{missing[0]}' for action='task_checkpoint'",
                status_code=400,
            )
        for field, expected_type in required_checkpoint_fields.items():
            if type(checkpoint[field]) is not expected_type:
                return services_module.contract_error(
                    f"checkpoint.{field} must be {expected_type.__name__} for action='task_checkpoint'",
                    status_code=400,
                )
        if not checkpoint["phase"].strip() or not checkpoint["next_action"].strip():
            return services_module.contract_error(
                "checkpoint.phase and checkpoint.next_action must be non-empty strings",
                status_code=400,
            )
        for field in ("affected_paths", "evidence_ids", "blockers"):
            if any(type(value) is not str for value in checkpoint[field]):
                return services_module.contract_error(
                    f"checkpoint.{field} items must be strings for action='task_checkpoint'",
                    status_code=400,
                )
        state_data = checkpoint.get("state_data")
        if isinstance(state_data, dict) and "memory_audit" in state_data:
            audit = state_data["memory_audit"]
            if not isinstance(audit, dict) or (not audit.get("used_ids") and not (isinstance(audit.get("not_used_reason"), str) and audit["not_used_reason"].strip())):
                return services_module.contract_error(
                    "checkpoint.state_data.memory_audit requires used_ids or nonempty not_used_reason",
                    status_code=400,
                )
    if action == "worktree_release" and not worktree_path and not worktree_id:
        return services_module.contract_error("worktree_path or worktree_id is required for action='worktree_release'", status_code=400)
    requested_root = str(root or "").strip()
    if action in {"curate_dataset", "task_budget_increase"} and not services_module.is_rooted_path(requested_root):
        return services_module.contract_error(f"explicit absolute root is required for action='{action}'", status_code=400)
    root = services_module._client_root(root)
    if action.startswith("task_"):
        rejection = services_module._subminimum_budget_rejection({"max_response_tokens": max_response_tokens})
        if rejection is not None:
            return rejection
    if action == "task_zombie_reap":
        reap_payload = {
            "action": "reap_expired", "auto_recover": True,
            "root": root, "task_id": task_id,
        }
        requested, _, _, budget_enabled = services_module._response_budget(action, {
            "max_response_tokens": max_response_tokens,
            "response_profile": response_profile,
            "reuse_key": reuse_key,
            "tool": action,
        })
        if budget_enabled:
            reap_payload["response_budget_tokens"] = requested
        return services_module._compact(services_module.CLIENT.post(
            "/api/agent-state/tasks", reap_payload, timeout=services_module._timeout("quick")
        ), "status")
    if action == "task_cleanup_worktree":
        cleanup_payload = {
            "action": "cleanup_worktree", "task_id": task_id,
        }
        requested, _, _, budget_enabled = services_module._response_budget(action, {
            "max_response_tokens": max_response_tokens,
            "response_profile": response_profile,
            "reuse_key": reuse_key,
            "tool": action,
        })
        if budget_enabled:
            cleanup_payload["response_budget_tokens"] = requested
        return services_module._compact(services_module.CLIENT.post(
            "/api/agent-state/tasks", cleanup_payload, timeout=services_module._timeout("quick")
        ), "status")
    if action in {"ask", "answer"}:
        question_payload = {
            "action": action, "root": root,
            "question_id": question_id, "task_id": task_id,
        }
        if action == "ask":
            question_payload.update(session_id=session_id, question=question)
        else:
            question_payload["answer"] = answer
        requested, _, _, budget_enabled = services_module._response_budget(action, {
            "max_response_tokens": max_response_tokens,
            "response_profile": response_profile,
            "reuse_key": reuse_key,
            "tool": action,
        })
        if budget_enabled:
            question_payload["response_budget_tokens"] = requested
        return services_module._compact(services_module.CLIENT.coord(**question_payload), "status", extra_fields=["question"])
    if action.startswith("task_"):
        task_kwargs: dict[str, services_module.Any] = {
            "action": action, "task_id": task_id, "contract": contract,
            "checkpoint": checkpoint, "status": status, "reason": reason,
            "root": root, "include_stale": include_stale,
        }
        if ttl_seconds is not None:
            task_kwargs["ttl_seconds"] = ttl_seconds
        if action == "task_budget_increase":
            task_kwargs = {"action": action, "root": root, "task_id": task_id,
                           "reason": reason, "budget": budget}
        if action == "task_repair_session":
            task_kwargs = {"action": action, "root": root, "task_id": task_id,
                           "session_id": session_id, "reason": reason}
        if action in {
            "task_create", "task_checkpoint", "task_fail", "task_transition", "task_complete",
            "task_rollback", "task_resume", "task_heartbeat", "task_budget_increase", "task_repair_session",
        }:
            budget_options = {
                "max_response_tokens": max_response_tokens,
                "response_profile": response_profile,
                "reuse_key": reuse_key,
                "tool": action,
            }
            subminimum = services_module._subminimum_budget_rejection(budget_options)
            if subminimum is not None:
                return subminimum
            requested, _, _, budget_enabled = services_module._response_budget(action, budget_options)
            if budget_enabled:
                task_kwargs["response_budget_tokens"] = requested
        if action == "task_list":
            task_kwargs["query"] = query
            task_kwargs["limit"] = limit if limit is not None else 20
            if offset is not None:
                task_kwargs["offset"] = offset
            if status:
                task_kwargs["status"] = status
            if owner:
                task_kwargs["owner"] = owner
        if action == "task_fail":
            fail_reason = reason or "Task failed"
            task_kwargs["reason"] = fail_reason
        if action == "task_create":
            task_inputs: dict[str, services_module.Any] = {
                "root": root, "task_id": task_id, "contract": contract,
            }
            flat_fields = {
                "goal": goal, "task": task, "paths": paths, "scope": scope,
                "acceptance_criteria": acceptance_criteria, "criteria": criteria,
                "title": title, "description": description,
                "criterion": criterion,
            }
            task_inputs.update({
                field: value for field, value in flat_fields.items()
                if value is not None and value not in ("", [], False, 0)
            })
            validation_error = services_module.validate_operation_arguments(
                "local_ai_coord", "task_create", task_inputs,
            )
            if validation_error is not None:
                return services_module.contract_error(validation_error, status_code=400)
        if action == "task_complete" and allow_adopt:
            task_kwargs["allow_adopt"] = True
        if action == "task_complete" and operator_waiver is not None:
            task_kwargs["operator_waiver"] = operator_waiver
        if action in {"task_claim", "task_adopt"}:
            return services_module._compact(services_module.CLIENT.coord(
                action="task_claim", task_id=task_id, owner=owner, root=root,
            ), "task_memory")
        task_result = services_module.CLIENT.coord(
            **task_kwargs,
        )
        if (action == "task_checkpoint" and budget_enabled
                and isinstance(task_result, dict)
                and task_result.get("success") is False
                and task_result.get("status_code") == 413
                and task_result.get("operation_not_started") is True
                and task_result.get("error") == "checkpoint_response_budget_too_small"):
            response_budget = task_result.get("response_budget")
            required_tokens = response_budget.get("required_tokens") if isinstance(response_budget, dict) else None
            if type(required_tokens) is int and required_tokens > requested:
                task_kwargs["response_budget_tokens"] = required_tokens
                task_result = services_module.CLIENT.coord(**task_kwargs)
        task_projection = services_module._compact(task_result, "task_memory")
        if (action == "task_list" and isinstance(task_result, dict)
                and task_result.get("success") is True and task_result.get("tasks") == []
                and isinstance(task_projection, dict) and task_projection.get("success") is True):
            task_projection["tasks"] = []
        return task_projection
    if action in {"memory_record", "memory_delete", "memory_promote"}:
        supplied = {"action": action, "root": root, "scope": scope}
        if action == "memory_record":
            supplied["key"] = key
            if value is not None:
                supplied["value"] = value
            if contradicts_record_id is not None:
                supplied["contradicts_record_id"] = contradicts_record_id
            if supersedes_record_id is not None:
                supplied["supersedes_record_id"] = supersedes_record_id
        if action in {"memory_delete", "memory_promote"}:
            supplied["record_id"] = record_id
        if action == "memory_promote":
            supplied["target_scope"] = target_scope
        if session_id:
            supplied["session_id"] = session_id
        for alias, alias_value in (("name", name), ("content", content), ("query", query)):
            if alias_value not in (None, ""):
                supplied[alias] = alias_value
        contract_error_value = services_module.validate_operation_arguments("local_ai_coord", action, supplied)
        if contract_error_value:
            return services_module.contract_error(contract_error_value, status_code=400)
    if action.startswith("memory_"):
        if value is None:
            value = ""
        mem_root = root if (requested_root and requested_root != ".") else services_module._workspace
        if not repository_id and mem_root:
            from .project_config import resolve_project_context
            from .state_paths import configured_state_dir
            try:
                ctx = resolve_project_context(mem_root, configured_state_dir(services_module.load_config()))
                repository_id = getattr(ctx, "coordination_id", "")
                if not scope_id and getattr(ctx, "root", None):
                    scope_id = str(ctx.root)
            except Exception:
                pass
        mem_include_all = True if (action == "memory_find" and not requested_root and not scope) else False
        memory_kwargs = {"action": action, "root": mem_root}
        for field, field_value in (
            ("scope", scope), ("scope_id", scope_id), ("task_id", task_id),
            ("session_id", session_id), ("clone_id", clone_id),
            ("worktree_id", worktree_id), ("branch", branch),
        ):
            if field_value and not (action == "memory_record" and field == "scope_id"):
                memory_kwargs[field] = field_value
        if action == "memory_record":
            memory_kwargs.update(key=key, value=value)
            if status:
                memory_kwargs["status"] = status
            if contradicts_record_id is not None:
                memory_kwargs["contradicts_record_id"] = contradicts_record_id
            if supersedes_record_id is not None:
                memory_kwargs["supersedes_record_id"] = supersedes_record_id
        elif action == "memory_find":
            memory_kwargs["query"] = query
            if key:
                memory_kwargs["key"] = key
            if status:
                memory_kwargs["status"] = status
        elif action in {"memory_get", "memory_delete", "memory_promote"}:
            memory_kwargs["record_id"] = record_id
        if action == "memory_promote":
            memory_kwargs["target_scope"] = target_scope
        if kind:
            memory_kwargs["kind"] = kind
        if mem_include_all:
            memory_kwargs["include_all_scopes"] = True
        if limit is not None:
            memory_kwargs["limit"] = limit
        if ttl_seconds is not None:
            memory_kwargs["ttl_seconds"] = ttl_seconds
        if confidence is not None:
            memory_kwargs["confidence"] = confidence
        return services_module._compact(services_module.CLIENT.coord(**memory_kwargs), "task_memory")
    if action == "context_compile":
        return services_module._context_pack_projection(services_module.CLIENT.post("/api/agent-state/context", {
            "action": "compile", "task_id": task_id,
            "token_budget": max_tokens or 4000, "root": root,
            "changed_paths": paths or [],
            "since_hash": since_hash,
            "compact": True,
            "include_diagnostics": bool(include_diagnostics),
            "clone_id": clone_id,
            "worktree_id": worktree_id,
            "branch": branch,
            "repository_id": repository_id,
            "session_id": session_id,
            "repository_revision": repository_revision,
            "phase": phase,
            "focus": list(focus or []),
            "preload_profile": preload_profile,
        }, timeout=services_module._timeout("context")))
    if action == "record_native_receipt":
        if not task_id or not criterion or not command_id:
            return services_module.contract_error("record_native_receipt requires task_id, criterion, and command_id")
        return services_module._compact(services_module.CLIENT.post("/api/agent-state/verification", {
            "action": "native_receipt", "root": root, "task_id": task_id,
            "criterion": criterion, "command_id": command_id,
        }, timeout=services_module._timeout("quick")), "verify")
    if action == "verify_receipt":
        return services_module._compact(services_module.CLIENT.post("/api/agent-state/verification", {
            "action": "receipt", "receipt": receipt, "root": root,
        }, timeout=services_module._timeout("quick")), "verify")
    if action == "verify_completion":
        return services_module._compact(services_module.CLIENT.post("/api/agent-state/verification", {
            "action": "completion", "task_id": task_id, "root": root,
            "repository_revision": repository_revision,
        }, timeout=services_module._timeout("quick")), "verify")
    if action == "verify_export":
        return services_module._compact(services_module.CLIENT.post("/api/agent-state/verification", {
            "action": "export", "task_id": task_id, "root": root,
            "format": "markdown" if format is None else format,
        }, timeout=services_module._timeout("quick")), "verify")
    if action == "negative_knowledge_record":
        rec = dict(record) if isinstance(record, dict) else {}
        if "paths" in rec and "affected_paths" not in rec:
            rec["affected_paths"] = rec.pop("paths")
        if "description" in rec and "message" not in rec:
            rec["message"] = rec.pop("description")
        if "reason" in rec and "root_cause" not in rec:
            rec["root_cause"] = rec.pop("reason")
        if "fix" in rec and "verified_fix" not in rec:
            rec["verified_fix"] = rec.pop("fix")
        if "error_class" in rec and "operation_class" not in rec:
            rec["operation_class"] = rec.pop("error_class")
        if paths and "affected_paths" not in rec:
            rec["affected_paths"] = paths
        if reason and "root_cause" not in rec:
            rec["root_cause"] = reason
        return services_module._compact(services_module.CLIENT.post("/api/agent-state/incidents", {
            **rec, "action": "record", "root": root,
        }, timeout=services_module._timeout("quick")), "task_memory")
    if action == "negative_knowledge_find":
        return services_module._compact(services_module.CLIENT.post("/api/agent-state/incidents", {
            "action": "find", "root": root,
            "query": query, "limit": 100 if limit is None else limit,
        }, timeout=services_module._timeout("quick")), "task_memory")
    if action == "incident_decision":
        return services_module._compact(services_module.CLIENT.coord(
            action=action, fingerprint=fingerprint, state_revision=state_revision,
            root=root,
        ), "status")
    if action == "client_status":
        from local_ai_hub.client_adapters.registry import (
            ClientRegistry,
        )
        agent_header = services_module.os.environ.get("LOCAL_AI_AGENT")
        adapter = ClientRegistry.get(agent_header=agent_header)
        report = adapter.capability_report(repo_root=services_module._client_root(root))
        report["success"] = True
        return services_module._compact(report, "coord")
    if action == "claim":
        result = services_module.CLIENT.post("/api/leases/claim_batch", {
            "owner": owner, "root": root, "paths": paths or [], "ttl_seconds": 900 if ttl_seconds is None else ttl_seconds, "purpose": purpose,
        })
        if isinstance(result, dict) and result.get("success") is True:
            lease = result.get("lease_id")
            if not isinstance(lease, str) or not services_module.re.fullmatch(r"lease_[0-9a-f]{20}", lease):
                return services_module._compact({"success": False, "mutation_applied": True, "outcome_unknown": True,
                                 "error": "lease claim returned invalid lease identity"})
            result = {key: result[key] for key in ("success", "lease_id", "expires_at") if key in result}
            result["mutation_applied"] = True
        return services_module._compact(result)
    if action == "release":
        result = services_module.CLIENT.post("/api/leases/release", {"owner": owner, "lease_id": lease_id})
        if isinstance(result, dict) and result.get("success") is True:
            rows = result.get("released_rows")
            if type(rows) is not int or rows < 0:
                return services_module._compact({"success": False, "outcome_unknown": True,
                                 "error": "lease release returned invalid row count"})
            result = {"success": True, "released_rows": rows, "mutation_applied": rows > 0}
        return services_module._compact(result)
    if action == "renew":
        return services_module._compact(services_module.CLIENT.post("/api/leases/renew", {"owner": owner, "lease_id": lease_id, "ttl_seconds": 900 if ttl_seconds is None else ttl_seconds}))
    if action == "leases":
        return services_module._compact(services_module.CLIENT.get(f"/api/leases?root={services_module.quote(root)}"))
    if action.startswith("blackboard_"):
        sub = action[len("blackboard_"):]
        payload: dict[str, services_module.Any] = {
            "action": sub,
            "root": root,
        }
        if sub != "list":
            payload["board_id"] = board_id or task_id or "default"
        if task_id:
            payload["task_id"] = task_id
        if sub in {"update", "get", "delete"}:
            payload["section"] = (section or "main") if sub == "update" else (section or None)
        if sub == "update":
            payload.update(content=content, author=author)
            if expected_version is not None:
                payload["expected_version"] = expected_version
        elif sub == "merge":
            payload["remote_sections"] = remote_sections
        return services_module._compact(services_module.CLIENT.post(
            "/api/agent-state/blackboard", payload, timeout=services_module._timeout("quick")
        ), "status")
    if action == "swarm_dispatch":
        return services_module._compact(services_module.CLIENT.post("/api/agent-state/swarm/dispatch", {
            "goal": goal,
            "target_paths": [] if target_paths is None else target_paths,
            "test_command": test_command,
            "author": author,
            "root": root or ".",
        }, timeout=services_module._timeout("quick")), "status")
    if action == "swarm_step":
        return services_module._compact(services_module.CLIENT.post("/api/agent-state/swarm/step", {
            "swarm_id": swarm_id,
            "role": role,
            "action": swarm_action,
            "payload": {} if payload is None else payload,
            "root": root or ".",
        }, timeout=services_module._timeout("quick")), "status")
    if action == "swarm_status":
        return services_module._compact(services_module.CLIENT.get(f"/api/agent-state/swarm/{services_module.quote(swarm_id)}?root={services_module.quote(root)}", timeout=services_module._timeout("quick")), "status")
    if action == "swarm_list":
        params = [f"root={services_module.quote(root)}"]
        if state:
            params.append(f"state={services_module.quote(state)}")
        return services_module._compact(services_module.CLIENT.get(f"/api/agent-state/swarm?{'&'.join(params)}", timeout=services_module._timeout("quick")), "status")
    if action == "swarm_cancel":
        return services_module._compact(services_module.CLIENT.post("/api/agent-state/swarm/cancel", {"swarm_id": swarm_id, "reason": reason, "root": root or "."}, timeout=services_module._timeout("quick")), "status")
    if action == "worktree_lease":
        return services_module._compact(services_module.CLIENT.coord(action="worktree_lease", root=root, branch=branch or None), "status")
    if action == "worktree_release":
        return services_module._compact(services_module.CLIENT.coord(action="worktree_release", root=root, worktree_path=worktree_path, worktree_id=worktree_id, delete_branch=delete_branch, branch=branch or None), "status")
    if action == "pubsub_publish":
        return services_module._compact(services_module.CLIENT.coord(
            action="pubsub_publish", topic=topic, message=message,
            publisher=publisher, root=root,
        ), "status")
    if action == "pubsub_poll":
        return services_module._compact(services_module.CLIENT.coord(
            action="pubsub_poll", topic=topic, after_seq=after_seq,
            limit=limit, after_ts=after_ts, root=root,
        ), "status")
    if action == "simulate_merge":
        return services_module._compact(
            services_module.CLIENT.coord(
                action="simulate_merge",
                root=root,
                source_branch=source_branch,
                target_branch=target_branch,
            ),
            "general",
            extra_fields=["mergeable", "conflicts", "exit_code"],
        )
    if action == "curate_dataset":
        payload = {
            "action": "curate_dataset",
            "root": root,
            "output_path": output_path,
            "min_receipts": min_receipts,
            "format": "jsonl" if format is None else format,
        }
        if laya_operation is not None:
            payload["laya_operation"] = laya_operation
        return services_module._compact(services_module.CLIENT.post(
            "/api/agent-state/tasks", payload, timeout=services_module._timeout("quick"),
        ), "status", ["service_available", "model_resident", "runtime"])
    if action in {
        "wait_for_event", "semaphore_acquire", "semaphore_release", "semaphore_status",
        "session_briefing",
    }:
        coord_kwargs = dict(
            action=action, root=root,
            name=name,
            capacity=capacity, timeout=timeout, ttl_seconds=ttl_seconds, purpose=purpose,
            owner=owner, lease_id=lease_id, topic=topic,
            filter=filter or filter_payload, limit=limit, include=include, session_id=session_id,
            query=query,
        )
        return services_module._compact(services_module.CLIENT.coord(**coord_kwargs), "status")
    return services_module._invalid_action("local_ai_coord", action, tuple(services_module.CoordAction.__args__), "Use coordination for bounded shared state; the main agent remains the owner of final integration.")

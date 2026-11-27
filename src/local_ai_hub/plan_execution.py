"""Read-only plan coverage derived from current Agent OS verification gates."""
from __future__ import annotations

import json
import time
from collections import Counter, defaultdict, deque
from typing import Any

from .verified_execution import EXECUTION_KEY

MAX_PLAN_TASKS = 64
MAX_REFERENCED_PLANS = 16


def partition_coverage(configs: list[dict[str, Any]], *,
                       verified: list[bool] | None = None) -> list[dict[str, Any]]:
    """Never combine different manifests or check matrices into one coverage claim."""
    if verified is not None and len(verified) != len(configs):
        raise ValueError("partition verification flags must match configurations")
    groups: dict[tuple[str, str, int, int, str, str, str, str, bool], list[tuple[int, bool]]] = defaultdict(list)
    for position, config in enumerate(configs):
        inventory = config.get("inventory", {})
        partition = inventory.get("partition")
        if not partition:
            continue
        key = (
            partition["manifest_sha256"],
            json.dumps(inventory["checks"], sort_keys=True, separators=(",", ":")),
            partition["size"],
            partition["total"], inventory.get("scope", "repository"), inventory.get("base_revision", ""),
            inventory.get("policy_sha256", ""),
            json.dumps(inventory.get("exclusions", []), sort_keys=True, separators=(",", ":")),
            inventory.get("include_python_imports", False),
        )
        groups[key].append((partition["index"], verified[position] if verified is not None else False))
    result = []
    for (digest, _checks, size, total, _scope, _base, _policy, _exclusions, _python_imports), entries in sorted(groups.items()):
        indices = [index for index, _ in entries]
        seen = set(indices)
        verified_indices = {index for index, passed in entries if passed}
        missing = sorted(set(range(total)) - seen)
        duplicate_count = len(indices) - len(seen)
        result.append({
            "manifest_sha256": digest, "partition_size": size,
            "expected_partitions": total, "present_partitions": len(seen),
            "missing_count": len(missing), "missing_preview": missing[:12],
            "duplicate_count": duplicate_count,
            "complete": not missing and not duplicate_count,
            **({"verified_partitions": len(verified_indices),
                "verified_complete": not missing and not duplicate_count and len(verified_indices) == total,
                "unverified_preview": sorted(seen - verified_indices)[:12]} if verified is not None else {}),
        })
    return result


def verified_dependency_closure(
    specs: dict[tuple[str, str], dict[str, Any]], candidates: set[tuple[str, str]],
) -> set[tuple[str, str]]:
    """Resolve exact verified prerequisites across a bounded observed plan graph."""
    pending = set(candidates)
    verified: set[tuple[str, str]] = set()
    while pending:
        ready = {
            key for key in pending
            if key in specs and all((dep["plan_id"], dep["task_id"]) in verified
                                   for dep in specs[key].get("depends_on", []))
        }
        if not ready:
            break
        verified.update(ready)
        pending.difference_update(ready)
    return verified


def reconcile_plan_dependencies(
    plan_id: str, tasks: dict[str, Any], rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Single-plan closure for callers without external verification snapshots."""
    verified = verified_dependency_closure(
        {(plan_id, task_id): spec for task_id, spec in tasks.items()},
        {(plan_id, row["plan_task_id"]) for row in rows if row["status"] == "verified"},
    )
    return _apply_dependency_closure(plan_id, rows, verified)


def _apply_dependency_closure(
    plan_id: str, rows: list[dict[str, Any]], verified: set[tuple[str, str]],
) -> list[dict[str, Any]]:
    return [
        {**row, "status": "dependency_unverified", "receipt_status": "verified"}
        if row["status"] == "verified" and (plan_id, row["plan_task_id"]) not in verified
        else dict(row)
        for row in rows
    ]


def plan_actionability(plan_id: str, tasks: dict[str, Any], rows: list[dict[str, Any]], *,
                       external_verified: set[tuple[str, str]] | None = None,
                       external_observed: set[tuple[str, str]] | None = None) -> dict[str, Any]:
    """Conservative local-plan scheduling preview, not authorization to execute."""
    by_id = {row["plan_task_id"]: row for row in rows}
    verified = {task_id for task_id, row in by_id.items() if row["status"] == "verified"}
    verified_refs = {(plan_id, task_id) for task_id in verified} | (external_verified or set())
    observed_refs = external_observed or set()
    ready: list[dict[str, Any]] = []
    waiting: list[dict[str, Any]] = []
    for task_id, row in by_id.items():
        spec = tasks[task_id]
        if row["status"] == "verified" or spec.get("work_status") == "cancelled":
            continue
        dependencies = spec.get("depends_on", [])
        unresolved = [
            {"plan_id": dep["plan_id"], "task_id": dep["task_id"],
             "reason": ("local_dependency_unverified" if dep["plan_id"] == plan_id
                        else "external_dependency_unverified" if (dep["plan_id"], dep["task_id"]) in observed_refs
                        else "external_plan_unchecked")}
            for dep in dependencies
            if (dep["plan_id"], dep["task_id"]) not in verified_refs
        ]
        if unresolved:
            waiting.append({"plan_task_id": task_id, "reason": "dependencies_unverified",
                            "waiting_count": len(unresolved), "waiting_preview": unresolved[:12]})
        elif (row["status"] not in {"unbound", "incomplete"}
              or spec.get("work_status") == "blocked" or spec.get("blocker")):
            waiting.append({"plan_task_id": task_id, "reason": "task_blocked_or_binding_conflict"})
        else:
            ready.append({"plan_task_id": task_id, "status": row["status"],
                          "next_obligation": row.get("next_obligation")})
    ready.sort(key=lambda row: (row["status"] != "incomplete", row["plan_task_id"]))
    waiting.sort(key=lambda row: row["plan_task_id"])
    return {"ready_count": len(ready), "waiting_count": len(waiting),
            "next_plan_task": ready[0] if ready else None,
            "ready_preview": ready[:12], "waiting_preview": waiting[:12]}


def _revision(tracker: Any, root: str) -> str:
    if tracker is None:
        return ""
    state = tracker.fingerprint(root, force=True)
    if (not isinstance(state, dict) or state.get("success") is False
            or state.get("degraded") or state.get("stale")):
        return ""
    return str(state.get("fingerprint", "") or "").strip()


def plan_execution_preview(workspace: Any, plan_id: str, task_store: Any,
                           verifier: Any, tracker: Any) -> dict[str, Any]:
    """Bounded advisory snapshot; does not change plan status or issue receipts."""
    from .agent_tasks import _task_scope_root
    from .repo_plan.agent_bridge import TaskBindingManager
    from .verification_rules import evaluate_project_completion

    snapshot = workspace.get_plan(plan_id)
    root = str(workspace.repo_root)
    tasks = snapshot["plan"].get("tasks", {})
    revision = _revision(tracker, root)
    if not revision or task_store is None or verifier is None:
        return {"complete": False, "status": "verification_unavailable",
                "total_tasks": len(tasks), "scanned_tasks": 0}
    manager = TaskBindingManager(root)
    from .repo_plan.schema_validation import RepoPlanConflictError, RepoPlanNotFoundError, RepoPlanValidationError

    snapshots = {plan_id: snapshot}
    binding_snapshots = {plan_id: manager.bindings_for_plan(plan_id)}
    binding_indexes: dict[str, dict[str, list[Any]]] = {}

    def bindings_index(ref_plan: str) -> dict[str, list[Any]]:
        if ref_plan not in binding_indexes:
            index: dict[str, list[Any]] = defaultdict(list)
            for binding in binding_snapshots[ref_plan]:
                index[binding.plan_task_id].append(binding)
            binding_indexes[ref_plan] = index
        return binding_indexes[ref_plan]

    deadline = time.monotonic() + 15.0
    rows: list[dict[str, Any]] = []
    configs: list[dict[str, Any]] = []
    config_task_ids: list[str] = []
    obligation_counts: Counter[str] = Counter()
    dimension_counts: dict[str, Counter[str]] = defaultdict(Counter)
    tasks_with_coverage = 0
    counts: Counter[str] = Counter()
    observed: list[tuple[str, Any]] = []
    graph_specs: dict[tuple[str, str], dict[str, Any]] = {}
    graph_rows: dict[tuple[str, str], dict[str, Any]] = {}

    def evaluate_row(ref_plan: str, task_key: str, spec: dict[str, Any]) -> tuple[dict[str, Any], Any]:
        row: dict[str, Any] = {"plan_task_id": task_key, "status": "unbound"}
        config: Any = None
        candidates = bindings_index(ref_plan).get(task_key, [])
        if not candidates:
            return row, config
        attempts = [(b, task_store.get(b.task_id)) for b in candidates]
        attempts.sort(key=lambda item: item[0].bound_at, reverse=True)
        binding, task = attempts[0]
        ambiguous = (len(attempts) > 1 and (
            binding.bound_at == attempts[1][0].bound_at or any(
                old is None or old.status.value not in {"completed", "cancelled"}
                for _, old in attempts[1:]
            )
        ))
        if ambiguous:
            row["status"] = "ambiguous_binding"
        elif (task is None or _task_scope_root(task) != root
              or binding.plan_rel_path != snapshots[ref_plan]["rel_path"]
              or not binding.session_id or binding.session_id != task.context.session_id
              or binding.contract_revision != task.checkpoint.state_data.get("contract_revision", 1)
              or tuple(spec.get("acceptance_criteria", ())) != task.contract.acceptance_criteria):
            row["status"] = "binding_conflict"
        else:
            # Observe all attempts: a stale/superseded attempt changing during
            # evaluation also invalidates the binding snapshot.
            observed.extend((attempt.task_id, state) for attempt, state in attempts)
            row["task_id"] = binding.task_id
            config = task.contract.slo_profile.get(EXECUTION_KEY)
            result = evaluate_project_completion(
                verifier, binding.task_id, root=root, current_revision=revision,
                state_dir=verifier.state_store.db_path.parent,
            )
            execution = result.execution
            row["coverage"] = execution.get("coverage", {})
            row["next_obligation"] = execution.get("next_obligation")
            row["status"] = (
                "verified" if result.complete and task.status.value == "completed"
                and spec.get("work_status") in {"done", "completed"}
                and not any(d.get("disposition") == "pending" for d in spec.get("deliveries", {}).values())
                else "incomplete"
            )
            row["_dimensions"] = execution.get("dimensions", {})
        return row, config

    pending: deque[tuple[str, str]] = deque()
    queued: set[tuple[str, str]] = set()

    def enqueue_dependencies(spec: dict[str, Any]) -> None:
        for dep in spec.get("depends_on", []):
            key = (dep["plan_id"], dep["task_id"])
            if key not in queued and key not in graph_rows:
                queued.add(key)
                pending.append(key)

    for plan_task_id, spec in tasks.items():
        if len(rows) >= MAX_PLAN_TASKS or time.monotonic() >= deadline:
            break
        row, config = evaluate_row(plan_id, plan_task_id, spec)
        coverage = row.get("coverage", {})
        dimensions = row.pop("_dimensions", {})
        if coverage:
            tasks_with_coverage += 1
            for key in ("total", "verified", "unverified", "stale", "dependency_blocked"):
                obligation_counts[key] += coverage.get(key, 0)
            for dimension, values in dimensions.items():
                for key in ("total", "verified"):
                    dimension_counts[dimension][key] += values.get(key, 0)
        if isinstance(config, dict):
            configs.append(config)
            config_task_ids.append(plan_task_id)
        rows.append(row)
        graph_specs[(plan_id, plan_task_id)] = spec
        graph_rows[(plan_id, plan_task_id)] = row
        enqueue_dependencies(spec)

    missing: set[tuple[str, str]] = set()
    unavailable_plans: set[str] = set()
    while pending and len(graph_rows) < MAX_PLAN_TASKS and time.monotonic() < deadline:
        key = pending.popleft()
        if key in graph_rows:
            continue
        ref_plan, ref_task = key
        if ref_plan in unavailable_plans:
            missing.add(key)
            continue
        if ref_plan not in snapshots:
            if len(snapshots) + len(unavailable_plans) >= MAX_REFERENCED_PLANS:
                pending.appendleft(key)
                break
            try:
                snapshots[ref_plan] = workspace.get_plan(ref_plan)
                binding_snapshots[ref_plan] = manager.bindings_for_plan(ref_plan)
            except (RepoPlanNotFoundError, RepoPlanValidationError, RepoPlanConflictError, OSError, ValueError):
                snapshots.pop(ref_plan, None)
                binding_snapshots.pop(ref_plan, None)
                unavailable_plans.add(ref_plan)
                missing.add(key)
                continue
        spec = snapshots[ref_plan]["plan"].get("tasks", {}).get(ref_task)
        if not isinstance(spec, dict):
            missing.add(key)
            continue
        row, _ = evaluate_row(ref_plan, ref_task, spec)
        row.pop("_dimensions", None)
        graph_rows[key] = row
        graph_specs[key] = spec
        enqueue_dependencies(spec)

    verified = verified_dependency_closure(
        graph_specs, {key for key, row in graph_rows.items() if row["status"] == "verified"},
    )
    rows = _apply_dependency_closure(plan_id, rows, verified)
    counts.update(row["status"] for row in rows)
    partitions = partition_coverage(configs, verified=[(plan_id, task_id) in verified for task_id in config_task_ids])
    try:
        stable = (
            all(workspace.get_plan(ref)["file_revision"] == item["file_revision"]
                for ref, item in snapshots.items())
            and _revision(tracker, root) == revision
            and all(manager.bindings_for_plan(ref) == items for ref, items in binding_snapshots.items())
            and all(task_store.get(task_id) == task for task_id, task in observed)
        )
    except (RepoPlanNotFoundError, RepoPlanValidationError, RepoPlanConflictError, OSError, ValueError):
        stable = False
    external_rows = {key: row for key, row in graph_rows.items() if key[0] != plan_id}
    external_verified = {key for key in verified if key[0] != plan_id}
    external_observed = set(external_rows) | {key for key in missing if key[0] != plan_id}
    unresolved = sorted(key for key in external_observed if key not in external_verified)
    unresolved_pending = {key for key in pending if key not in graph_rows}
    exhaustive = len(rows) == len(tasks)
    complete = bool(tasks) and stable and exhaustive and not unresolved_pending and counts["verified"] == len(tasks) and all(
        group["verified_complete"] for group in partitions
    )
    return {
        "complete": complete, "status": "snapshot" if stable else "snapshot_changed",
        "total_tasks": len(tasks), "scanned_tasks": len(rows),
        "truncated": not exhaustive, "counts": dict(counts),
        "repository_revision": revision, "plan_revision": snapshot["file_revision"],
        "partition_groups": partitions, "tasks": rows,
        "referenced_dependencies": {"scanned_plans": len(snapshots), "scanned_tasks": len(external_rows),
                                    "verified_tasks": len(external_verified), "unresolved_count": len(unresolved),
                                    "unresolved_preview": [{"plan_id": p, "task_id": t} for p, t in unresolved[:12]],
                                    "truncated": bool(unresolved_pending)},
        "actionability": plan_actionability(plan_id, tasks, rows, external_verified=external_verified,
                                             external_observed=external_observed) if stable and exhaustive and not unresolved_pending else {
            "status": "partial_or_changed_snapshot", "next_plan_task": None,
        },
        "obligation_coverage": {"tasks_with_coverage": tasks_with_coverage,
                                "counts": dict(obligation_counts),
                                "dimensions": {name: dict(values) for name, values in sorted(dimension_counts.items())},
                                "partial": not exhaustive or tasks_with_coverage != len(tasks) or not stable},
        "advisory": True,
    }

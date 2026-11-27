"""Read-only plan coverage derived from current Agent OS verification gates."""
from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from typing import Any

from .verified_execution import EXECUTION_KEY

MAX_PLAN_TASKS = 64


def partition_coverage(configs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Never combine different manifests or check matrices into one coverage claim."""
    groups: dict[tuple[str, str, int, int, str, str, str], list[int]] = defaultdict(list)
    for config in configs:
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
        )
        groups[key].append(partition["index"])
    result = []
    for (digest, _checks, size, total, _scope, _base, _policy), indices in sorted(groups.items()):
        seen = set(indices)
        missing = sorted(set(range(total)) - seen)
        duplicate_count = len(indices) - len(seen)
        result.append({
            "manifest_sha256": digest, "partition_size": size,
            "expected_partitions": total, "present_partitions": len(seen),
            "missing_count": len(missing), "missing_preview": missing[:12],
            "duplicate_count": duplicate_count,
            "complete": not missing and not duplicate_count,
        })
    return result


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
    bindings = manager.bindings_for_plan(plan_id)
    by_plan_task: dict[str, list[Any]] = defaultdict(list)
    for binding in bindings:
        by_plan_task[binding.plan_task_id].append(binding)
    deadline = time.monotonic() + 15.0
    rows: list[dict[str, Any]] = []
    configs: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    observed = []
    for plan_task_id, spec in tasks.items():
        if len(rows) >= MAX_PLAN_TASKS or time.monotonic() >= deadline:
            break
        row: dict[str, Any] = {"plan_task_id": plan_task_id, "status": "unbound"}
        candidates = by_plan_task.get(plan_task_id, [])
        if candidates:
            # Multiple attempts are accepted only if the newest uniquely
            # supersedes terminal older attempts; never pick arbitrary evidence.
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
                  or binding.plan_rel_path != snapshot["rel_path"]
                  or not binding.session_id or binding.session_id != task.context.session_id
                  or binding.contract_revision != task.checkpoint.state_data.get("contract_revision", 1)
                  or tuple(spec.get("acceptance_criteria", ())) != task.contract.acceptance_criteria):
                row["status"] = "binding_conflict"
            else:
                observed.append((binding.task_id, task))
                row["task_id"] = binding.task_id
                config = task.contract.slo_profile.get(EXECUTION_KEY)
                if isinstance(config, dict):
                    configs.append(config)
                result = evaluate_project_completion(
                    verifier, binding.task_id, root=root, current_revision=revision,
                    state_dir=verifier.state_store.db_path.parent,
                )
                execution = result.execution
                coverage = execution.get("coverage", {})
                row["coverage"] = coverage
                row["next_obligation"] = execution.get("next_obligation")
                row["status"] = (
                    "verified" if result.complete and task.status.value == "completed"
                    and spec.get("work_status") in {"done", "completed"}
                    and not any(d.get("disposition") == "pending" for d in spec.get("deliveries", {}).values())
                    else "incomplete"
                )
        counts[row["status"]] += 1
        rows.append(row)
    partitions = partition_coverage(configs)
    stable = (
        workspace.get_plan(plan_id)["file_revision"] == snapshot["file_revision"]
        and _revision(tracker, root) == revision
        and manager.bindings_for_plan(plan_id) == bindings
        and all(task_store.get(task_id) == task for task_id, task in observed)
    )
    exhaustive = len(rows) == len(tasks)
    complete = bool(tasks) and stable and exhaustive and counts["verified"] == len(tasks) and all(
        group["complete"] for group in partitions
    )
    return {
        "complete": complete, "status": "snapshot" if stable else "snapshot_changed",
        "total_tasks": len(tasks), "scanned_tasks": len(rows),
        "truncated": not exhaustive, "counts": dict(counts),
        "repository_revision": revision, "plan_revision": snapshot["file_revision"],
        "partition_groups": partitions, "tasks": rows,
        "advisory": True,
    }

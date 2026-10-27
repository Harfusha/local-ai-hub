"""Project workspace management and scoped Kanban board projections for repo plans."""

from __future__ import annotations

import logging
import copy
import json
import re
from pathlib import Path
from typing import Any

from local_ai_hub.project_config import resolve_project_config

from .models import PlanLifecycle
from .schema_validation import (
    PLAN_ID_REGEX,
    TASK_ID_REGEX,
    RepoPlanConflictError,
    RepoPlanNotFoundError,
    RepoPlanValidationError,
    validate_plan_dict,
    validate_repo_path,
)
from .storage import RepoPlanStorage, get_git_context

logger = logging.getLogger(__name__)
_UNSET = object()

DEFAULT_README_CONTENT = """# Local AI Hub Project Workspace

This directory contains repository-owned project plans, adopted specifications, and decisions.

- `plans/`: Authoritative, versioned `.plan.json` files for project goals and tasks.
- `local/`: Machine-local cache, durable intents, and runtime session bindings (ignored by Git).
"""

DEFAULT_GITIGNORE_CONTENT = """# Local AI Hub workspace ignores
local/
.tmp_*
*.tmp
"""


class RepoPlanWorkspace:
    """High-level workspace operations and Kanban view over repository plan files."""

    def __init__(self, repo_root: str | Path) -> None:
        self.repo_root = Path(repo_root).resolve()
        config_res = resolve_project_config(self.repo_root)
        self.settings = config_res.settings.workspace
        self._validate_workspace_paths()
        self.plans_dir = self.repo_root / self.settings.plans_dir
        self.intents_dir = self.repo_root / self.settings.intents_dir
        self.storage = RepoPlanStorage(self.repo_root, intents_dir=self.settings.intents_dir)

    def _validate_workspace_paths(self) -> None:
        validate_repo_path(".local-ai-hub", repo_root=self.repo_root)
        for name in ("plans_dir", "specs_dir", "decisions_dir", "knowledge_dir", "local_dir", "intents_dir"):
            validate_repo_path(getattr(self.settings, name), repo_root=self.repo_root)

    def init_workspace(self, force: bool = False) -> dict[str, Any]:
        """Initialize project workspace folder structure, README, and .gitignore."""
        self._validate_workspace_paths()
        created_paths: list[str] = []
        existing_paths: list[str] = []

        workspace_dir = self.repo_root / ".local-ai-hub"
        workspace_dir.mkdir(parents=True, exist_ok=True)
        self.plans_dir.mkdir(parents=True, exist_ok=True)
        self.intents_dir.mkdir(parents=True, exist_ok=True)

        readme_file = workspace_dir / "README.md"
        if not readme_file.exists() or force:
            readme_file.write_text(DEFAULT_README_CONTENT, encoding="utf-8")
            created_paths.append(".local-ai-hub/README.md")
        else:
            existing_paths.append(".local-ai-hub/README.md")

        gitignore_file = workspace_dir / ".gitignore"
        if not gitignore_file.exists() or force:
            gitignore_file.write_text(DEFAULT_GITIGNORE_CONTENT, encoding="utf-8")
            created_paths.append(".local-ai-hub/.gitignore")
        else:
            existing_paths.append(".local-ai-hub/.gitignore")

        return {
            "success": True,
            "root": str(self.repo_root),
            "plans_dir": str(self.plans_dir.relative_to(self.repo_root).as_posix()),
            "created_paths": created_paths,
            "existing_paths": existing_paths,
        }

    def has_workspace(self) -> bool:
        """Check if workspace directory or plans directory exists."""
        ws_dir = self.repo_root / ".local-ai-hub"
        return ws_dir.exists() and (self.plans_dir.exists() or any(ws_dir.iterdir()))

    def _plan_rel_path(self, plan_id: str) -> str:
        if not isinstance(plan_id, str) or not PLAN_ID_REGEX.fullmatch(plan_id):
            raise RepoPlanValidationError(f"Invalid plan ID: {plan_id!r}")
        direct = self.plans_dir / f"{plan_id}.plan.json"
        if direct.exists():
            return direct.relative_to(self.repo_root).as_posix()
        matches: list[Path] = []
        if self.plans_dir.exists():
            for path in sorted(self.plans_dir.glob("*.plan.json")):
                if path.is_symlink():
                    continue
                try:
                    raw = path.read_bytes()
                    if len(raw) > 1024 * 1024:
                        continue
                    data = json.loads(raw.decode("utf-8"))
                except (OSError, UnicodeError, ValueError):
                    continue
                if isinstance(data, dict) and data.get("id") == plan_id:
                    matches.append(path)
                    if len(matches) > 1:
                        break
        if len(matches) > 1:
            raise RepoPlanValidationError(f"Duplicate plan identity '{plan_id}' in this worktree")
        return (matches[0] if matches else direct).relative_to(self.repo_root).as_posix()

    def list_plans(
        self,
        lifecycle: str | None = None,
        query: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List plans in the workspace with metadata and task counts."""
        if not self.plans_dir.exists():
            return []

        plans: list[dict[str, Any]] = []
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise RepoPlanValidationError("limit must be an integer from 1 to 1000")
        query_clean = (query or "").strip().lower()

        for path in sorted(self.plans_dir.glob("*.plan.json")):
            rel_path = path.relative_to(self.repo_root).as_posix()
            try:
                data, rev = self.storage.read_plan_file(rel_path)
            except Exception as exc:
                logger.warning("Failed to load plan %s: %s", path, exc)
                plans.append({"invalid": True, "rel_path": rel_path, "error": str(exc)})
                if len(plans) >= limit:
                    break
                continue

            plan_life = data.get("lifecycle", "draft")
            if lifecycle and plan_life != lifecycle:
                continue

            title = data.get("title", "")
            desc = data.get("description", "")
            if query_clean:
                searchable = f"{data.get('id', '')} {title} {desc}".lower()
                if query_clean not in searchable:
                    continue

            tasks = data.get("tasks", {})
            plans.append({
                "id": data.get("id"),
                "title": title,
                "description": desc,
                "lifecycle": plan_life,
                "default_target_ref": data.get("default_target_ref"),
                "task_count": len(tasks),
                "file_revision": rev,
                "rel_path": rel_path,
                "updated_at": path.stat().st_mtime,
            })
            if len(plans) >= limit:
                break

        return plans

    def get_plan(self, plan_id: str) -> dict[str, Any]:
        """Get full plan file dictionary and file revision."""
        rel_path = self._plan_rel_path(plan_id)
        data, rev = self.storage.read_plan_file(rel_path)
        if data.get("id") != plan_id:
            raise RepoPlanNotFoundError(f"Plan '{plan_id}' not found")
        branch, head = get_git_context(self.repo_root)
        return {
            "success": True,
            "plan": data,
            "file_revision": rev,
            "rel_path": rel_path,
            "git_branch": branch,
            "git_head": head,
        }

    def create_plan(
        self,
        plan_id: str,
        title: str,
        description: str = "",
        lifecycle: str = "draft",
        default_target_ref: str | None = "refs/heads/master",
        spec_refs: list[dict[str, Any]] | None = None,
        tasks: dict[str, Any] | None = None,
        accountable_role: str | None = None,
        owner: str = "agent",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Create a new plan file using the 9-step atomic save protocol."""
        self.init_workspace()
        rel_path = self._plan_rel_path(plan_id)
        full_path = self.repo_root / rel_path
        if full_path.exists() and not idempotency_key:
            raise RepoPlanConflictError(f"Plan file already exists: {rel_path}")

        plan_dict = {
            "schema_version": 1,
            "id": plan_id,
            "title": title,
            "description": description,
            "lifecycle": lifecycle,
            "default_target_ref": default_target_ref,
            "spec_refs": copy.deepcopy(spec_refs if spec_refs is not None else []),
            "tasks": {},
        }
        if accountable_role is not None:
            plan_dict["accountable_role"] = accountable_role
        if tasks is not None:
            if not isinstance(tasks, dict):
                raise RepoPlanValidationError("tasks must be an object keyed by stable task ID")
            for tid, raw_task in tasks.items():
                if not isinstance(raw_task, dict):
                    raise RepoPlanValidationError(f"Task '{tid}' must be an object")
                task = copy.deepcopy(raw_task)
                task.setdefault("description", "")
                task.setdefault("kind", "code")
                task.setdefault("work_status", "planned")
                task.setdefault("depends_on", [])
                task.setdefault("clarifications", [])
                task.setdefault("acceptance_criteria", [])
                task.setdefault("next_action", "")
                task.setdefault("blocker", None)
                plan_dict["tasks"][tid] = task
        validate_plan_dict(plan_dict, repo_root=self.repo_root)

        save_res = self.storage.save_plan_file(
            rel_path,
            plan_dict,
            expected_revision="",
            owner=owner,
            idempotency_key=idempotency_key,
        )
        return {
            "success": True,
            "root": str(self.repo_root),
            "plan_id": plan_id,
            "file_revision": save_res["file_revision"],
            "rel_path": rel_path,
            "plan": plan_dict,
        }

    def update_plan(
        self,
        plan_id: str,
        title: Any = _UNSET,
        description: Any = _UNSET,
        lifecycle: Any = _UNSET,
        default_target_ref: Any = _UNSET,
        spec_refs: Any = _UNSET,
        accountable_role: Any = _UNSET,
        expected_revision: str | None = None,
        owner: str = "agent",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Update top-level plan metadata. Preserves plan identity and does NOT rename file on title change."""
        rel_path = self._plan_rel_path(plan_id)
        plan_dict, current_rev = self.storage.read_plan_file(rel_path)

        if expected_revision is not None and expected_revision != current_rev:
            raise RepoPlanConflictError(
                f"Revision conflict on plan '{plan_id}': expected {expected_revision}, current {current_rev}"
            )

        for key, value in (("title", title), ("description", description),
                           ("lifecycle", lifecycle), ("default_target_ref", default_target_ref),
                           ("spec_refs", spec_refs), ("accountable_role", accountable_role)):
            if value is not _UNSET:
                plan_dict[key] = copy.deepcopy(value)

        validate_plan_dict(plan_dict, repo_root=self.repo_root)

        save_res = self.storage.save_plan_file(
            rel_path,
            plan_dict,
            expected_revision=current_rev,
            owner=owner,
            idempotency_key=idempotency_key,
        )
        return {
            "success": True,
            "plan_id": plan_id,
            "file_revision": save_res["file_revision"],
            "no_op": save_res.get("no_op", False),
            "plan": plan_dict,
        }

    def edit_task(
        self,
        plan_id: str,
        task_id: str,
        *,
        title: Any = _UNSET,
        description: Any = _UNSET,
        kind: Any = _UNSET,
        work_status: Any = _UNSET,
        depends_on: Any = _UNSET,
        clarifications: Any = _UNSET,
        acceptance_criteria: Any = _UNSET,
        next_action: Any = _UNSET,
        blocker: Any = _UNSET,
        order: Any = _UNSET,
        accountable_role: Any = _UNSET,
        work_phase: Any = _UNSET,
        spec_refs: Any = _UNSET,
        scope: Any = _UNSET,
        results: Any = _UNSET,
        deliveries: Any = _UNSET,
        expected_revision: str | None = None,
        owner: str = "agent",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Edit or create a task within a plan file using atomic save."""
        rel_path = self._plan_rel_path(plan_id)
        plan_dict, current_rev = self.storage.read_plan_file(rel_path)

        if expected_revision is not None and expected_revision != current_rev:
            raise RepoPlanConflictError(
                f"Revision conflict on plan '{plan_id}': expected {expected_revision}, current {current_rev}"
            )

        if not isinstance(task_id, str) or not TASK_ID_REGEX.fullmatch(task_id):
            raise RepoPlanValidationError(f"Invalid task ID: {task_id!r}")
        clean_task_id = task_id

        tasks = plan_dict.setdefault("tasks", {})
        task = tasks.get(clean_task_id)

        if task is None:
            # Create new task
            if title is _UNSET or not title:
                raise RepoPlanValidationError(f"Task '{clean_task_id}' requires a title to create")
            task = {
                "title": title,
                "description": "" if description is _UNSET else description,
                "kind": "code" if kind is _UNSET else kind,
                "work_status": "planned" if work_status is _UNSET else work_status,
                "depends_on": [] if depends_on is _UNSET else copy.deepcopy(depends_on),
                "clarifications": [] if clarifications is _UNSET else copy.deepcopy(clarifications),
                "acceptance_criteria": [] if acceptance_criteria is _UNSET else copy.deepcopy(acceptance_criteria),
                "next_action": "" if next_action is _UNSET else next_action,
                "blocker": None if blocker is _UNSET else blocker,
            }
            if order is not _UNSET:
                task["order"] = order
            if accountable_role is not _UNSET:
                task["accountable_role"] = accountable_role
            if work_phase is not _UNSET:
                task["work_phase"] = work_phase
            if spec_refs is not _UNSET:
                task["spec_refs"] = copy.deepcopy(spec_refs)
            if scope is not _UNSET:
                task["scope"] = copy.deepcopy(scope)
            if results is not _UNSET:
                task["results"] = copy.deepcopy(results)
            if deliveries is not _UNSET:
                task["deliveries"] = copy.deepcopy(deliveries)
            tasks[clean_task_id] = task
        else:
            # Patch existing task
            if title is not _UNSET:
                task["title"] = title
            if description is not _UNSET:
                task["description"] = description
            if kind is not _UNSET:
                task["kind"] = kind
            if work_status is not _UNSET:
                task["work_status"] = work_status
            if depends_on is not _UNSET:
                task["depends_on"] = copy.deepcopy(depends_on)
            if clarifications is not _UNSET:
                task["clarifications"] = copy.deepcopy(clarifications)
            if acceptance_criteria is not _UNSET:
                task["acceptance_criteria"] = copy.deepcopy(acceptance_criteria)
            if next_action is not _UNSET:
                task["next_action"] = next_action
            if blocker is not _UNSET:
                task["blocker"] = blocker
            if order is not _UNSET:
                task["order"] = order
            if accountable_role is not _UNSET:
                task["accountable_role"] = accountable_role
            if work_phase is not _UNSET:
                task["work_phase"] = work_phase
            if spec_refs is not _UNSET:
                task["spec_refs"] = copy.deepcopy(spec_refs)
            if scope is not _UNSET:
                task["scope"] = copy.deepcopy(scope)
            if results is not _UNSET:
                task["results"] = copy.deepcopy(results)
            if deliveries is not _UNSET:
                task["deliveries"] = copy.deepcopy(deliveries)

        validate_plan_dict(plan_dict, repo_root=self.repo_root)

        save_res = self.storage.save_plan_file(
            rel_path,
            plan_dict,
            expected_revision=current_rev,
            owner=owner,
            idempotency_key=idempotency_key,
        )
        return {
            "success": True,
            "plan_id": plan_id,
            "task_id": clean_task_id,
            "file_revision": save_res["file_revision"],
            "task": task,
        }

    def delete_task(
        self,
        plan_id: str,
        task_id: str,
        expected_revision: str | None = None,
        owner: str = "agent",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Delete a task from a plan file."""
        rel_path = self._plan_rel_path(plan_id)
        plan_dict, current_rev = self.storage.read_plan_file(rel_path)

        if expected_revision is not None and expected_revision != current_rev:
            raise RepoPlanConflictError(
                f"Revision conflict on plan '{plan_id}': expected {expected_revision}, current {current_rev}"
            )

        tasks = plan_dict.get("tasks", {})
        if task_id not in tasks:
            raise RepoPlanNotFoundError(f"Task '{task_id}' not found in plan '{plan_id}'")

        if tasks[task_id].get("work_status") in {"in_progress", "source_ready"}:
            raise RepoPlanConflictError("Cannot delete a task with active or unintegrated source work")
        if tasks[task_id].get("deliveries"):
            raise RepoPlanConflictError("Cannot delete a task with delivery obligations")
        if any(
            isinstance(dep, dict) and dep.get("plan_id", plan_id) == plan_id
            and dep.get("task_id") == task_id
            for other_id, other in tasks.items() if other_id != task_id
            for dep in other.get("depends_on", [])
        ):
            raise RepoPlanConflictError("Cannot delete a task referenced by another task")

        del tasks[task_id]
        validate_plan_dict(plan_dict, repo_root=self.repo_root)

        save_res = self.storage.save_plan_file(
            rel_path,
            plan_dict,
            expected_revision=current_rev,
            owner=owner,
            idempotency_key=idempotency_key,
        )
        return {
            "success": True,
            "plan_id": plan_id,
            "task_id": task_id,
            "file_revision": save_res["file_revision"],
        }

    def archive_plan(
        self,
        plan_id: str,
        expected_revision: str | None = None,
        owner: str = "agent",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Archive a plan file by setting its lifecycle to 'archived'."""
        return self.update_plan(
            plan_id=plan_id,
            lifecycle=PlanLifecycle.ARCHIVED.value,
            expected_revision=expected_revision,
            owner=owner,
            idempotency_key=idempotency_key,
        )

    def validate_plan(self, plan_id: str) -> dict[str, Any]:
        """Validate an existing plan file against schema and semantic invariants."""
        rel_path = self._plan_rel_path(plan_id)
        data, rev = self.storage.read_plan_file(rel_path)
        try:
            validate_plan_dict(data, repo_root=self.repo_root)
            return {"success": True, "valid": True, "plan_id": plan_id, "file_revision": rev}
        except RepoPlanValidationError as exc:
            return {"success": False, "valid": False, "plan_id": plan_id, "error": str(exc)}

    def get_board_view(
        self,
        plan_id: str | None = None,
        query: str | None = None,
        worktree_id: str | None = None,
    ) -> dict[str, Any]:
        """Project repository plan files into a scoped Kanban board view."""
        branch, head = get_git_context(self.repo_root)

        columns: dict[str, list[dict[str, Any]]] = {
            "planned": [],
            "ready": [],
            "in_progress": [],
            "blocked": [],
            "source_ready": [],
            "done": [],
        }

        plans_to_inspect = []
        if plan_id:
            try:
                rel_path = self._plan_rel_path(plan_id)
                data, rev = self.storage.read_plan_file(rel_path)
                plans_to_inspect.append((plan_id, rel_path, data, rev))
            except FileNotFoundError as exc:
                raise RepoPlanNotFoundError(f"Plan {plan_id!r} not found") from exc
            except RepoPlanValidationError as exc:
                raise RepoPlanValidationError(f"Cannot load plan {plan_id!r} for board: {exc}") from exc
        else:
            if self.plans_dir.exists():
                for ppath in sorted(self.plans_dir.glob("*.plan.json")):
                    rel = ppath.relative_to(self.repo_root).as_posix()
                    try:
                        pdata, prev = self.storage.read_plan_file(rel)
                        if pdata.get("lifecycle") not in {"archived", "cancelled"}:
                            plans_to_inspect.append((pdata.get("id", ""), rel, pdata, prev))
                    except RepoPlanValidationError as exc:
                        raise RepoPlanValidationError(f"Cannot load plan {rel!r} for board: {exc}") from exc

        query_clean = (query or "").strip().lower()
        counts: dict[str, int] = {k: 0 for k in columns}

        for pid, rel, pdata, prev in plans_to_inspect:
            plan_title = pdata.get("title", "")
            tasks = pdata.get("tasks", {})

            for tid, tdata in tasks.items():
                title = tdata.get("title", "")
                desc = tdata.get("description", "")
                if query_clean:
                    searchable = f"{tid} {title} {desc} {plan_title}".lower()
                    if query_clean not in searchable:
                        continue

                work_status = tdata.get("work_status", "planned").lower()
                target_col = work_status if work_status in columns else "planned"

                deliveries = tdata.get("deliveries", {})
                has_open_deliveries = any(
                    isinstance(d, dict) and d.get("disposition") == "pending"
                    for d in deliveries.values()
                )
                # File declarations and result references are not current verifier receipts.
                verified = False

                board_card = {
                    "task_id": tid,
                    "plan_id": pid,
                    "plan_title": plan_title,
                    "title": title,
                    "description": desc,
                    "kind": tdata.get("kind", "code"),
                    "accountable_role": tdata.get("accountable_role"),
                    "work_status": work_status,
                    "work_phase": tdata.get("work_phase"),
                    "order": tdata.get("order"),
                    "next_action": tdata.get("next_action", ""),
                    "blocker": tdata.get("blocker"),
                    "depends_on": tdata.get("depends_on", []),
                    "acceptance_criteria": tdata.get("acceptance_criteria", []),
                    "clarifications": tdata.get("clarifications", []),
                    "deliveries": deliveries,
                    "has_open_deliveries": has_open_deliveries,
                    "saved_to_file": True,
                    "verified": verified,
                    "verification_status": "unverified",
                    "plan_file_revision": prev,
                    "plan_rel_path": rel,
                }

                columns[target_col].append(board_card)
                counts[target_col] += 1

        total_items = sum(counts.values())
        return {
            "success": True,
            "project_root": str(self.repo_root),
            "git_branch": branch,
            "git_head": head,
            "plan_filter": plan_id,
            "columns": columns,
            "counts": counts,
            "total_items": total_items,
        }

    def adopt_legacy_board_items(
        self,
        plan_id: str = "default",
        board_items: list[dict[str, Any]] | None = None,
        legacy_items: list[dict[str, Any]] | None = None,
        title: str = "",
        owner: str = "agent",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Adopt SQLite board items into a file-backed plan without deleting the originals."""
        items_to_adopt = board_items if board_items is not None else (legacy_items or [])
        rel_path = self._plan_rel_path(plan_id)
        full_path = self.repo_root / rel_path
        if not full_path.exists():
            self.create_plan(
                plan_id=plan_id,
                title=title or f"Plan {plan_id}",
                description="Adopted from legacy board items",
                owner=owner,
            )
        plan_dict, current_rev = self.storage.read_plan_file(rel_path)
        board_items = items_to_adopt

        tasks = plan_dict.setdefault("tasks", {})
        adopted_count = 0

        for item in board_items:
            item_id = item.get("item_id", "")
            title = item.get("title", "").strip()
            if not title:
                continue

            # Convert item_id to valid task_id
            safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", item_id)
            task_id = f"task_{safe_id}" if not safe_id.startswith("task_") else safe_id

            if task_id in tasks:
                continue

            status = item.get("status", "planned").lower()
            plan_status = "planned"
            if status in {"in_progress", "active"}:
                plan_status = "in_progress"
            elif status == "done":
                plan_status = "done"
            elif status == "blocked":
                plan_status = "blocked"

            tasks[task_id] = {
                "title": title,
                "description": f"Adopted from board item {item_id}",
                "kind": "code",
                "work_status": plan_status,
                "depends_on": [],
                "clarifications": [],
                "acceptance_criteria": [],
                "next_action": "",
                "blocker": None,
            }
            adopted_count += 1

        validate_plan_dict(plan_dict, repo_root=self.repo_root)

        save_res = self.storage.save_plan_file(
            rel_path,
            plan_dict,
            expected_revision=current_rev,
            owner=owner,
            idempotency_key=idempotency_key,
        )
        return {
            "success": True,
            "plan_id": plan_id,
            "adopted_count": adopted_count,
            "tasks_imported": adopted_count,
            "file_revision": save_res["file_revision"],
        }

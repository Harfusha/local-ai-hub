"""Project workspace management and scoped Kanban board projections for repo plans."""

from __future__ import annotations

import logging
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
)
from .storage import RepoPlanStorage, get_git_context

logger = logging.getLogger(__name__)

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
        self.plans_dir = self.repo_root / self.settings.plans_dir
        self.intents_dir = self.repo_root / self.settings.intents_dir
        self.storage = RepoPlanStorage(self.repo_root, intents_dir=self.intents_dir)

    def init_workspace(self, force: bool = False) -> dict[str, Any]:
        """Initialize project workspace folder structure, README, and .gitignore."""
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
        clean_id = plan_id.strip()
        if not PLAN_ID_REGEX.match(clean_id):
            raise RepoPlanValidationError(f"Invalid plan ID: '{clean_id}'")
        rel_dir = self.plans_dir.relative_to(self.repo_root).as_posix()
        return f"{rel_dir}/{clean_id}.plan.json"

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
        query_clean = (query or "").strip().lower()

        for path in sorted(self.plans_dir.glob("*.plan.json")):
            rel_path = path.relative_to(self.repo_root).as_posix()
            try:
                data, rev = self.storage.read_plan_file(rel_path)
            except Exception as exc:
                logger.warning("Failed to load plan %s: %s", path, exc)
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
        goal: str = "",
        lifecycle: str = "draft",
        target_branch: str | None = None,
        default_target_ref: str | None = "refs/heads/master",
        specs: list[str] | None = None,
        spec_refs: list[dict[str, Any]] | None = None,
        decisions: list[str] | None = None,
        tasks: dict[str, Any] | None = None,
        owner: str = "agent",
    ) -> dict[str, Any]:
        final_desc = (description or goal or "").strip()
        final_target = f"refs/heads/{target_branch}" if target_branch else default_target_ref
        """Create a new plan file using the 9-step atomic save protocol."""
        self.init_workspace()
        rel_path = self._plan_rel_path(plan_id)
        full_path = self.repo_root / rel_path
        if full_path.exists():
            raise RepoPlanConflictError(f"Plan file already exists: {rel_path}")

        plan_dict = {
            "schema_version": 1,
            "id": plan_id.strip(),
            "title": title.strip(),
            "description": final_desc,
            "lifecycle": lifecycle.strip().lower(),
            "default_target_ref": final_target.strip() if final_target else None,
            "spec_refs": spec_refs or [],
            "tasks": {},
        }
        if tasks:
            for tid, t in tasks.items():
                if isinstance(t, dict):
                    t.setdefault("description", t.get("title", ""))
                    t.setdefault("kind", "code")
                    t.setdefault("work_status", "planned")
                    t.setdefault("depends_on", [])
                    t.setdefault("clarifications", [])
                    t.setdefault("acceptance_criteria", ["Initial acceptance criteria"])
                    t.setdefault("next_action", "")
                    t.setdefault("blocker", None)
            plan_dict["tasks"] = tasks
        validate_plan_dict(plan_dict, repo_root=self.repo_root)

        save_res = self.storage.save_plan_file(
            rel_path,
            plan_dict,
            expected_revision="",
            owner=owner,
        )
        return {
            "success": True,
            "plan_id": plan_id,
            "file_revision": save_res["file_revision"],
            "rel_path": rel_path,
            "plan": plan_dict,
        }

    def update_plan(
        self,
        plan_id: str,
        title: str | None = None,
        description: str | None = None,
        lifecycle: str | None = None,
        default_target_ref: str | None = None,
        expected_revision: str | None = None,
        owner: str = "agent",
    ) -> dict[str, Any]:
        """Update top-level plan metadata. Preserves plan identity and does NOT rename file on title change."""
        rel_path = self._plan_rel_path(plan_id)
        plan_dict, current_rev = self.storage.read_plan_file(rel_path)

        if expected_revision is not None and expected_revision != current_rev:
            raise RepoPlanConflictError(
                f"Revision conflict on plan '{plan_id}': expected {expected_revision}, current {current_rev}"
            )

        if title is not None:
            plan_dict["title"] = title.strip()
        if description is not None:
            plan_dict["description"] = description.strip()
        if lifecycle is not None:
            plan_dict["lifecycle"] = lifecycle.strip().lower()
        if default_target_ref is not None:
            plan_dict["default_target_ref"] = default_target_ref.strip() if default_target_ref else None

        validate_plan_dict(plan_dict, repo_root=self.repo_root)

        save_res = self.storage.save_plan_file(
            rel_path,
            plan_dict,
            expected_revision=current_rev,
            owner=owner,
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
        title: str | None = None,
        description: str | None = None,
        kind: str | None = None,
        work_status: str | None = None,
        depends_on: list[dict[str, Any]] | None = None,
        clarifications: list[dict[str, Any]] | None = None,
        acceptance_criteria: list[str] | None = None,
        next_action: str | None = None,
        blocker: str | None = None,
        order: int | None = None,
        accountable_role: str | None = None,
        work_phase: str | None = None,
        deliveries: dict[str, Any] | None = None,
        expected_revision: str | None = None,
        owner: str = "agent",
    ) -> dict[str, Any]:
        """Edit or create a task within a plan file using atomic save."""
        rel_path = self._plan_rel_path(plan_id)
        plan_dict, current_rev = self.storage.read_plan_file(rel_path)

        if expected_revision is not None and expected_revision != current_rev:
            raise RepoPlanConflictError(
                f"Revision conflict on plan '{plan_id}': expected {expected_revision}, current {current_rev}"
            )

        clean_task_id = task_id.strip()
        if not TASK_ID_REGEX.match(clean_task_id):
            raise RepoPlanValidationError(f"Invalid task ID: '{clean_task_id}'")

        tasks = plan_dict.setdefault("tasks", {})
        task = tasks.get(clean_task_id)

        if task is None:
            # Create new task
            if not title:
                raise RepoPlanValidationError(f"Task '{clean_task_id}' requires a title to create")
            task = {
                "title": title.strip(),
                "description": description.strip() if description else "",
                "kind": kind.strip().lower() if kind else "code",
                "work_status": work_status.strip().lower() if work_status else "planned",
                "depends_on": depends_on or [],
                "clarifications": clarifications or [],
                "acceptance_criteria": acceptance_criteria or [],
                "next_action": next_action.strip() if next_action else "",
                "blocker": blocker.strip() if blocker else None,
            }
            if order is not None:
                task["order"] = order
            if accountable_role is not None:
                task["accountable_role"] = accountable_role
            if work_phase is not None:
                task["work_phase"] = work_phase
            if deliveries:
                task["deliveries"] = deliveries
            tasks[clean_task_id] = task
        else:
            # Patch existing task
            if title is not None:
                task["title"] = title.strip()
            if description is not None:
                task["description"] = description.strip()
            if kind is not None:
                task["kind"] = kind.strip().lower()
            if work_status is not None:
                task["work_status"] = work_status.strip().lower()
            if depends_on is not None:
                task["depends_on"] = depends_on
            if clarifications is not None:
                task["clarifications"] = clarifications
            if acceptance_criteria is not None:
                task["acceptance_criteria"] = list(acceptance_criteria)
            if next_action is not None:
                task["next_action"] = next_action.strip()
            if blocker is not None:
                task["blocker"] = blocker.strip() if blocker else None
            if order is not None:
                task["order"] = order
            if accountable_role is not None:
                task["accountable_role"] = accountable_role
            if work_phase is not None:
                task["work_phase"] = work_phase
            if deliveries is not None:
                task["deliveries"] = deliveries

        validate_plan_dict(plan_dict, repo_root=self.repo_root)

        save_res = self.storage.save_plan_file(
            rel_path,
            plan_dict,
            expected_revision=current_rev,
            owner=owner,
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

        del tasks[task_id]
        validate_plan_dict(plan_dict, repo_root=self.repo_root)

        save_res = self.storage.save_plan_file(
            rel_path,
            plan_dict,
            expected_revision=current_rev,
            owner=owner,
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
    ) -> dict[str, Any]:
        """Archive a plan file by setting its lifecycle to 'archived'."""
        return self.update_plan(
            plan_id=plan_id,
            lifecycle=PlanLifecycle.ARCHIVED.value,
            expected_revision=expected_revision,
            owner=owner,
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
            except Exception as exc:
                logger.warning("Failed to load plan %s for board: %s", plan_id, exc)
        else:
            if self.plans_dir.exists():
                for ppath in sorted(self.plans_dir.glob("*.plan.json")):
                    rel = ppath.relative_to(self.repo_root).as_posix()
                    try:
                        pdata, prev = self.storage.read_plan_file(rel)
                        if pdata.get("lifecycle") not in {"archived", "cancelled"}:
                            plans_to_inspect.append((pdata.get("id", ""), rel, pdata, prev))
                    except Exception as exc:
                        logger.warning("Skipping invalid plan %s: %s", ppath, exc)

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

                results = tdata.get("results", [])
                deliveries = tdata.get("deliveries", {})
                has_open_deliveries = any(
                    isinstance(d, dict) and d.get("disposition") == "pending"
                    for d in deliveries.values()
                )
                verified = (work_status == "done" or len(results) > 0) and not tdata.get("blocker")

                board_card = {
                    "task_id": tid,
                    "plan_id": pid,
                    "plan_title": plan_title,
                    "title": title,
                    "description": desc,
                    "kind": tdata.get("kind", "code"),
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
                "acceptance_criteria": [f"Adopted criteria for {title}"],
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
        )
        return {
            "success": True,
            "plan_id": plan_id,
            "adopted_count": adopted_count,
            "tasks_imported": adopted_count,
            "file_revision": save_res["file_revision"],
        }

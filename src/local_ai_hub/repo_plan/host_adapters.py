"""Host adapters, capability probes, and managed instruction injection for Superpowers & agents."""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
import hashlib
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PLANNER_BLOCK_START = "<!-- BEGIN LOCAL AI HUB PLANNER -->"
PLANNER_BLOCK_END = "<!-- END LOCAL AI HUB PLANNER -->"

MANAGED_PLANNER_INSTRUCTIONS = f"""{PLANNER_BLOCK_START}
## LOCAL AI HUB FILE-BACKED PROJECT PLANNER & AGENT WORKFLOW
- **Authoritative Plans**: All project goals, tasks, dependencies, and deliverables are stored in `.local-ai-hub/plans/<plan-id>.plan.json`.
- **Single Source of Truth**: NEVER create secondary or competing Markdown plans (e.g., `PLAN.md`, `TODO.md`, `tasks.md`) for repository work. Always use the file-backed planner via `local_ai_coord(action="plan_*")`.
- **Pre-execution Resolution**: Always resolve the repository root before starting work. Adopt or reuse an existing plan and task rather than duplicating goals.
- **Contract & Clarifications**: If project requirements or acceptance criteria change, update the specification, record a clarification on the task, and reconcile the contract revision before editing code.
- **Agent OS Checkpoint Sync**: Checkpoint progress through `local_ai_coord(action="task_checkpoint")`. Bound tasks automatically synchronize progress, phase, next action, and blockers to the plan file.
- **Checkpoint Recovery**: If a checkpoint persisted but plan sync failed, resolve the error, reread the plan revision, and call `plan_bind_task` again with the same task and session. Do not repeat the persisted task mutation.
- **Kanban & Briefings**: Board views (`board_summary`, `board_item_list`) and `session_briefing` reflect the authoritative plan files.
- **Authentic Verification**: Deliveries and tasks can only be completed when verified by authentic command receipts from native test/lint runs.
- **Interruption & Resumption**: On interruption, preserve explicit blockers and next actions in the checkpoint rather than restarting with a blank plan.
{PLANNER_BLOCK_END}"""


@dataclass(frozen=True)
class HostCapabilityReport:
    """Named capability levels for an agent host."""
    host_name: str
    file_management: bool
    instructions_integrated: bool
    workflow_interception: bool
    support_level: str  # "enforced", "advisory", "unsupported"
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def get_managed_planner_instructions() -> str:
    """Return the canonical managed instruction block for Local AI Hub planner."""
    return MANAGED_PLANNER_INSTRUCTIONS.strip()


def inject_managed_instructions(content: str, block: str | None = None) -> str:
    """Inject or update the managed planner block in existing instruction content.

    If markers exist, replaces the content between markers.
    If markers do not exist, appends the block cleanly while preserving all user instructions.
    """
    block_to_insert = (block or get_managed_planner_instructions()).strip()
    pattern = re.compile(
        rf"{re.escape(PLANNER_BLOCK_START)}.*?{re.escape(PLANNER_BLOCK_END)}",
        re.DOTALL,
    )

    if pattern.search(content):
        return pattern.sub(block_to_insert, content)

    # Append to content
    trimmed = content.rstrip()
    if trimmed:
        return f"{trimmed}\n\n{block_to_insert}\n"
    return f"{block_to_insert}\n"


def remove_managed_instructions(content: str) -> str:
    """Remove the managed planner block from instructions if present."""
    pattern = re.compile(
        rf"\n*{re.escape(PLANNER_BLOCK_START)}.*?{re.escape(PLANNER_BLOCK_END)}\n*",
        re.DOTALL,
    )
    return pattern.sub("\n", content).strip() + "\n"


def detect_host_environment() -> str:
    """Detect current running host agent environment."""
    if os.environ.get("ANTIGRAVITY_ENV"):
        return "gemini_antigravity"
    if os.environ.get("GEMINI_CLI_HOME"):
        return "gemini_cli"
    if os.environ.get("CODEX_HOME") or os.environ.get("CODEX_ENV"):
        return "codex"
    if os.environ.get("CLAUDE_ENV") or os.environ.get("CLAUDE_BASE_DIR"):
        return "claude"
    if os.environ.get("CURSOR_PROJECT_DIR") or os.environ.get("CURSOR_ENV"):
        return "cursor"
    return "generic_mcp"


def probe_host_capabilities(
    host_name: str | None = None,
    repo_root: str | Path | None = None,
) -> HostCapabilityReport:
    """Probe capability levels of an agent host for a target workspace root."""
    resolved_host = host_name or detect_host_environment()
    root = Path(repo_root or ".").resolve()

    # 1. File management probe
    file_management = False
    try:
        if root.exists() and os.access(str(root), os.R_OK | os.W_OK):
            file_management = True
    except Exception:
        file_management = False

    # 2. Instructions integrated probe
    instructions_integrated = False
    agents_paths = [
        root / "AGENTS.md",
        root / ".gemini" / "AGENTS.md",
        root / ".gemini" / "GEMINI.md",
        root / ".codex" / "AGENTS.md",
        root / ".cursorrules",
    ]
    from .host_hooks import confined_path, read_bytes
    for ap in agents_paths:
        if ap.exists():
            try:
                confined_path(root, ap)
                txt = read_bytes(ap, max_bytes=65536).decode("utf-8", errors="ignore")
                if PLANNER_BLOCK_START in txt and PLANNER_BLOCK_END in txt:
                    instructions_integrated = True
                    break
            except (OSError, ValueError):
                pass

    # Configuration and local files cannot authenticate a host's event delivery,
    # trust decision, coverage or failure behavior. Never promote them to enforced.
    workflow_interception = False
    registration = {"configured": False, "reason": "unsupported_host"}
    if resolved_host in {"codex", "gemini_cli"}:
        from .host_hooks import ManagedHostInstallation
        try:
            preview = ManagedHostInstallation(root, resolved_host).preview()
            registration = {"configured": preview["installed"],
                            "config_path": preview["config_path"],
                            "reason": "host_trust_and_event_delivery_not_verified"}
        except (OSError, ValueError) as exc:
            registration = {"configured": False, "reason": str(exc)}

    # Determine support level
    if file_management and instructions_integrated and workflow_interception:
        support_level = "enforced"
    elif file_management and instructions_integrated:
        support_level = "advisory"
    else:
        support_level = "unsupported"

    return HostCapabilityReport(
        host_name=resolved_host,
        file_management=file_management,
        instructions_integrated=instructions_integrated,
        workflow_interception=workflow_interception,
        support_level=support_level,
        details={
            "repo_root": str(root),
            "instructions_checked": [str(p) for p in agents_paths if p.exists()],
            "hook_registration": registration,
            "host_event_verification": "not_verified",
            "enforcement_gap": "No authenticated host capability observation; local configuration is advisory.",
        },
    )


class SteeringManager:
    """Bounded private inbox; records are advisory, never host verification receipts."""

    MAX_RECORDS = 256

    def __init__(self, repo_root: str | Path) -> None:
        from .host_hooks import checked_root, confined_path
        self.repo_root = checked_root(repo_root)
        self.steering_dir = self.repo_root / ".local-ai-hub" / "local" / "steering"
        confined_path(self.repo_root, self.steering_dir)
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        from .host_hooks import confined_path
        confined_path(self.repo_root, self.steering_dir)
        self.steering_dir.mkdir(parents=True, exist_ok=True)

    def capture_steering(
        self,
        session_id: str,
        message: str,
        *,
        task_id: str | None = None,
        author: str = "operator",
        event_id: str | None = None,
    ) -> dict[str, Any]:
        """Capture private local text; never copy operator text into tracked plans."""
        from .host_hooks import atomic_json, bounded_text, confined_path, read_json
        bounded_text(session_id, "session_id", 200)
        bounded_text(message, "message", 16384)
        bounded_text(author, "author", 100)
        if task_id is not None:
            bounded_text(task_id, "task_id", 200)
        if event_id is not None:
            bounded_text(event_id, "event_id", 300)
        self._ensure_dir()
        with self._locked():
            identity = json.dumps([session_id, task_id, event_id], ensure_ascii=True)
            suffix = hashlib.sha256(identity.encode()).hexdigest()[:24] if event_id else uuid.uuid4().hex[:24]
            steering_id = f"steer_{suffix}"
            file_path = confined_path(self.repo_root, self.steering_dir / f"{steering_id}.json")
            if file_path.exists():
                existing = read_json(file_path, max_bytes=32768)
                if any(existing.get(key) != value for key, value in {
                    "session_id": session_id, "task_id": task_id, "message": message,
                }.items()):
                    raise ValueError("event_id reused with different steering payload")
                return {"success": True, "steering_id": steering_id, "record": existing}
            if len(self._paths()) >= self.MAX_RECORDS:
                raise ValueError("steering capacity exceeded; reconcile and archive local records")
            record = {
                "steering_id": steering_id,
                "session_id": session_id,
                "task_id": task_id,
                "author": author,
                "message": message,
                "status": "pending",  # pending, reconciled, dismissed
                "created_at": time.time(),
            }
            atomic_json(self.repo_root, file_path, record)
            return {"success": True, "steering_id": steering_id, "record": record}

    @contextmanager
    def _locked(self):
        from .host_hooks import confined_path
        lock = confined_path(self.repo_root, self.steering_dir / ".inbox.lock")
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise ValueError("steering inbox busy; do not retry an uncertain write") from exc
        try:
            os.close(descriptor)
            yield
        finally:
            lock.unlink(missing_ok=True)

    def _paths(self) -> list[Path]:
        from .host_hooks import confined_path
        confined_path(self.repo_root, self.steering_dir)
        paths = []
        with os.scandir(self.steering_dir) as entries:
            for index, entry in enumerate(entries):
                if index >= self.MAX_RECORDS + 16:
                    raise ValueError("steering capacity exceeded")
                if entry.name.endswith(".json"):
                    paths.append(confined_path(self.repo_root, Path(entry.path)))
        return paths

    def list_pending_steering(self, task_id: str | None = None, *, session_id: str | None = None) -> list[dict[str, Any]]:
        """List un-reconciled steering items."""
        if not self.steering_dir.exists():
            return []
        items = []
        from .host_hooks import read_json
        for p in self._paths():
            try:
                data = read_json(p, max_bytes=32768)
                if data.get("status") == "pending":
                    if (task_id is None or data.get("task_id") == task_id) and (session_id is None or data.get("session_id") == session_id):
                        items.append(data)
            except (OSError, ValueError) as exc:
                raise ValueError("invalid steering record") from exc
        return sorted(items, key=lambda x: str(x.get("created_at", "")))

    def mark_reconciled(self, steering_id: str, reconciliation_summary: str = "") -> bool:
        """Mark a steering item as reconciled."""
        from .host_hooks import atomic_json, bounded_text, confined_path, read_json
        if not isinstance(steering_id, str) or not re.fullmatch(r"steer_[a-f0-9]{12,32}", steering_id):
            raise ValueError("invalid steering_id")
        bounded_text(reconciliation_summary, "reconciliation_summary", 4096, allow_empty=True)
        target_file = confined_path(self.repo_root, self.steering_dir / f"{steering_id}.json")
        if not target_file.exists():
            return False
        try:
            with self._locked():
                data = read_json(target_file, max_bytes=32768)
                data["status"] = "reconciled"
                data["reconciliation_summary"] = reconciliation_summary
                atomic_json(self.repo_root, target_file, data)
                return True
        except Exception:
            return False

    def confirm_reconciled(
        self, steering_id: str, *, task_id: str, session_id: str,
        contract_revision: int, plan_revision: str, spec_revision: str,
        summary: str = "",
    ) -> bool:
        """Persist revisions after the bridge verifies the actual spec/plan/task.

        This is an internal storage primitive, not an evidence validator. Public
        routes must derive these revisions from authenticated stores, never from
        caller-provided acknowledgement strings.
        """
        from .host_hooks import atomic_json, bounded_text, confined_path, read_json
        if not isinstance(steering_id, str) or not re.fullmatch(r"steer_[a-f0-9]{12,32}", steering_id):
            raise ValueError("invalid steering_id")
        if isinstance(contract_revision, bool) or not isinstance(contract_revision, int) or contract_revision < 1:
            raise ValueError("invalid contract_revision")
        for name, value in {"task_id": task_id, "session_id": session_id, "plan_revision": plan_revision,
                            "spec_revision": spec_revision}.items():
            bounded_text(value, name, 200)
        bounded_text(summary, "summary", 4096, allow_empty=True)
        path = confined_path(self.repo_root, self.steering_dir / f"{steering_id}.json")
        if not path.exists():
            return False
        record = read_json(path, max_bytes=32768)
        if record.get("session_id") != session_id or record.get("task_id") not in {None, task_id}:
            raise ValueError("steering task/session scope mismatch")
        record.update(status="reconciled", task_id=task_id, reconciliation_summary=summary,
                      reconciliation={"contract_revision": contract_revision,
                                      "plan_revision": plan_revision, "spec_revision": spec_revision})
        atomic_json(self.repo_root, path, record)
        return True

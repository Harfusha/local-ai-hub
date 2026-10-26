"""Host adapters, capability probes, and managed instruction injection for Superpowers & agents."""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
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
    if os.environ.get("ANTIGRAVITY_ENV") or os.environ.get("GEMINI_CLI_HOME"):
        return "gemini_antigravity"
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
        root / ".codex" / "AGENTS.md",
        root / ".cursorrules",
    ]
    for ap in agents_paths:
        if ap.exists():
            try:
                txt = ap.read_text(encoding="utf-8", errors="ignore")
                if PLANNER_BLOCK_START in txt and PLANNER_BLOCK_END in txt:
                    instructions_integrated = True
                    break
            except OSError:
                pass

    # 3. Workflow interception probe
    workflow_interception = False
    # Check for hook configurations or event streams
    hook_paths = [
        root / ".local-ai-hub" / "local" / "hooks",
        root / ".gemini" / "antigravity" / "hooks",
    ]
    for hp in hook_paths:
        if hp.exists() and any(hp.iterdir()):
            workflow_interception = True
            break

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
        },
    )


class SteeringManager:
    """Captures and manages in-flight operator clarifications, steering, and pending reconciliations."""

    def __init__(self, repo_root: str | Path) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.steering_dir = self.repo_root / ".local-ai-hub" / "local" / "steering"
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        self.steering_dir.mkdir(parents=True, exist_ok=True)

    def capture_steering(
        self,
        session_id: str,
        message: str,
        *,
        task_id: str | None = None,
        author: str = "operator",
    ) -> dict[str, Any]:
        """Capture an operator clarification or mid-execution steering safely without leaking secrets."""
        self._ensure_dir()
        steering_id = f"steer_{uuid.uuid4().hex[:12]}"
        record = {
            "steering_id": steering_id,
            "session_id": session_id,
            "task_id": task_id,
            "author": author,
            "message": message,
            "status": "pending",  # pending, reconciled, dismissed
            "created_at": os.environ.get("TEST_TIME") or str(uuid.uuid1().time),
        }
        file_path = self.steering_dir / f"{steering_id}.json"
        temp_path = self.steering_dir / f".tmp_{steering_id}_{uuid.uuid4().hex[:6]}"
        try:
            temp_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
            temp_path.replace(file_path)
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
        return {"success": True, "steering_id": steering_id, "record": record}

    def list_pending_steering(self, task_id: str | None = None) -> list[dict[str, Any]]:
        """List un-reconciled steering items."""
        if not self.steering_dir.exists():
            return []
        items = []
        for p in self.steering_dir.glob("*.json"):
            if p.name.startswith(".tmp_"):
                continue
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if data.get("status") == "pending":
                    if task_id is None or data.get("task_id") == task_id:
                        items.append(data)
            except Exception:
                continue
        return sorted(items, key=lambda x: str(x.get("created_at", "")))

    def mark_reconciled(self, steering_id: str, reconciliation_summary: str = "") -> bool:
        """Mark a steering item as reconciled."""
        target_file = self.steering_dir / f"{steering_id}.json"
        if not target_file.exists():
            return False
        try:
            data = json.loads(target_file.read_text(encoding="utf-8"))
            data["status"] = "reconciled"
            data["reconciliation_summary"] = reconciliation_summary
            target_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return True
        except Exception:
            return False

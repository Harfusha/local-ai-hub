"""Unified Git-first Agent OS state management and projection reconciliation.

Coordinates the canonical storage under `.local-ai-hub/agent-os/` with derived
local SQLite tables. Ensures clean clones without local databases can
deterministically rebuild project projections.
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from .repo_project_tasks import list_project_tasks
from .repo_project_memory import list_project_memory
from .repo_project_incidents import list_project_incidents

AGENT_OS_SUBDIRS = ("tasks", "memory", "incidents", "handoffs", "verification")


def ensure_agent_os_layout(repo_root: Path | str) -> None:
    """Ensure directory structure exists under `.local-ai-hub/agent-os/`."""
    base = Path(repo_root) / ".local-ai-hub" / "agent-os"
    for subdir in AGENT_OS_SUBDIRS:
        (base / subdir).mkdir(parents=True, exist_ok=True)


def is_agent_state_git_canonical(repo_root: Path | str) -> bool:
    """Return True if the repository is configured for canonical Git-first Agent OS."""
    base = Path(repo_root) / ".local-ai-hub" / "agent-os"
    manifest_path = Path(repo_root) / ".local-ai-hub" / "project.json"
    return base.is_dir() and manifest_path.is_file()


def rebuild_agent_state_projection(
    repo_root: Path | str,
    state_dir: Path | str,
) -> dict[str, Any]:
    """Rebuild SQLite projection tables from canonical Git-backed records.

    Allows a fresh clone without an existing database to immediately execute
    queries against canonical tasks, memory, and incidents.
    """
    root = Path(repo_root).resolve(strict=True)
    db_path = Path(state_dir).resolve() / "agent_state.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    counts = {"tasks": 0, "memory": 0, "incidents": 0}
    now = time.time()

    with closing(sqlite3.connect(str(db_path))) as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")

        # 1. Rebuild tasks projection
        tasks = list_project_tasks(root)
        for task_rec in tasks:
            payload = task_rec.get("payload", {})
            task_id = payload.get("task_id")
            if not task_id:
                continue
            contract_json = json.dumps(payload.get("contract", {}), ensure_ascii=False)
            checkpoint = dict(payload.get("checkpoint", {}))
            checkpoint["state_data"] = {
                "_agent_task_scope": {
                    "version": 2,
                    "repo_root": str(root),
                }
            }
            checkpoint_json = json.dumps(checkpoint, ensure_ascii=False)
            status = payload.get("status", "planned")

            con.execute(
                """INSERT INTO agent_tasks_projection (
                    task_id, status, contract, checkpoint, context, owner, lease_id, receipts,
                    created_at, updated_at, heartbeat_expires_at
                ) VALUES (?, ?, ?, ?, '{}', 'canonical-git', '', '[]', ?, ?, 0)
                ON CONFLICT(task_id) DO UPDATE SET
                    status=excluded.status,
                    contract=excluded.contract,
                    checkpoint=excluded.checkpoint,
                    updated_at=excluded.updated_at
                """,
                (task_id, status, contract_json, checkpoint_json, now, now),
            )
            counts["tasks"] += 1

        # 2. Rebuild memory records
        memory_records = list_project_memory(root)
        for mem_rec in memory_records:
            payload = mem_rec.get("payload", {})
            record_id = payload.get("record_id")
            if not record_id:
                continue
            value_val = payload.get("value")
            value_str = value_val if isinstance(value_val, str) else json.dumps(value_val, ensure_ascii=False)
            con.execute(
                """INSERT INTO agent_memory_records (
                    record_id, kind, scope, key, value, confidence, source,
                    sensitivity, quarantine_reason, created_at, updated_at,
                    scope_id, provenance, evidence_ids, contradicts_record_id,
                    supersedes_record_id, expires_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '{}', '[]', '', '', 0, 'active')
                ON CONFLICT(record_id) DO UPDATE SET
                    value=excluded.value,
                    confidence=excluded.confidence,
                    updated_at=excluded.updated_at
                """,
                (
                    record_id, payload.get("kind", "fact"), payload.get("scope", "project"),
                    payload.get("key", ""), value_str, payload.get("confidence", 1.0),
                    payload.get("source", "agent"), payload.get("sensitivity", "internal"),
                    payload.get("quarantine_reason", ""), now, now,
                ),
            )
            counts["memory"] += 1

        # 3. Rebuild incidents
        incidents = list_project_incidents(root)
        for inc_rec in incidents:
            payload = inc_rec.get("payload", {})
            incident_id = payload.get("incident_id")
            if not incident_id:
                continue
            con.execute(
                """INSERT INTO agent_incidents (
                    incident_id, operation_class, error_class, signature_hash, resolved,
                    redacted_message, root_cause, verified_fix, confidence,
                    affected_paths, created_at, updated_at, state_revision, attempts,
                    evidence_ids, repository_key, ignored, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, '[]', '', 0, 0)
                ON CONFLICT(incident_id) DO UPDATE SET
                    resolved=excluded.resolved,
                    verified_fix=excluded.verified_fix,
                    root_cause=excluded.root_cause,
                    updated_at=excluded.updated_at
                """,
                (
                    incident_id, payload.get("operation_class", "agent"),
                    payload.get("error_class", "RuntimeError"), payload.get("signature_hash", ""),
                    1 if payload.get("resolved") else 0,
                    payload.get("redacted_message", ""), payload.get("root_cause", ""),
                    payload.get("verified_fix", ""), payload.get("confidence", 1.0),
                    json.dumps(payload.get("affected_paths", []), ensure_ascii=False),
                    now, now,
                ),
            )
            counts["incidents"] += 1

        con.commit()

    return {
        "success": True,
        "rebuilt": counts,
        "repo_root": str(root),
        "state_dir": str(state_dir),
    }

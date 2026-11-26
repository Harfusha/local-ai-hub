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

from .agent_incidents import _incident_scope_key
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
    repository_key = _incident_scope_key("repository", str(root))
    if not repository_key:
        return {"success": False, "error": "Repository incident scope could not be derived"}
    db_path = Path(state_dir).resolve() / "agent_state.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    counts = {"tasks": 0, "memory": 0, "incidents": 0}
    now = time.time()

    with closing(sqlite3.connect(str(db_path))) as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        _ensure_projection_schema(con)
        con.execute("BEGIN IMMEDIATE")

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

            existing = con.execute(
                "SELECT checkpoint FROM agent_tasks_projection WHERE task_id=?", (task_id,)
            ).fetchone()
            if existing:
                try:
                    existing_checkpoint = json.loads(existing[0] or "{}")
                    existing_root = (
                        existing_checkpoint.get("state_data", {})
                        .get("_agent_task_scope", {}).get("repo_root")
                    )
                except (TypeError, ValueError):
                    existing_root = None
                if existing_root and existing_root != str(root):
                    con.rollback()
                    return {"success": False, "error": f"Task ID is already projected from another repository: {task_id}"}
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
            project_id = str(mem_rec.get("project_id", ""))
            provenance = json.dumps({
                "_agent_project_scope": {"repo_root": str(root), "project_id": project_id}
            })
            existing = con.execute(
                "SELECT provenance FROM agent_memory_records WHERE record_id=?", (record_id,)
            ).fetchone()
            if existing:
                try:
                    existing_root = json.loads(existing[0] or "{}").get("_agent_project_scope", {}).get("repo_root")
                except (TypeError, ValueError, AttributeError):
                    existing_root = None
                if existing_root and existing_root != str(root):
                    con.rollback()
                    return {"success": False, "error": f"Memory ID is already projected from another repository: {record_id}"}
            con.execute(
                """INSERT INTO agent_memory_records (
                    record_id, kind, scope, scope_id, key, value, status, confidence,
                    source, evidence_ids, sensitivity, contradicts_record_id,
                    supersedes_record_id, quarantine_reason, provenance, created_at,
                    updated_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(record_id) DO UPDATE SET
                    kind=excluded.kind,
                    scope=excluded.scope,
                    value=excluded.value,
                    confidence=excluded.confidence,
                    key=excluded.key,
                    source=excluded.source,
                    sensitivity=excluded.sensitivity,
                    quarantine_reason=excluded.quarantine_reason,
                    scope_id=excluded.scope_id,
                    provenance=excluded.provenance,
                    contradicts_record_id=excluded.contradicts_record_id,
                    supersedes_record_id=excluded.supersedes_record_id,
                    expires_at=excluded.expires_at,
                    updated_at=excluded.updated_at
                """,
                (
                    record_id,
                    payload.get("kind", "fact"),
                    payload.get("scope", "project"),
                    project_id,
                    payload.get("key", ""),
                    value_str,
                    "quarantined" if payload.get("quarantine_reason") else "active",
                    payload.get("confidence", 1.0),
                    payload.get("source", "agent"),
                    "[]",
                    payload.get("sensitivity", "internal"),
                    payload.get("contradicts_record_id", ""),
                    payload.get("supersedes_record_id", ""),
                    payload.get("quarantine_reason", ""),
                    provenance,
                    payload.get("created_at", now),
                    payload.get("updated_at", now),
                    payload.get("expires_at"),
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
            existing = con.execute(
                "SELECT repository_key FROM agent_incidents WHERE incident_id=?", (incident_id,)
            ).fetchone()
            if existing and existing[0] and existing[0] != repository_key:
                con.rollback()
                return {"success": False, "error": f"Incident ID is already projected from another repository: {incident_id}"}
            con.execute(
                """INSERT INTO agent_incidents (
                    incident_id, operation_class, error_class, signature_hash, resolved,
                    redacted_message, root_cause, verified_fix, confidence,
                    affected_paths, created_at, updated_at, state_revision, attempts,
                    evidence_ids, repository_key, ignored, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, '[]', ?, 0, 0)
                ON CONFLICT(incident_id) DO UPDATE SET
                    operation_class=excluded.operation_class,
                    error_class=excluded.error_class,
                    signature_hash=excluded.signature_hash,
                    redacted_message=excluded.redacted_message,
                    resolved=excluded.resolved,
                    verified_fix=excluded.verified_fix,
                    root_cause=excluded.root_cause,
                    confidence=excluded.confidence,
                    affected_paths=excluded.affected_paths,
                    repository_key=excluded.repository_key,
                    updated_at=excluded.updated_at
                """,
                (
                    incident_id, payload.get("operation_class", "agent"),
                    payload.get("error_class", "RuntimeError"), payload.get("signature_hash", ""),
                    1 if payload.get("resolved") else 0,
                    payload.get("redacted_message", ""), payload.get("root_cause", ""),
                    payload.get("verified_fix", ""), payload.get("confidence", 1.0),
                    json.dumps(payload.get("affected_paths", []), ensure_ascii=False),
                    payload.get("created_at", now),
                    payload.get("updated_at", now),
                    repository_key,
                ),
            )
            counts["incidents"] += 1

        # Reconcile deletions without touching rows projected from other repos.
        task_ids = {str(row.get("payload", {}).get("task_id")) for row in tasks}
        for task_id, checkpoint_raw in con.execute(
            "SELECT task_id, checkpoint FROM agent_tasks_projection"
        ).fetchall():
            try:
                scope_root = json.loads(checkpoint_raw or "{}").get("state_data", {}).get(
                    "_agent_task_scope", {}
                ).get("repo_root")
            except (TypeError, ValueError, AttributeError):
                scope_root = None
            if scope_root == str(root) and task_id not in task_ids:
                con.execute("DELETE FROM agent_tasks_projection WHERE task_id=?", (task_id,))

        memory_ids = {str(row.get("payload", {}).get("record_id")) for row in memory_records}
        for record_id, provenance_raw in con.execute(
            "SELECT record_id, provenance FROM agent_memory_records"
        ).fetchall():
            try:
                scope_root = json.loads(provenance_raw or "{}").get("_agent_project_scope", {}).get("repo_root")
            except (TypeError, ValueError, AttributeError):
                scope_root = None
            if scope_root == str(root) and record_id not in memory_ids:
                con.execute("DELETE FROM agent_memory_records WHERE record_id=?", (record_id,))

        incident_ids = {str(row.get("payload", {}).get("incident_id")) for row in incidents}
        for (incident_id,) in con.execute(
            "SELECT incident_id FROM agent_incidents WHERE repository_key=?", (repository_key,)
        ).fetchall():
            if incident_id not in incident_ids:
                con.execute("DELETE FROM agent_incidents WHERE incident_id=?", (incident_id,))

        con.commit()

    return {
        "success": True,
        "rebuilt": counts,
        "repo_root": str(root),
        "state_dir": str(state_dir),
    }


def _ensure_projection_schema(con: sqlite3.Connection) -> None:
    """Create the projection tables when rebuilding a clean clone."""
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS agent_tasks_projection (
            task_id TEXT PRIMARY KEY, status TEXT NOT NULL, owner TEXT NOT NULL,
            lease_id TEXT NOT NULL, contract TEXT NOT NULL, context TEXT NOT NULL,
            checkpoint TEXT NOT NULL, receipts TEXT NOT NULL,
            heartbeat_expires_at REAL NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS agent_memory_records (
            record_id TEXT PRIMARY KEY, kind TEXT NOT NULL, scope TEXT NOT NULL,
            scope_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
            status TEXT NOT NULL, confidence REAL NOT NULL, source TEXT NOT NULL,
            evidence_ids TEXT NOT NULL, sensitivity TEXT NOT NULL, contradicts_record_id TEXT,
            supersedes_record_id TEXT, quarantine_reason TEXT, provenance TEXT NOT NULL,
            created_at REAL NOT NULL, updated_at REAL NOT NULL, expires_at REAL
        );
        CREATE TABLE IF NOT EXISTS agent_incidents (
            incident_id TEXT PRIMARY KEY, operation_class TEXT NOT NULL, error_class TEXT NOT NULL,
            signature_hash TEXT NOT NULL, redacted_message TEXT NOT NULL, state_revision TEXT NOT NULL,
            attempts INTEGER NOT NULL, evidence_ids TEXT NOT NULL, root_cause TEXT, verified_fix TEXT,
            confidence REAL NOT NULL, resolved INTEGER NOT NULL, created_at REAL NOT NULL,
            updated_at REAL NOT NULL, expires_at REAL, affected_paths TEXT NOT NULL DEFAULT '[]',
            ignored INTEGER NOT NULL DEFAULT 0, repository_key TEXT NOT NULL DEFAULT ''
        );
        """
    )

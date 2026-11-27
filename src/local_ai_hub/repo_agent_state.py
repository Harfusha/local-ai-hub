"""Unified Git-first Agent OS state management and projection reconciliation.

Coordinates the canonical storage under `.local-ai-hub/agent-os/` with derived
local SQLite tables. Ensures clean clones without local databases can
deterministically rebuild project projections.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from .agent_incidents import _incident_scope_key
from .agent_task_models import GoalContract, TaskCheckpoint
from .repo_project_tasks import list_project_tasks
from .repo_project_memory import list_project_memory
from .repo_project_incidents import list_project_incidents
from .repo_knowledge import _git_checkout_generation
from .project_identity import project_scope_id, repository_snapshot_id, worktree_scope_id
from .json_utils import dumps as json_dumps

AGENT_OS_SUBDIRS = ("tasks", "memory", "incidents", "handoffs", "verification")
_MAX_PROJECT_RECORD_FILES = 10000
_PROJECTION_GENERATION_VERSION = 3


def _projection_generation(root: Path) -> tuple[Any, ...]:
    """Fence projections on both Git checkout identity and current record files."""
    checkout = _git_checkout_generation(root)
    digest = hashlib.sha256()
    count = 0
    manifest = root / ".local-ai-hub" / "project.json"
    candidates = [manifest] if manifest.is_file() else []
    for name in AGENT_OS_SUBDIRS:
        directory = root / ".local-ai-hub" / "agent-os" / name
        if directory.is_symlink() or getattr(directory, "is_junction", lambda: False)():
            raise ValueError(f"Agent OS record directory is a link: {name}")
        if directory.is_dir():
            candidates.extend(path for path in directory.iterdir() if path.suffix == ".json")
    for path in sorted(candidates, key=lambda value: value.relative_to(root).as_posix().casefold()):
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise ValueError(f"Agent OS canonical record is a link: {path.relative_to(root).as_posix()}")
        stat = path.stat()
        count += 1
        if count > _MAX_PROJECT_RECORD_FILES:
            raise ValueError("Agent OS canonical record inventory exceeds the projection limit")
        item = (
            path.relative_to(root).as_posix(), stat.st_size,
            getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)),
            getattr(stat, "st_ctime_ns", int(stat.st_ctime * 1_000_000_000)),
        )
        digest.update(json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")
    return (
        (_PROJECTION_GENERATION_VERSION, *checkout, count, digest.hexdigest())
        if checkout is not None else
        (_PROJECTION_GENERATION_VERSION, None, count, digest.hexdigest())
    )


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
    try:
        checkout_generation = _projection_generation(root)
    except (OSError, ValueError, RuntimeError) as exc:
        return {"success": False, "error": f"Git checkout snapshot is unavailable: {exc}"}
    try:
        project_id = project_scope_id(root)
        worktree_id = worktree_scope_id(root)
    except (OSError, ValueError) as exc:
        return {"success": False, "error": f"Canonical project manifest is invalid: {exc}"}
    repository_key = _incident_scope_key("repository", project_id)
    if not repository_key:
        return {"success": False, "error": "Repository incident scope could not be derived"}
    db_path = Path(state_dir).resolve() / "agent_state.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    ownership_db_path = db_path.parent / "agent_project_projection.sqlite"

    counts = {"tasks": 0, "memory": 0, "incidents": 0}
    now = time.time()

    with closing(sqlite3.connect(str(db_path))) as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        _ensure_projection_schema(con)
        con.execute("ATTACH DATABASE ? AS project_projection_meta", (str(ownership_db_path),))
        con.execute(
            """CREATE TABLE IF NOT EXISTS project_projection_meta.records (
                repo_root TEXT NOT NULL,
                record_kind TEXT NOT NULL,
                record_id TEXT NOT NULL,
                PRIMARY KEY (repo_root, record_kind, record_id)
            )"""
        )
        con.execute(
            """CREATE TABLE IF NOT EXISTS project_projection_meta.snapshots (
                repo_root TEXT PRIMARY KEY,
                generation TEXT NOT NULL
            )"""
        )
        con.execute("BEGIN IMMEDIATE")

        # 1. Rebuild tasks projection
        tasks = list_project_tasks(root)
        for task_rec in tasks:
            payload = task_rec.get("payload", {})
            task_id = payload.get("task_id")
            if not task_id:
                continue
            contract_json = json_dumps(GoalContract.from_dict(payload.get("contract", {})).to_dict())
            checkpoint_data = dict(payload.get("checkpoint", {}))
            checkpoint_data["state_data"] = {
                "_agent_task_scope": {
                    "version": 4,
                    "project_id": project_id,
                    "worktree_id": worktree_id,
                    "repo_root": str(root),
                    "snapshot_id": repository_snapshot_id(root),
                }
            }
            checkpoint_projection = TaskCheckpoint.from_dict(checkpoint_data).to_dict()
            checkpoint_json = json_dumps(checkpoint_projection)
            branch = (
                checkout_generation[4]
                if len(checkout_generation) > 4 and isinstance(checkout_generation[4], str)
                else ""
            )
            context_json = json.dumps({
                "repository_id": project_id,
                "clone_id": "",
                "worktree_id": worktree_id,
                "branch": branch,
                "task_id": task_id,
                "session_id": "",
            }, separators=(",", ":"))
            status = payload.get("status", "planned")
            # Canonical project records accept the plan-facing spelling, while
            # the runtime TaskStore uses TaskStatus.ACTIVE.
            if status == "in_progress":
                status = "active"

            existing = con.execute(
                "SELECT checkpoint, owner, contract FROM agent_tasks_projection WHERE task_id=?", (task_id,)
            ).fetchone()
            if existing:
                try:
                    existing_checkpoint = json.loads(existing[0] or "{}")
                    existing_scope = existing_checkpoint.get("state_data", {}).get("_agent_task_scope", {})
                except (TypeError, ValueError):
                    existing_scope = {}
                existing_root = existing_scope.get("repo_root")
                existing_project_id = existing_scope.get("project_id")
                if existing_root and existing_root != str(root) and existing_project_id != project_id:
                    con.rollback()
                    return {"success": False, "error": f"Task ID is already projected from another repository: {task_id}"}
                owned = con.execute(
                    "SELECT 1 FROM project_projection_meta.records WHERE repo_root=? AND record_kind='task' AND record_id=?",
                    (str(root), task_id),
                ).fetchone()
                if not owned and existing[1] != "canonical-git":
                    con.rollback()
                    return {"success": False, "error": f"Task ID belongs to live runtime state and cannot be overwritten: {task_id}"}
                if existing_root and existing_root != str(root):
                    existing_checkpoint["state_data"]["_agent_task_scope"]["repo_root"] = str(root)
                    existing_checkpoint["state_data"]["_agent_task_scope"]["worktree_id"] = worktree_id
                    existing_checkpoint["state_data"]["_agent_task_scope"]["snapshot_id"] = repository_snapshot_id(root)
                    try:
                        same_content = (
                            existing_project_id == project_id
                            and json.loads(existing[2] or "{}") == json.loads(contract_json)
                                and existing_checkpoint == checkpoint_projection
                        )
                    except (TypeError, ValueError):
                        same_content = False
                    if not same_content:
                        con.rollback()
                        return {"success": False, "error": f"Conflicting task revision across checkouts: {task_id}"}
            con.execute(
                """INSERT INTO agent_tasks_projection (
                    task_id, status, contract, checkpoint, context, owner, lease_id, receipts,
                    created_at, updated_at, heartbeat_expires_at
                ) VALUES (?, ?, ?, ?, ?, 'canonical-git', '', '{}', ?, ?, 0)
                ON CONFLICT(task_id) DO UPDATE SET
                    status=excluded.status,
                    contract=excluded.contract,
                    checkpoint=excluded.checkpoint,
                    updated_at=excluded.updated_at
                """,
                (task_id, status, contract_json, checkpoint_json, context_json, now, now),
            )
            counts["tasks"] += 1

        # 2. Rebuild memory records
        memory_records = list_project_memory(root)
        for mem_rec in memory_records:
            payload = mem_rec.get("payload", {})
            record_id = payload.get("record_id")
            if not record_id:
                continue
            project_id = str(mem_rec.get("project_id", ""))
            canonical_scope = payload.get("scope", "project")
            scope = "global" if canonical_scope == "global" else "repository"
            scope_id = "" if scope == "global" else project_id
            runtime_kind = {
                "concept": "fact",
                "fact": "fact",
                "pattern": "convention",
                "rule": "convention",
                "decision": "decision",
                "negative_knowledge": "rejected_approach",
            }.get(payload.get("kind", "fact"))
            if runtime_kind is None:
                con.rollback()
                return {"success": False, "error": f"Unsupported canonical memory kind: {record_id}"}
            value_val = payload.get("value")
            value_str = json.dumps(value_val, ensure_ascii=False)
            runtime_sensitivity = "normal"
            provenance = json.dumps({
                "repository_id": project_id,
                "_agent_project_scope": {
                    "version": 2, "repo_root": str(root), "project_id": project_id,
                },
            })
            existing = con.execute(
                """SELECT kind, scope, scope_id, key, value, provenance
                   FROM agent_memory_records WHERE record_id=?""",
                (record_id,),
            ).fetchone()
            if existing:
                try:
                    existing_scope = json.loads(existing[5] or "{}").get("_agent_project_scope", {})
                    existing_root = existing_scope.get("repo_root")
                    existing_project_id = existing_scope.get("project_id")
                except (TypeError, ValueError, AttributeError):
                    existing_scope = {}
                    existing_root = None
                    existing_project_id = None
                if existing_root and existing_root != str(root) and existing_project_id != project_id:
                    con.rollback()
                    return {"success": False, "error": f"Memory ID is already projected from another repository: {record_id}"}
                owned = con.execute(
                    "SELECT 1 FROM project_projection_meta.records WHERE repo_root=? AND record_kind='memory' AND record_id=?",
                    (str(root), record_id),
                ).fetchone()
                matches_canonical = (
                    existing_project_id == project_id
                    and existing[0] == runtime_kind
                    and existing[1] == scope
                    and existing[2] == scope_id
                    and existing[3] == payload.get("key", "")
                    and existing[4] == value_str
                    and existing_scope.get("version") == 2
                )
                if not owned and not matches_canonical:
                    con.rollback()
                    return {"success": False, "error": f"Memory ID belongs to unmarked runtime state and cannot be overwritten: {record_id}"}
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
                    runtime_kind,
                    scope,
                    scope_id,
                    payload.get("key", ""),
                    value_str,
                    "quarantined" if payload.get("quarantine_reason") else "active",
                    payload.get("confidence", 1.0),
                    payload.get("source", "agent"),
                    "[]",
                    runtime_sensitivity,
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
                "SELECT operation_class, error_class, signature_hash, repository_key, redacted_message, resolved, verified_fix "
                "FROM agent_incidents WHERE incident_id=?",
                (incident_id,),
            ).fetchone()
            if existing:
                owned = con.execute(
                    "SELECT 1 FROM project_projection_meta.records WHERE repo_root=? AND record_kind='incident' AND record_id=?",
                    (str(root), incident_id),
                ).fetchone()
                matches_canonical = (
                    existing[0] == payload.get("operation_class", "agent")
                    and existing[1] == payload.get("error_class", "RuntimeError")
                    and existing[2] == payload.get("signature_hash", "")
                    and existing[3] == repository_key
                    and existing[4] == payload.get("redacted_message", "")
                    and existing[5] == (1 if payload.get("resolved") else 0)
                    and existing[6] == payload.get("verified_fix", "")
                )
                if not owned and not matches_canonical:
                    con.rollback()
                    return {"success": False, "error": f"Incident ID belongs to unmarked runtime state and cannot be overwritten: {incident_id}"}
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

        # Remove stale projections only after the final local checkout owner
        # releases them; another checkout of this project may still need the row.
        task_ids = {str(row.get("payload", {}).get("task_id")) for row in tasks}
        memory_ids = {str(row.get("payload", {}).get("record_id")) for row in memory_records}
        incident_ids = {str(row.get("payload", {}).get("incident_id")) for row in incidents}
        current_ids = {"task": task_ids, "memory": memory_ids, "incident": incident_ids}
        for record_kind, record_id in con.execute(
            "SELECT record_kind, record_id FROM project_projection_meta.records WHERE repo_root=?",
            (str(root),),
        ).fetchall():
            if record_id in current_ids.get(record_kind, set()):
                continue
            other_owner = con.execute(
                """SELECT 1 FROM project_projection_meta.records
                   WHERE record_kind=? AND record_id=? AND repo_root<>? LIMIT 1""",
                (record_kind, record_id, str(root)),
            ).fetchone()
            if other_owner:
                con.execute(
                    "DELETE FROM project_projection_meta.records WHERE repo_root=? AND record_kind=? AND record_id=?",
                    (str(root), record_kind, record_id),
                )
                continue
            if record_kind == "task":
                con.execute(
                    "DELETE FROM agent_tasks_projection WHERE task_id=? AND owner='canonical-git'",
                    (record_id,),
                )
            elif record_kind == "memory":
                con.execute(
                    """DELETE FROM agent_memory_records
                       WHERE record_id=?
                         AND json_valid(provenance)
                         AND json_extract(provenance, '$._agent_project_scope.project_id')=?""",
                    (record_id, project_id),
                )
            elif record_kind == "incident":
                con.execute(
                    "DELETE FROM agent_incidents WHERE incident_id=? AND repository_key=?",
                    (record_id, repository_key),
                )
            con.execute(
                "DELETE FROM project_projection_meta.records WHERE repo_root=? AND record_kind=? AND record_id=?",
                (str(root), record_kind, record_id),
            )
        for record_kind, record_ids in current_ids.items():
            for record_id in record_ids:
                con.execute(
                    "INSERT OR IGNORE INTO project_projection_meta.records (repo_root, record_kind, record_id) VALUES (?, ?, ?)",
                    (str(root), record_kind, record_id),
                )

        if _projection_generation(root) != checkout_generation:
            con.rollback()
            return {"success": False, "error": "Git checkout changed during projection rebuild"}
        con.execute(
            "INSERT OR REPLACE INTO project_projection_meta.snapshots (repo_root, generation) VALUES (?, ?)",
            (str(root), json.dumps(checkout_generation, separators=(",", ":"))),
        )

        con.commit()

    return {
        "success": True,
        "rebuilt": counts,
        "repo_root": str(root),
        "state_dir": str(state_dir),
    }


def ensure_agent_state_projection_current(
    repo_root: Path | str, state_dir: Path | str,
) -> dict[str, Any]:
    """Refresh a checkout projection when its branch or HEAD changed."""
    root = Path(repo_root).resolve(strict=True)
    try:
        generation = _projection_generation(root)
    except (OSError, ValueError, RuntimeError) as exc:
        return {"success": False, "error": f"Git checkout snapshot is unavailable: {exc}"}
    metadata_db = Path(state_dir).resolve() / "agent_project_projection.sqlite"
    try:
        with closing(sqlite3.connect(str(metadata_db), timeout=2.0)) as con:
            exists = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='snapshots'"
            ).fetchone()
            if exists:
                row = con.execute(
                    "SELECT generation FROM snapshots WHERE repo_root=?", (str(root),)
                ).fetchone()
                if row and row[0] == json.dumps(generation, separators=(",", ":")):
                    return {"success": True, "rebuilt": False, "repo_root": str(root)}
    except sqlite3.Error as exc:
        return {"success": False, "error": f"Projection snapshot lookup failed: {exc}"}
    return rebuild_agent_state_projection(root, state_dir)


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
        CREATE INDEX IF NOT EXISTS idx_agent_tasks_status
            ON agent_tasks_projection (status, heartbeat_expires_at);
        CREATE INDEX IF NOT EXISTS idx_agent_tasks_updated
            ON agent_tasks_projection (updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_agent_tasks_status_updated
            ON agent_tasks_projection (status, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_agent_memory_scope_key
            ON agent_memory_records (scope, key, status);
        CREATE INDEX IF NOT EXISTS idx_agent_memory_scope_identity
            ON agent_memory_records (scope, scope_id, status, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_agent_memory_provenance_root
            ON agent_memory_records (
                scope,
                json_extract(CASE WHEN json_valid(provenance) THEN provenance ELSE '{}' END, '$.root'),
                status, updated_at DESC
            );
        CREATE INDEX IF NOT EXISTS idx_agent_memory_provenance_repository
            ON agent_memory_records (
                scope,
                json_extract(CASE WHEN json_valid(provenance) THEN provenance ELSE '{}' END, '$.repository_id'),
                status, updated_at DESC
            );
        CREATE INDEX IF NOT EXISTS idx_agent_memory_provenance_clone_id
            ON agent_memory_records (
                scope,
                json_extract(CASE WHEN json_valid(provenance) THEN provenance ELSE '{}' END, '$.clone_id'),
                status, updated_at DESC
            );
        CREATE INDEX IF NOT EXISTS idx_agent_memory_provenance_worktree_id
            ON agent_memory_records (
                scope,
                json_extract(CASE WHEN json_valid(provenance) THEN provenance ELSE '{}' END, '$.worktree_id'),
                status, updated_at DESC
            );
        CREATE INDEX IF NOT EXISTS idx_agent_memory_provenance_branch
            ON agent_memory_records (
                scope,
                json_extract(CASE WHEN json_valid(provenance) THEN provenance ELSE '{}' END, '$.branch'),
                status, updated_at DESC
            );
        CREATE INDEX IF NOT EXISTS idx_agent_memory_updated
            ON agent_memory_records (updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_agent_memory_expires
            ON agent_memory_records (expires_at) WHERE expires_at IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_agent_incidents_fp
            ON agent_incidents (error_class, operation_class, signature_hash, state_revision);
        CREATE INDEX IF NOT EXISTS idx_agent_incidents_lookup
            ON agent_incidents (operation_class, signature_hash, state_revision, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_agent_incidents_recent
            ON agent_incidents (operation_class, signature_hash, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_agent_incidents_scope
            ON agent_incidents (repository_key, ignored, updated_at DESC);
        """
    )

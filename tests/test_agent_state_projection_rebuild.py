from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from local_ai_hub.repo_knowledge import RepoKnowledgeStore
from local_ai_hub.repo_project_tasks import build_project_task_record
from local_ai_hub.repo_project_memory import build_project_memory_record
from local_ai_hub.repo_project_incidents import build_project_incident_record
from local_ai_hub.repo_agent_state import rebuild_agent_state_projection, ensure_agent_os_layout


def test_rebuild_projection_from_canonical_git(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".local-ai-hub").mkdir()
    project = "41a9ce2a-d6b9-4ff0-ae6a-87e6c884f7bb"
    (root / ".local-ai-hub/project.json").write_text(json.dumps({
        "schema_version": 1, "project_id": project, "mode": "shared",
    }), encoding="utf-8")
    ensure_agent_os_layout(root)
    store = RepoKnowledgeStore(root)

    # 1. Create canonical task
    t_rec = build_project_task_record(store, {
        "task_id": "task-rebuild-1",
        "status": "in_progress",
        "contract": {"goal": "Test rebuild", "description": "", "acceptance_criteria": ["rebuild ok"], "non_goals": [], "constraints": [], "risk_profile": "normal"},
        "checkpoint": {"phase": "testing", "next_action": "verify", "blockers": [], "affected_paths": []},
    })
    (root / ".local-ai-hub/agent-os/tasks/task-rebuild-1.json").write_text(json.dumps(t_rec, indent=2), encoding="utf-8")

    # 2. Create canonical memory
    m_rec = build_project_memory_record(store, {
        "record_id": "mem-rebuild-1",
        "kind": "fact",
        "scope": "project",
        "key": "git_first_principle",
        "value": "Git is the canonical durable owner",
    })
    (root / ".local-ai-hub/agent-os/memory/mem-rebuild-1.json").write_text(json.dumps(m_rec, indent=2), encoding="utf-8")

    # 3. Create canonical incident
    i_rec = build_project_incident_record(store, {
        "incident_id": "inc-rebuild-1",
        "operation_class": "agent",
        "error_class": "ValueError",
        "signature_hash": "deadbeef12345678",
        "resolved": True,
        "verified_fix": "Applied input sanitization before processing",
    })
    (root / ".local-ai-hub/agent-os/incidents/inc-rebuild-1.json").write_text(json.dumps(i_rec, indent=2), encoding="utf-8")

    # Rebuild into a clean state_dir with empty SQLite tables
    state_dir = tmp_path / "server_state"
    state_dir.mkdir()
    db = state_dir / "agent_state.sqlite"
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE TABLE agent_tasks_projection (task_id TEXT PRIMARY KEY, status TEXT, contract TEXT, checkpoint TEXT, context TEXT, owner TEXT, lease_id TEXT, receipts TEXT, created_at REAL, updated_at REAL, heartbeat_expires_at REAL)")
        con.execute("CREATE TABLE agent_memory_records (record_id TEXT PRIMARY KEY, kind TEXT, scope TEXT, key TEXT, value TEXT, confidence REAL, source TEXT, sensitivity TEXT, quarantine_reason TEXT, created_at REAL, updated_at REAL, scope_id TEXT, provenance TEXT, evidence_ids TEXT, contradicts_record_id TEXT, supersedes_record_id TEXT, expires_at REAL, status TEXT)")
        con.execute("CREATE TABLE agent_incidents (incident_id TEXT PRIMARY KEY, operation_class TEXT, error_class TEXT, signature_hash TEXT, resolved INTEGER, redacted_message TEXT, root_cause TEXT, verified_fix TEXT, confidence REAL, affected_paths TEXT, created_at REAL, updated_at REAL, state_revision INTEGER, attempts INTEGER, evidence_ids TEXT, repository_key TEXT, ignored INTEGER, expires_at REAL)")
        con.commit()

    res = rebuild_agent_state_projection(root, state_dir)
    assert res["success"]
    assert res["rebuilt"]["tasks"] == 1
    assert res["rebuilt"]["memory"] == 1
    assert res["rebuilt"]["incidents"] == 1

    # Verify queryable from SQLite
    with closing(sqlite3.connect(db)) as con:
        t_row = con.execute("SELECT status, contract FROM agent_tasks_projection WHERE task_id='task-rebuild-1'").fetchone()
        assert t_row is not None
        assert t_row[0] == "in_progress"
        assert json.loads(t_row[1])["goal"] == "Test rebuild"

        m_row = con.execute("SELECT key, value FROM agent_memory_records WHERE record_id='mem-rebuild-1'").fetchone()
        assert m_row is not None
        assert m_row[0] == "git_first_principle"

        i_row = con.execute("SELECT resolved, verified_fix FROM agent_incidents WHERE incident_id='inc-rebuild-1'").fetchone()
        assert i_row is not None
        assert i_row[0] == 1
        assert i_row[1] == "Applied input sanitization before processing"

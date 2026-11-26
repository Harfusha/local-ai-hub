from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
import shutil

from local_ai_hub.repo_knowledge import RepoKnowledgeStore
from local_ai_hub.repo_project_tasks import build_project_task_record
from local_ai_hub.repo_project_memory import build_project_memory_record
from local_ai_hub.repo_project_incidents import build_project_incident_record
from local_ai_hub.repo_agent_state import rebuild_agent_state_projection, ensure_agent_os_layout


def test_e2e_git_first_multi_clone_collaboration(tmp_path: Path):
    """End-to-end scenario:
    1. Node A creates and publishes canonical task, memory, and incident under .local-ai-hub/
    2. Node A's private SQLite state contains transient leases and session data
    3. Node B clones the repository (simulated by copying repo without local server state)
    4. Node B has NO SQLite database initially
    5. Node B executes projection rebuild
    6. Node B gets full project intelligence without any of Node A's private leases or tokens
    """
    # Node A setup
    repo_a = tmp_path / "repo_a"
    repo_a.mkdir()
    (repo_a / ".local-ai-hub").mkdir()
    project = "41a9ce2a-d6b9-4ff0-ae6a-87e6c884f7bb"
    (repo_a / ".local-ai-hub/project.json").write_text(json.dumps({
        "schema_version": 1, "project_id": project, "mode": "shared",
    }), encoding="utf-8")
    ensure_agent_os_layout(repo_a)
    store_a = RepoKnowledgeStore(repo_a)

    # Node A publishes canonical records
    t = build_project_task_record(store_a, {
        "task_id": "task-collab-v4",
        "status": "in_progress",
        "contract": {"goal": "Distributed Agent OS", "description": "", "acceptance_criteria": ["multi-node ok"], "non_goals": [], "constraints": [], "risk_profile": "critical"},
        "checkpoint": {"phase": "testing", "next_action": "e2e verify", "blockers": [], "affected_paths": []},
    })
    (repo_a / ".local-ai-hub/agent-os/tasks/task-collab-v4.json").write_text(json.dumps(t, indent=2), encoding="utf-8")

    m = build_project_memory_record(store_a, {
        "record_id": "mem-shared-rule",
        "kind": "rule",
        "scope": "project",
        "key": "git_first_policy",
        "value": "Shared state must be in git, runtime leases stay in sqlite",
    })
    (repo_a / ".local-ai-hub/agent-os/memory/mem-shared-rule.json").write_text(json.dumps(m, indent=2), encoding="utf-8")

    i = build_project_incident_record(store_a, {
        "incident_id": "inc-shared-fix",
        "operation_class": "agent",
        "error_class": "PermissionError",
        "signature_hash": "abcdef0123456789",
        "resolved": True,
        "verified_fix": "Set umask and enforce safe directory permissions",
    })
    (repo_a / ".local-ai-hub/agent-os/incidents/inc-shared-fix.json").write_text(json.dumps(i, indent=2), encoding="utf-8")

    # Node A local SQLite has private lease
    state_a = tmp_path / "state_a"
    state_a.mkdir()
    db_a = state_a / "agent_state.sqlite"
    with closing(sqlite3.connect(db_a)) as con:
        con.execute("CREATE TABLE leases (lease_id TEXT, owner TEXT, root TEXT)")
        con.execute("INSERT INTO leases VALUES ('lease-private-node-a', 'worker-a', ?)", (str(repo_a),))
        con.commit()

    # Node B clones repo_a (only Git-tracked files)
    repo_b = tmp_path / "repo_b"
    shutil.copytree(repo_a, repo_b)

    # Node B has fresh, empty server state
    state_b = tmp_path / "state_b"
    state_b.mkdir()
    db_b = state_b / "agent_state.sqlite"
    with closing(sqlite3.connect(db_b)) as con:
        con.execute("CREATE TABLE agent_tasks_projection (task_id TEXT PRIMARY KEY, status TEXT, contract TEXT, checkpoint TEXT, context TEXT, owner TEXT, lease_id TEXT, receipts TEXT, created_at REAL, updated_at REAL, heartbeat_expires_at REAL)")
        con.execute("CREATE TABLE agent_memory_records (record_id TEXT PRIMARY KEY, kind TEXT, scope TEXT, key TEXT, value TEXT, confidence REAL, source TEXT, sensitivity TEXT, quarantine_reason TEXT, created_at REAL, updated_at REAL, scope_id TEXT, provenance TEXT, evidence_ids TEXT, contradicts_record_id TEXT, supersedes_record_id TEXT, expires_at REAL, status TEXT)")
        con.execute("CREATE TABLE agent_incidents (incident_id TEXT PRIMARY KEY, operation_class TEXT, error_class TEXT, signature_hash TEXT, resolved INTEGER, redacted_message TEXT, root_cause TEXT, verified_fix TEXT, confidence REAL, affected_paths TEXT, created_at REAL, updated_at REAL, state_revision INTEGER, attempts INTEGER, evidence_ids TEXT, repository_key TEXT, ignored INTEGER, expires_at REAL)")
        con.execute("CREATE TABLE leases (lease_id TEXT, owner TEXT, root TEXT)")
        con.commit()

    # Node B runs rebuild from Git
    rebuild_res = rebuild_agent_state_projection(repo_b, state_b)
    assert rebuild_res["success"]
    assert rebuild_res["rebuilt"]["tasks"] == 1
    assert rebuild_res["rebuilt"]["memory"] == 1
    assert rebuild_res["rebuilt"]["incidents"] == 1

    # Verify Node B state
    with closing(sqlite3.connect(db_b)) as con:
        # Task is present
        task_row = con.execute("SELECT status FROM agent_tasks_projection WHERE task_id='task-collab-v4'").fetchone()
        assert task_row[0] == "active"

        # Memory is present
        mem_row = con.execute("SELECT value FROM agent_memory_records WHERE record_id='mem-shared-rule'").fetchone()
        assert "Shared state must be in git" in mem_row[0]

        # Incident is present
        inc_row = con.execute("SELECT verified_fix FROM agent_incidents WHERE incident_id='inc-shared-fix'").fetchone()
        assert inc_row[0] == "Set umask and enforce safe directory permissions"

        # Leases from Node A are ABSENT
        leases = con.execute("SELECT COUNT(*) FROM leases").fetchone()[0]
        assert leases == 0

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
import pytest

from local_ai_hub.repo_knowledge import RepoKnowledgeStore
from local_ai_hub.agent_state_migration import (
    preview_legacy_canonical_task_batch,
    preview_legacy_memory_batch,
    preview_legacy_incident_batch,
    publish_legacy_record,
)
from local_ai_hub.repo_plan.schema_validation import RepoPlanValidationError


def _setup_migration_env(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".local-ai-hub").mkdir()
    project = "41a9ce2a-d6b9-4ff0-ae6a-87e6c884f7bb"
    (root / ".local-ai-hub/project.json").write_text(json.dumps({
        "schema_version": 1, "project_id": project, "mode": "shared",
    }), encoding="utf-8")
    store = RepoKnowledgeStore(root)

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    db = state_dir / "agent_state.sqlite"
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE TABLE agent_tasks_projection (task_id TEXT PRIMARY KEY, status TEXT, contract TEXT, checkpoint TEXT, context TEXT, owner TEXT, lease_id TEXT, receipts TEXT, created_at REAL, updated_at REAL, heartbeat_expires_at REAL)")
        con.execute("CREATE TABLE agent_memory_records (record_id TEXT PRIMARY KEY, kind TEXT, scope TEXT, key TEXT, value TEXT, confidence REAL, source TEXT, sensitivity TEXT, quarantine_reason TEXT, created_at REAL, updated_at REAL, scope_id TEXT, provenance TEXT, evidence_ids TEXT, contradicts_record_id TEXT, supersedes_record_id TEXT, expires_at REAL, status TEXT)")
        con.execute("CREATE TABLE agent_incidents (incident_id TEXT PRIMARY KEY, operation_class TEXT, error_class TEXT, signature_hash TEXT, resolved INTEGER, redacted_message TEXT, root_cause TEXT, verified_fix TEXT, confidence REAL, affected_paths TEXT, created_at REAL, updated_at REAL, state_revision INTEGER, attempts INTEGER, evidence_ids TEXT, repository_key TEXT, ignored INTEGER, expires_at REAL)")

        # Seed task with v2 scope
        chk = json.dumps({"phase": "done", "next_action": "", "blockers": [], "affected_paths": [], "state_data": {"_agent_task_scope": {"version": 2, "repo_root": str(root)}}})
        contract = json.dumps({"goal": "Migrate task", "description": "", "acceptance_criteria": ["done"], "non_goals": [], "constraints": [], "risk_profile": "normal"})
        con.execute("INSERT INTO agent_tasks_projection VALUES ('task-mig-1', 'completed', ?, ?, '{}', 'local-user', '', '[]', 100, 200, 0)", (contract, chk))

        # Seed memory
        con.execute("INSERT INTO agent_memory_records VALUES ('mem-mig-1', 'fact', 'project', 'deploy_target', '\"cloud-run\"', 1.0, 'ci', 'internal', '', 100, 200, '', '{}', '[]', '', '', 0, 'active')")

        # Seed incident
        con.execute("INSERT INTO agent_incidents VALUES ('inc-mig-1', 'command', 'TimeoutError', 'cafebabecafebabe', 1, 'build timeout', 'slow network', 'cached docker layers in runner', 1.0, '[\"Dockerfile\"]', 100, 200, 1, 0, '[]', '', 0, 0)")
        con.commit()

    return root, store, state_dir


def test_preview_and_publish_canonical_task(tmp_path: Path):
    root, store, state_dir = _setup_migration_env(tmp_path)
    preview = preview_legacy_canonical_task_batch(state_dir, store, limit=8)
    assert preview["success"]
    assert len(preview["batch"]["records"]) == 1
    assert preview["batch"]["records"][0]["record"]["id"] == "task-mig-1"

    pub = publish_legacy_record(
        state_dir, store, kind="task", record_id="task-mig-1",
        expected_snapshot=preview["snapshot"], operation_id="publish-task-1",
        authorize_write=lambda: True,
    )
    assert pub["success"]
    assert (root / ".local-ai-hub/agent-os/tasks/task-mig-1.json").is_file()


def test_preview_and_publish_canonical_memory(tmp_path: Path):
    root, store, state_dir = _setup_migration_env(tmp_path)
    preview = preview_legacy_memory_batch(state_dir, store, limit=8)
    assert preview["success"]
    assert len(preview["batch"]["records"]) == 1
    assert preview["batch"]["records"][0]["record"]["id"] == "mem-mig-1"

    pub = publish_legacy_record(
        state_dir, store, kind="memory", record_id="mem-mig-1",
        expected_snapshot=preview["snapshot"], operation_id="publish-mem-1",
        authorize_write=lambda: True,
    )
    assert pub["success"]
    assert (root / ".local-ai-hub/agent-os/memory/mem-mig-1.json").is_file()


def test_preview_and_publish_canonical_incident(tmp_path: Path):
    root, store, state_dir = _setup_migration_env(tmp_path)
    preview = preview_legacy_incident_batch(state_dir, store, limit=8)
    assert preview["success"]
    assert len(preview["batch"]["records"]) == 1
    assert preview["batch"]["records"][0]["record"]["id"] == "inc-mig-1"

    pub = publish_legacy_record(
        state_dir, store, kind="incident", record_id="inc-mig-1",
        expected_snapshot=preview["snapshot"], operation_id="publish-inc-1",
        authorize_write=lambda: True,
    )
    assert pub["success"]
    assert (root / ".local-ai-hub/agent-os/incidents/inc-mig-1.json").is_file()

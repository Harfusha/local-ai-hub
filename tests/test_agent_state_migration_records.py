from __future__ import annotations

import json
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path
import pytest

from local_ai_hub.repo_knowledge import RepoKnowledgeStore
from local_ai_hub.agent_state_migration import (
    migrate_project_state_on_update,
)
from local_ai_hub.agent_incidents import _incident_scope_key
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
        provenance = json.dumps({"root": str(root)})
        con.execute("INSERT INTO agent_memory_records VALUES ('mem-mig-1', 'fact', 'project', 'deploy_target', '\"cloud-run\"', 1.0, 'ci', 'internal', '', 100, 200, '', ?, '[]', '', '', 0, 'active')", (provenance,))
        con.execute("INSERT INTO agent_memory_records VALUES ('mem-other-project', 'fact', 'project', 'private', '\"other-project-secret\"', 1.0, 'ci', 'internal', '', 100, 200, '', ?, '[]', '', '', 0, 'active')", (json.dumps({"root": str(root.parent / "other")}),))

        # Seed incident
        repository_key = _incident_scope_key("repository", str(root))
        con.execute("INSERT INTO agent_incidents VALUES ('inc-mig-1', 'command', 'TimeoutError', 'cafebabecafebabe', 1, 'build timeout', 'slow network', 'cached docker layers in runner', 1.0, '[\"Dockerfile\"]', 100, 200, 1, 0, '[]', ?, 0, 0)", (repository_key,))
        other_repository_key = _incident_scope_key("repository", str(root.parent / "other"))
        con.execute("INSERT INTO agent_incidents VALUES ('inc-other-project', 'command', 'ValueError', 'deadbeefdeadbeef', 1, 'other project', 'private', 'other-project-secret', 1.0, '[]', 100, 200, 1, 0, '[]', ?, 0, 0)", (other_repository_key,))
        con.commit()

    return root, store, state_dir


def test_update_migration_publishes_portable_records_once(tmp_path: Path):
    root, store, state_dir = _setup_migration_env(tmp_path)
    first = migrate_project_state_on_update(state_dir, root)
    assert first["status"] == "migrated"
    assert first["records"] == {"task": 1, "memory": 1, "incident": 1}
    assert (root / ".local-ai-hub/agent-os/tasks/task-mig-1.json").is_file()
    assert (root / ".local-ai-hub/agent-os/memory/mem-mig-1.json").is_file()
    assert (root / ".local-ai-hub/agent-os/incidents/inc-mig-1.json").is_file()
    assert not (root / ".local-ai-hub/agent-os/memory/mem-other-project.json").exists()
    assert not (root / ".local-ai-hub/agent-os/incidents/inc-other-project.json").exists()
    again = migrate_project_state_on_update(state_dir, root)
    assert again["status"] == "already_migrated"
    assert again["records"] == 0


def test_update_migration_resumes_after_a_late_blocker(tmp_path: Path):
    root, _, state_dir = _setup_migration_env(tmp_path)
    db = state_dir / "agent_state.sqlite"
    with closing(sqlite3.connect(db)) as con:
        con.execute("UPDATE agent_incidents SET verified_fix='password=private' WHERE incident_id='inc-mig-1'")
        con.commit()

    with pytest.raises(RepoPlanValidationError):
        migrate_project_state_on_update(state_dir, root)
    assert (root / ".local-ai-hub/agent-os/tasks/task-mig-1.json").is_file()
    assert (root / ".local-ai-hub/agent-os/memory/mem-mig-1.json").is_file()
    assert not (state_dir / "project_state_migration_v1.json").exists()

    with closing(sqlite3.connect(db)) as con:
        con.execute("UPDATE agent_incidents SET verified_fix='cached docker layers in runner' WHERE incident_id='inc-mig-1'")
        con.commit()
    resumed = migrate_project_state_on_update(state_dir, root)
    assert resumed["status"] == "migrated"
    assert resumed["records"] == {"task": 0, "memory": 0, "incident": 1}


def test_update_migration_recognizes_registered_linked_worktree_roots(tmp_path: Path):
    root, _, state_dir = _setup_migration_env(tmp_path)
    linked = tmp_path / "linked"
    (root / ".gitignore").write_text(".local-ai-hub/local/\n", encoding="utf-8")
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(root), "add", ".gitignore", ".local-ai-hub/project.json"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-m", "project identity"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "worktree", "add", "-b", "linked-test", str(linked)], check=True, capture_output=True)

    db = state_dir / "agent_state.sqlite"
    with closing(sqlite3.connect(db)) as con:
        task_row = con.execute("SELECT checkpoint FROM agent_tasks_projection WHERE task_id='task-mig-1'").fetchone()
        checkpoint = json.loads(task_row[0])
        checkpoint["state_data"]["_agent_task_scope"]["repo_root"] = str(linked)
        con.execute("UPDATE agent_tasks_projection SET checkpoint=? WHERE task_id='task-mig-1'", (json.dumps(checkpoint),))
        con.execute("UPDATE agent_memory_records SET provenance=? WHERE record_id='mem-mig-1'", (json.dumps({"root": str(linked)}),))
        con.execute("UPDATE agent_incidents SET repository_key=? WHERE incident_id='inc-mig-1'", (_incident_scope_key("repository", str(linked)),))
        con.commit()

    result = migrate_project_state_on_update(state_dir, root)
    assert result["records"] == {"task": 1, "memory": 1, "incident": 1}


def test_update_migration_recognizes_existing_relocated_checkout_by_project_id(tmp_path: Path):
    root, _, state_dir = _setup_migration_env(tmp_path)
    old_checkout = tmp_path / "old-checkout"
    (old_checkout / ".local-ai-hub").mkdir(parents=True)
    (old_checkout / ".local-ai-hub/project.json").write_bytes((root / ".local-ai-hub/project.json").read_bytes())
    db = state_dir / "agent_state.sqlite"
    with closing(sqlite3.connect(db)) as con:
        task_row = con.execute("SELECT checkpoint FROM agent_tasks_projection WHERE task_id='task-mig-1'").fetchone()
        checkpoint = json.loads(task_row[0])
        checkpoint["state_data"]["_agent_task_scope"]["repo_root"] = str(old_checkout)
        con.execute("UPDATE agent_tasks_projection SET checkpoint=? WHERE task_id='task-mig-1'", (json.dumps(checkpoint),))
        con.execute("UPDATE agent_memory_records SET provenance=? WHERE record_id='mem-mig-1'", (json.dumps({"root": str(old_checkout)}),))
        con.execute("UPDATE agent_incidents SET repository_key=? WHERE incident_id='inc-mig-1'", (_incident_scope_key("repository", str(old_checkout)),))
        con.commit()

    result = migrate_project_state_on_update(state_dir, root)
    assert result["records"] == {"task": 1, "memory": 1, "incident": 1}


def test_release_update_invokes_project_cutover_once(tmp_path: Path, monkeypatch):
    root, _, state_dir = _setup_migration_env(tmp_path)
    (root / "pyproject.toml").write_text('[project]\nversion = "8.2.1"\n', encoding="utf-8")
    from tools import setup as setup_module

    monkeypatch.setattr(setup_module, "SOURCE_ROOT", root)
    monkeypatch.setattr(setup_module, "run_state_migrations", lambda *args, **kwargs: {"status": "current", "backups": []})
    monkeypatch.setattr(setup_module, "apply_embedding_reset", lambda *args, **kwargs: {"status": "not_required"})
    monkeypatch.setattr(setup_module, "discard_stale_migration_artifacts", lambda *args, **kwargs: [])

    result = setup_module.migrate_release_state(state_dir)
    assert result["project_state_migration"]["status"] == "migrated"
    assert (root / ".local-ai-hub/agent-os/tasks/task-mig-1.json").is_file()
    assert (state_dir / "project_state_migration_v1.json").is_file()

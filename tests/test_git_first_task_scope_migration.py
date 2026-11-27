from __future__ import annotations

import json
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path
import pytest

from local_ai_hub.state_lifecycle import read_state_version, write_state_version
from local_ai_hub.project_identity import repository_snapshot_id, worktree_scope_id
from tools.state_migrations import StateMigrationError, run_state_migrations


def test_update_migrates_path_scoped_runtime_task_once(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    write_state_version(state, version=11)
    repo = tmp_path / "old-checkout"
    local = repo / ".local-ai-hub"
    local.mkdir(parents=True)
    project_id = "41a9ce2a-d6b9-4ff0-ae6a-87e6c884f7bb"
    (local / "project.json").write_text(json.dumps({
        "schema_version": 1, "project_id": project_id, "mode": "shared",
    }), encoding="utf-8")
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", ".local-ai-hub/project.json"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "project identity"], check=True, capture_output=True)
    db = state / "agent_state.sqlite"
    checkpoint = {"phase": "working", "blockers": [], "state_data": {"_agent_task_scope": {
        "version": 2, "repo_root": str(repo),
    }}}
    with closing(sqlite3.connect(db)) as con:
        con.execute("BEGIN")
        con.execute("CREATE TABLE agent_tasks_projection (task_id TEXT PRIMARY KEY, status TEXT NOT NULL, checkpoint TEXT NOT NULL, lease_id TEXT NOT NULL DEFAULT '', heartbeat_expires_at REAL NOT NULL DEFAULT 0, updated_at REAL NOT NULL DEFAULT 0)")
        con.execute("INSERT INTO agent_tasks_projection VALUES (?, 'active', ?, 'old-lease', 9999999999, 1)", (
            "legacy-task", json.dumps(checkpoint),
        ))
        con.commit()

    first = run_state_migrations(state, create_backup=False)
    second = run_state_migrations(state, create_backup=False)

    assert first["version"] == 13
    assert second["status"] == "current"
    assert read_state_version(state) == 13
    with closing(sqlite3.connect(db)) as con:
        status, lease_id, heartbeat, raw = con.execute(
            "SELECT status,lease_id,heartbeat_expires_at,checkpoint FROM agent_tasks_projection WHERE task_id='legacy-task'"
        ).fetchone()
    checkpoint = json.loads(raw)
    migrated = checkpoint["state_data"]["_agent_task_scope"]
    assert status == "blocked"
    assert not lease_id and heartbeat == 0
    assert migrated == {
        "version": 4,
        "project_id": project_id,
        "worktree_id": worktree_scope_id(repo),
        "repo_root": str(repo.resolve()),
        "snapshot_id": repository_snapshot_id(repo),
    }
    assert "re-review" in checkpoint["blockers"][-1]


def test_scope_cutover_failure_keeps_state_and_verified_backup(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    write_state_version(state, version=12)
    db = state / "agent_state.sqlite"
    checkpoint = {"state_data": {"_agent_task_scope": {"version": 99, "repo_root": "unknown"}}}
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE TABLE agent_tasks_projection (task_id TEXT PRIMARY KEY, status TEXT NOT NULL, checkpoint TEXT NOT NULL, lease_id TEXT NOT NULL DEFAULT '', heartbeat_expires_at REAL NOT NULL DEFAULT 0, updated_at REAL NOT NULL DEFAULT 0)")
        con.execute("INSERT INTO agent_tasks_projection VALUES ('unsupported','active',?,'lease',9999999999,1)", (json.dumps(checkpoint),))
        con.commit()
    original = db.read_bytes()

    with pytest.raises(StateMigrationError) as error:
        run_state_migrations(state)

    assert error.value.backup_path.is_dir()
    assert read_state_version(state) == 12
    assert db.read_bytes() == original
    with closing(sqlite3.connect(error.value.backup_path / "agent_state.sqlite")) as con:
        assert json.loads(con.execute("SELECT checkpoint FROM agent_tasks_projection").fetchone()[0]) == checkpoint

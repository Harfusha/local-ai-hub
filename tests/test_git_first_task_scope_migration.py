from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from local_ai_hub.state_lifecycle import read_state_version, write_state_version
from local_ai_hub.project_identity import worktree_scope_id
from tools.state_migrations import run_state_migrations


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
    db = state / "agent_state.sqlite"
    checkpoint = {"state_data": {"_agent_task_scope": {
        "version": 2, "repo_root": str(repo),
    }}}
    with closing(sqlite3.connect(db)) as con:
        con.execute("BEGIN")
        con.execute("CREATE TABLE agent_tasks_projection (task_id TEXT PRIMARY KEY, checkpoint TEXT NOT NULL)")
        con.execute("INSERT INTO agent_tasks_projection VALUES (?, ?)", (
            "legacy-task", json.dumps(checkpoint),
        ))
        con.commit()

    first = run_state_migrations(state, create_backup=False)
    second = run_state_migrations(state, create_backup=False)

    assert first["version"] == 12
    assert second["status"] == "current"
    assert read_state_version(state) == 12
    with closing(sqlite3.connect(db)) as con:
        migrated = json.loads(con.execute(
            "SELECT checkpoint FROM agent_tasks_projection WHERE task_id='legacy-task'"
        ).fetchone()[0])["state_data"]["_agent_task_scope"]
    assert migrated == {
        "version": 3,
        "project_id": project_id,
        "worktree_id": worktree_scope_id(repo),
        "repo_root": str(repo.resolve()),
    }

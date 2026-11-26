from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

from local_ai_hub.repo_knowledge import RepoKnowledgeStore
from local_ai_hub.repo_project_tasks import build_project_task_record
from local_ai_hub.repo_project_memory import build_project_memory_record
from local_ai_hub.repo_project_incidents import build_project_incident_record
from local_ai_hub.repo_agent_state import rebuild_agent_state_projection, ensure_agent_os_layout
from local_ai_hub.agent_incidents import _incident_scope_key


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

    # A clean clone has no SQLite database or tables.
    state_dir = tmp_path / "server_state"
    db = state_dir / "agent_state.sqlite"

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
        assert con.execute(
            "SELECT repository_key FROM agent_incidents WHERE incident_id='inc-rebuild-1'"
        ).fetchone()[0] == _incident_scope_key("repository", str(root))

    t_rec["payload"]["status"] = "completed"
    (root / ".local-ai-hub/agent-os/tasks/task-rebuild-1.json").write_text(
        json.dumps(t_rec, indent=2), encoding="utf-8"
    )
    updated = rebuild_agent_state_projection(root, state_dir)
    assert updated["success"] and updated["rebuilt"]["tasks"] == 1
    m_rec["payload"]["key"] = "git_first_principle_updated"
    m_rec["payload"]["value"] = "Git canonical data was reconciled"
    (root / ".local-ai-hub/agent-os/memory/mem-rebuild-1.json").write_text(
        json.dumps(m_rec, indent=2), encoding="utf-8"
    )
    i_rec["payload"]["error_class"] = "OSError"
    i_rec["payload"]["verified_fix"] = "Applied input sanitization before processing and retried once"
    (root / ".local-ai-hub/agent-os/incidents/inc-rebuild-1.json").write_text(
        json.dumps(i_rec, indent=2), encoding="utf-8"
    )
    updated = rebuild_agent_state_projection(root, state_dir)
    assert updated["success"]
    with closing(sqlite3.connect(db)) as con:
        assert con.execute(
            "SELECT status FROM agent_tasks_projection WHERE task_id='task-rebuild-1'"
        ).fetchone() == ("completed",)
        assert con.execute(
            "SELECT key, value, scope_id FROM agent_memory_records WHERE record_id='mem-rebuild-1'"
        ).fetchone() == (
            "git_first_principle_updated",
            "Git canonical data was reconciled",
            project,
        )
        assert con.execute(
            "SELECT error_class, verified_fix FROM agent_incidents WHERE incident_id='inc-rebuild-1'"
        ).fetchone() == (
            "OSError",
            "Applied input sanitization before processing and retried once",
        )


def test_rebuild_removes_deleted_canonical_records_without_touching_other_projects(tmp_path: Path):
    def make_project(
        name: str, project_id: str, task_id: str,
        memory_id: str | None = None, incident_id: str | None = None,
    ) -> Path:
        root = tmp_path / name
        (root / ".local-ai-hub").mkdir(parents=True)
        (root / ".local-ai-hub/project.json").write_text(
            json.dumps({"schema_version": 1, "project_id": project_id, "mode": "shared"}),
            encoding="utf-8",
        )
        ensure_agent_os_layout(root)
        store = RepoKnowledgeStore(root)
        task = build_project_task_record(store, {
            "task_id": task_id, "status": "planned",
            "contract": {"goal": name, "description": "", "acceptance_criteria": ["works"], "non_goals": [], "constraints": [], "risk_profile": "normal"},
            "checkpoint": {"phase": "planned", "next_action": "run", "blockers": [], "affected_paths": []},
        })
        (root / f".local-ai-hub/agent-os/tasks/{task_id}.json").write_text(json.dumps(task), encoding="utf-8")
        memory_id = memory_id or f"mem-{name}"
        memory = build_project_memory_record(store, {
            "record_id": memory_id, "kind": "fact", "scope": "project", "key": "refund_rule", "value": name,
        })
        (root / f".local-ai-hub/agent-os/memory/{memory_id}.json").write_text(json.dumps(memory), encoding="utf-8")
        incident_id = incident_id or f"inc-{name}"
        incident = build_project_incident_record(store, {
            "incident_id": incident_id, "operation_class": "agent", "error_class": "TimeoutError",
            "signature_hash": "0123456789abcdef", "resolved": False,
        })
        (root / f".local-ai-hub/agent-os/incidents/{incident_id}.json").write_text(json.dumps(incident), encoding="utf-8")
        return root

    project_a = make_project("shop-a", "41a9ce2a-d6b9-4ff0-ae6a-87e6c884f7bb", "task-shop-a")
    project_b = make_project("shop-b", "62a9ce2a-d6b9-4ff0-ae6a-87e6c884f7bb", "task-shop-b")
    project_c = make_project("shop-c", "92a9ce2a-d6b9-4ff0-ae6a-87e6c884f7bb", "task-shop-a")
    project_d = make_project(
        "shop-d", "82a9ce2a-d6b9-4ff0-ae6a-87e6c884f7bb", "task-shop-d", memory_id="mem-shop-a"
    )
    project_e = make_project(
        "shop-e", "72a9ce2a-d6b9-4ff0-ae6a-87e6c884f7bb", "task-shop-e", incident_id="inc-shop-a"
    )
    state_dir = tmp_path / "server_state"

    assert rebuild_agent_state_projection(project_a, state_dir)["success"]
    assert rebuild_agent_state_projection(project_b, state_dir)["success"]
    collision = rebuild_agent_state_projection(project_c, state_dir)
    assert collision["success"] is False
    assert "another repository" in collision["error"]
    assert rebuild_agent_state_projection(project_d, state_dir)["success"] is False
    assert rebuild_agent_state_projection(project_e, state_dir)["success"] is False

    with closing(sqlite3.connect(state_dir / "agent_state.sqlite")) as con:
        assert con.execute(
            "SELECT contract FROM agent_tasks_projection WHERE task_id='task-shop-a'"
        ).fetchone()[0].find("shop-a") >= 0

    for path in (project_a / ".local-ai-hub/agent-os").rglob("*.json"):
        path.unlink()
    rebuilt = rebuild_agent_state_projection(project_a, state_dir)
    assert rebuilt["success"]
    assert rebuilt["rebuilt"] == {"tasks": 0, "memory": 0, "incidents": 0}

    with closing(sqlite3.connect(state_dir / "agent_state.sqlite")) as con:
        assert con.execute("SELECT task_id FROM agent_tasks_projection ORDER BY task_id").fetchall() == [("task-shop-b",)]
        assert con.execute("SELECT record_id FROM agent_memory_records ORDER BY record_id").fetchall() == [("mem-shop-b",)]
        assert con.execute("SELECT incident_id FROM agent_incidents ORDER BY incident_id").fetchall() == [("inc-shop-b",)]


def test_projection_rebuild_cli_works_for_a_clean_project(tmp_path: Path):
    root = tmp_path / "clean-repo"
    local = root / ".local-ai-hub"
    local.mkdir(parents=True)
    (local / "project.json").write_text(
        json.dumps({"schema_version": 1, "project_id": "41a9ce2a-d6b9-4ff0-ae6a-87e6c884f7bb", "mode": "shared"}),
        encoding="utf-8",
    )
    ensure_agent_os_layout(root)
    state_dir = tmp_path / "hub-state"
    config = tmp_path / "config.toml"
    repo_config = Path(__file__).parents[1] / "config.toml"
    config_text = repo_config.read_text(encoding="utf-8")
    config_text, replacements = re.subn(
        r'(?m)^state_dir\s*=.*$',
        f'state_dir = "{state_dir.as_posix()}"',
        config_text,
        count=1,
    )
    assert replacements == 1
    config.write_text(config_text, encoding="utf-8")
    command = [
        sys.executable, str(Path(__file__).parents[1] / "tools" / "hubctl.py"),
        "knowledge", "projection-rebuild", "--root", str(root), "--config", str(config),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=20)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["rebuilt"] == {"tasks": 0, "memory": 0, "incidents": 0}

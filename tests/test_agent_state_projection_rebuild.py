from __future__ import annotations

import json
import re
import sqlite3
import shutil
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from dataclasses import replace
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub.repo_knowledge import RepoKnowledgeStore
from local_ai_hub.repo_project_tasks import build_project_task_record
from local_ai_hub.repo_project_memory import build_project_memory_record
from local_ai_hub.repo_project_incidents import build_project_incident_record
from local_ai_hub.repo_agent_state import rebuild_agent_state_projection, ensure_agent_os_layout
from local_ai_hub.agent_incidents import _incident_scope_key
from local_ai_hub.agent_events import AgentEvent, AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_task_models import ConcurrentTaskUpdateError, TaskCheckpoint
from local_ai_hub.agent_tasks import GoalContract, TaskStore


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
        "status": "active",
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
        assert con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_project_projection_records'"
        ).fetchone() is None
        t_row = con.execute("SELECT status, contract FROM agent_tasks_projection WHERE task_id='task-rebuild-1'").fetchone()
        assert t_row is not None
        assert t_row[0] == "active"
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
        ).fetchone()[0] == _incident_scope_key("repository", project)

    with closing(sqlite3.connect(state_dir / "agent_project_projection.sqlite")) as con:
        assert con.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 3
    AgentStateStore(db)._preflight_schema_read_only()

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
            json.dumps("Git canonical data was reconciled"),
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
    task_db = state_dir / "agent_state.sqlite"
    runtime_checkpoint = {
        "phase": "working",
        "next_action": "continue active runtime task",
        "blockers": [],
        "affected_paths": [],
        "state_data": {"_agent_task_scope": {"version": 2, "repo_root": str(project_a)}},
    }
    with closing(sqlite3.connect(task_db)) as con:
        con.execute(
            """INSERT INTO agent_tasks_projection (
                task_id, status, owner, lease_id, contract, context, checkpoint, receipts,
                heartbeat_expires_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "runtime-task-shop-a", "active", "codex", "lease-active",
                json.dumps({"goal": "runtime task"}), "{}", json.dumps(runtime_checkpoint),
                "[]", 0, 10, 10,
            ),
        )
        con.commit()
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
        assert con.execute("SELECT task_id FROM agent_tasks_projection ORDER BY task_id").fetchall() == [
            ("runtime-task-shop-a",), ("task-shop-b",)
        ]
        assert con.execute("SELECT record_id FROM agent_memory_records ORDER BY record_id").fetchall() == [("mem-shop-b",)]
        assert con.execute("SELECT incident_id FROM agent_incidents ORDER BY incident_id").fetchall() == [("inc-shop-b",)]


def test_projection_rebuild_fails_closed_on_unmarked_memory_and_incident_collisions(tmp_path: Path):
    def make_project(name: str, *, memory_id: str | None = None, incident_id: str | None = None) -> Path:
        root = tmp_path / name
        local = root / ".local-ai-hub"
        local.mkdir(parents=True)
        project_id = str(uuid.uuid5(uuid.NAMESPACE_URL, name))
        local.joinpath("project.json").write_text(
            json.dumps({"schema_version": 1, "project_id": project_id, "mode": "shared"}),
            encoding="utf-8",
        )
        ensure_agent_os_layout(root)
        store = RepoKnowledgeStore(root)
        if memory_id:
            memory = build_project_memory_record(store, {
                "record_id": memory_id, "kind": "fact", "scope": "project",
                "key": "business_rule", "value": "canonical value",
            })
            (root / f".local-ai-hub/agent-os/memory/{memory_id}.json").write_text(
                json.dumps(memory), encoding="utf-8"
            )
        if incident_id:
            incident = build_project_incident_record(store, {
                "incident_id": incident_id, "operation_class": "agent",
                "error_class": "TimeoutError", "signature_hash": "0123456789abcdef",
                "redacted_message": "canonical timeout", "resolved": False,
            })
            (root / f".local-ai-hub/agent-os/incidents/{incident_id}.json").write_text(
                json.dumps(incident), encoding="utf-8"
            )
        return root

    memory_root = make_project("memory-collision", memory_id="shared-memory-id")
    memory_state = tmp_path / "memory-state"
    assert rebuild_agent_state_projection(memory_root, memory_state)["success"]
    memory_project_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "memory-collision"))
    memory_provenance = json.dumps({"_agent_project_scope": {
        "repo_root": str(memory_root), "project_id": memory_project_id
    }})
    with closing(sqlite3.connect(memory_state / "agent_project_projection.sqlite")) as con:
        con.execute("DELETE FROM records WHERE record_kind='memory' AND record_id='shared-memory-id'")
        con.commit()
    with closing(sqlite3.connect(memory_state / "agent_state.sqlite")) as con:
        con.execute(
            """INSERT OR REPLACE INTO agent_memory_records (
                record_id, kind, scope, scope_id, key, value, status, confidence,
                source, evidence_ids, sensitivity, contradicts_record_id,
                supersedes_record_id, quarantine_reason, provenance, created_at,
                updated_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("shared-memory-id", "fact", "project", memory_project_id, "business_rule",
             "runtime value", "active", 1.0, "codex", "[]", "internal", "", "", "",
             memory_provenance, 1.0, 1.0, None),
        )
        con.commit()

    memory_result = rebuild_agent_state_projection(memory_root, memory_state)
    assert memory_result["success"] is False
    assert "unmarked runtime state" in memory_result["error"]
    with closing(sqlite3.connect(memory_state / "agent_state.sqlite")) as con:
        assert con.execute(
            "SELECT value FROM agent_memory_records WHERE record_id='shared-memory-id'"
        ).fetchone() == ("runtime value",)

    incident_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "shared-incident-id"))
    incident_root = make_project("incident-collision", incident_id=incident_id)
    incident_state = tmp_path / "incident-state"
    assert rebuild_agent_state_projection(incident_root, incident_state)["success"]
    incident_key = _incident_scope_key("repository", str(incident_root.resolve()))
    with closing(sqlite3.connect(incident_state / "agent_project_projection.sqlite")) as con:
        con.execute("DELETE FROM records WHERE record_kind='incident' AND record_id=?", (incident_id,))
        con.commit()
    with closing(sqlite3.connect(incident_state / "agent_state.sqlite")) as con:
        con.execute(
            """INSERT OR REPLACE INTO agent_incidents (
                incident_id, operation_class, error_class, signature_hash, resolved,
                redacted_message, root_cause, verified_fix, confidence,
                affected_paths, created_at, updated_at, state_revision, attempts,
                evidence_ids, repository_key, ignored, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (incident_id, "agent", "TimeoutError", "fedcba9876543210", 0,
             "runtime incident", "", "", 0.5, "[]", 1.0, 1.0, "1", 1, "[]",
             incident_key, 0, None),
        )
        con.commit()

    incident_result = rebuild_agent_state_projection(incident_root, incident_state)
    assert incident_result["success"] is False
    assert "unmarked runtime state" in incident_result["error"]
    with closing(sqlite3.connect(incident_state / "agent_state.sqlite")) as con:
        assert con.execute(
            "SELECT signature_hash, redacted_message FROM agent_incidents WHERE incident_id=?",
            (incident_id,),
        ).fetchone() == ("fedcba9876543210", "runtime incident")


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
    repo_config = Path(__file__).parents[1] / "src" / "local_ai_hub" / "defaults.toml"
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


def test_same_project_projection_survives_checkout_relocation(tmp_path: Path):
    project_id = "41a9ce2a-d6b9-4ff0-ae6a-87e6c884f7bb"
    original = tmp_path / "old-checkout"
    local = original / ".local-ai-hub"
    local.mkdir(parents=True)
    (local / "project.json").write_text(
        json.dumps({"schema_version": 1, "project_id": project_id, "mode": "shared"}),
        encoding="utf-8",
    )
    ensure_agent_os_layout(original)
    store = RepoKnowledgeStore(original)
    task = build_project_task_record(store, {
        "task_id": "task-relocated-project",
        "status": "planned",
        "contract": {
            "goal": "Survive checkout relocation",
            "description": "",
            "acceptance_criteria": ["same project loads at a new path"],
            "non_goals": [],
            "constraints": [],
            "risk_profile": "normal",
        },
        "checkpoint": {"phase": "planned", "next_action": "run", "blockers": [], "affected_paths": []},
    })
    (local / "agent-os/tasks/task-relocated-project.json").write_text(
        json.dumps(task), encoding="utf-8"
    )
    memory = build_project_memory_record(store, {
        "record_id": "memory-relocated-project",
        "kind": "fact",
        "scope": "project",
        "key": "checkout_rule",
        "value": "Canonical project records follow project_id across checkout paths",
    })
    (local / "agent-os/memory/memory-relocated-project.json").write_text(
        json.dumps(memory), encoding="utf-8"
    )
    incident = build_project_incident_record(store, {
        "incident_id": "incident-relocated-project",
        "operation_class": "agent",
        "error_class": "TimeoutError",
        "signature_hash": "0123456789abcdef",
        "resolved": False,
    })
    (local / "agent-os/incidents/incident-relocated-project.json").write_text(
        json.dumps(incident), encoding="utf-8"
    )
    relocated = tmp_path / "new-checkout"
    shutil.copytree(original, relocated)
    state_dir = tmp_path / "shared-hub-state"

    first = rebuild_agent_state_projection(original, state_dir)
    second = rebuild_agent_state_projection(relocated, state_dir)

    assert first["success"] is True
    assert second["success"] is True, second
    divergent = tmp_path / "divergent-checkout"
    shutil.copytree(original, divergent)
    divergent_task_path = divergent / ".local-ai-hub/agent-os/tasks/task-relocated-project.json"
    divergent_task = json.loads(divergent_task_path.read_text(encoding="utf-8"))
    divergent_task["payload"]["contract"]["goal"] = "Conflicting branch edit"
    divergent_task_path.write_text(json.dumps(divergent_task), encoding="utf-8")
    conflict = rebuild_agent_state_projection(divergent, state_dir)
    assert conflict["success"] is False
    assert "Conflicting task revision across checkouts" in conflict["error"]
    with closing(sqlite3.connect(state_dir / "agent_state.sqlite")) as con:
        row = con.execute(
            "SELECT checkpoint FROM agent_tasks_projection WHERE task_id=?",
            ("task-relocated-project",),
        ).fetchone()
    assert row is not None
    scope = json.loads(row[0])["state_data"]["_agent_task_scope"]
    assert scope["project_id"] == project_id
    assert scope["repo_root"] == str(relocated.resolve())
    with closing(sqlite3.connect(state_dir / "agent_state.sqlite")) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM agent_memory_records WHERE record_id=?",
            ("memory-relocated-project",),
        ).fetchone()[0] == 1
        assert con.execute(
            "SELECT repository_key FROM agent_incidents WHERE incident_id=?",
            ("incident-relocated-project",),
        ).fetchone()[0] == _incident_scope_key("repository", project_id)

    # A stale checkout cannot delete a record still owned by the relocated root.
    (local / "agent-os/tasks/task-relocated-project.json").unlink()
    (local / "agent-os/memory/memory-relocated-project.json").unlink()
    (local / "agent-os/incidents/incident-relocated-project.json").unlink()
    assert rebuild_agent_state_projection(original, state_dir)["success"] is True
    with closing(sqlite3.connect(state_dir / "agent_state.sqlite")) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM agent_tasks_projection WHERE task_id=?",
            ("task-relocated-project",),
        ).fetchone()[0] == 1
        assert con.execute(
            "SELECT COUNT(*) FROM agent_memory_records WHERE record_id=?",
            ("memory-relocated-project",),
        ).fetchone()[0] == 1
        assert con.execute(
            "SELECT COUNT(*) FROM agent_incidents WHERE incident_id=?",
            ("incident-relocated-project",),
        ).fetchone()[0] == 1


def test_linked_worktree_reads_same_canonical_project_task(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
    local = repo / ".local-ai-hub"
    local.mkdir()
    project_id = "41a9ce2a-d6b9-4ff0-ae6a-87e6c884f7bb"
    (local / "project.json").write_text(json.dumps({
        "schema_version": 1, "project_id": project_id, "mode": "shared",
    }), encoding="utf-8")
    ensure_agent_os_layout(repo)
    task = build_project_task_record(RepoKnowledgeStore(repo), {
        "task_id": "task-linked-worktree",
        "status": "planned",
        "contract": {
            "goal": "Use canonical project task from linked worktree",
            "description": "",
            "acceptance_criteria": ["both roots can read the project task"],
            "non_goals": [],
            "constraints": [],
            "risk_profile": "normal",
        },
        "checkpoint": {"phase": "planned", "next_action": "run", "blockers": [], "affected_paths": []},
    })
    (local / "agent-os/tasks/task-linked-worktree.json").write_text(json.dumps(task), encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", ".local-ai-hub"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "add canonical task"], check=True, capture_output=True)
    linked = tmp_path / "linked-worktree"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-b", "agent-two", str(linked), "main"],
        check=True,
        capture_output=True,
    )
    state_dir = tmp_path / "hub-state"

    assert rebuild_agent_state_projection(repo, state_dir)["success"] is True
    assert rebuild_agent_state_projection(linked, state_dir)["success"] is True
    store = TaskStore(AgentStateStore(state_dir / "agent_state.sqlite"))
    assert [item.task_id for item in store.list_tasks(repo_root=str(repo)).tasks] == ["task-linked-worktree"]
    assert [item.task_id for item in store.list_tasks(repo_root=str(linked)).tasks] == ["task-linked-worktree"]


def test_task_reads_rebuild_projection_after_branch_switch(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
    hub = repo / ".local-ai-hub"
    hub.mkdir()
    (hub / ".gitignore").write_text("local/\n", encoding="utf-8")
    project_id = "41a9ce2a-d6b9-4ff0-ae6a-87e6c884f7bb"
    (hub / "project.json").write_text(json.dumps({
        "schema_version": 1, "project_id": project_id, "mode": "shared",
    }), encoding="utf-8")
    ensure_agent_os_layout(repo)
    subprocess.run(["git", "add", ".local-ai-hub"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "project identity"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "branch", "without-task"], cwd=repo, check=True, capture_output=True)

    task = build_project_task_record(RepoKnowledgeStore(repo), {
        "task_id": "task-branch-snapshot",
        "status": "planned",
        "contract": {
            "goal": "Stay scoped to the selected branch",
            "description": "",
            "acceptance_criteria": ["stale branch tasks disappear after checkout"],
            "non_goals": [], "constraints": [], "risk_profile": "normal",
        },
        "checkpoint": {"phase": "planned", "next_action": "run", "blockers": [], "affected_paths": []},
    })
    task_path = hub / "agent-os/tasks/task-branch-snapshot.json"
    task_path.write_text(json.dumps(task) + "\n", encoding="utf-8")
    subprocess.run(["git", "add", ".local-ai-hub/agent-os/tasks"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "publish project task"], cwd=repo, check=True, capture_output=True)

    store = TaskStore(AgentStateStore(tmp_path / "state" / "agent_state.sqlite"))
    runtime_task = store.create(
        GoalContract(goal="Branch-bound runtime work", acceptance_criteria=["Work remains scoped to the selected branch"]),
        ScopeContext(task_id="task-runtime-branch-snapshot"),
        task_id="task-runtime-branch-snapshot",
        repo_root=str(repo),
    )
    assert {item.task_id for item in store.list_tasks(repo_root=str(repo)).tasks} == {
        "task-branch-snapshot", runtime_task.task_id,
    }

    subprocess.run(["git", "switch", "without-task"], cwd=repo, check=True, capture_output=True)
    assert store.get("task-branch-snapshot", repo_root=str(repo)) is None
    assert store.get(runtime_task.task_id, repo_root=str(repo)) is not None
    subprocess.run(["git", "switch", "main"], cwd=repo, check=True, capture_output=True)
    assert store.get(runtime_task.task_id, repo_root=str(repo)) is not None

    # Reuse one live TaskStore across rapid checkout churn. Branch-owned records
    # must follow the selected snapshot; the uncommitted local task stays visible.
    for _ in range(12):
        subprocess.run(["git", "switch", "without-task"], cwd=repo, check=True, capture_output=True)
        assert store.get("task-branch-snapshot", repo_root=str(repo)) is None
        assert store.get(runtime_task.task_id, repo_root=str(repo)) is not None
        subprocess.run(["git", "switch", "main"], cwd=repo, check=True, capture_output=True)
        assert store.get("task-branch-snapshot", repo_root=str(repo)) is not None
        assert store.get(runtime_task.task_id, repo_root=str(repo)) is not None


def test_shared_task_checkpoint_is_git_canonical_across_state_dirs_without_head_change(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
    control = repo / ".local-ai-hub"
    control.mkdir()
    (control / ".gitignore").write_text("local/\n", encoding="utf-8")
    project_id = "f008c4d5-3391-4dcf-9630-20ed06f86c04"
    (control / "project.json").write_text(json.dumps({
        "schema_version": 1, "project_id": project_id, "mode": "shared",
    }), encoding="utf-8")
    ensure_agent_os_layout(repo)
    subprocess.run(["git", "-C", str(repo), "add", ".local-ai-hub"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "--quiet", "-m", "project identity"], check=True)
    initial_head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True,
        text=True,
    ).stdout.strip()

    agent_a = TaskStore(AgentStateStore(tmp_path / "agent-a" / "agent_state.sqlite"))
    agent_b = TaskStore(AgentStateStore(tmp_path / "agent-b" / "agent_state.sqlite"))
    task_id = "task-shared-checkpoint"
    contract = GoalContract(
        goal="Reconcile billing retries",
        acceptance_criteria=["One charge per request key"],
    )
    created = agent_a.create(
        contract, ScopeContext(task_id=task_id), task_id=task_id, repo_root=str(repo),
    )
    assert created.task_id == task_id
    stale_agent_b = agent_b.get(task_id, repo_root=str(repo))
    assert stale_agent_b.checkpoint.next_action == ""

    updated_checkpoint = TaskCheckpoint(
        phase="verification", next_action="run duplicate-charge scenario",
        affected_paths=("src/billing.py",),
    )
    agent_a.checkpoint(task_id, updated_checkpoint)

    stale_updated = replace(
        stale_agent_b,
        checkpoint=replace(
            stale_agent_b.checkpoint, phase="planning", next_action="overwrite stale progress",
        ),
    )
    with pytest.raises(ConcurrentTaskUpdateError):
        agent_b._commit_update(
            stale_agent_b, stale_updated,
            AgentEvent.create(
                f"task:{task_id}", "task.checkpoint",
                {"phase": "planning", "next_action": "overwrite stale progress"},
                actor="agent-b",
            ),
        )

    canonical = RepoKnowledgeStore(repo).get("task", task_id, verify_sources=False)["record"]
    assert canonical["payload"]["checkpoint"]["phase"] == "verification"
    assert canonical["payload"]["checkpoint"]["next_action"] == "run duplicate-charge scenario"
    assert "repo_root" not in json.dumps(canonical)
    assert agent_b.get(task_id, repo_root=str(repo)).checkpoint.next_action == "run duplicate-charge scenario"
    assert subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True,
        text=True,
    ).stdout.strip() == initial_head
    assert subprocess.run(["git", "-C", str(repo), "diff", "--cached", "--quiet"]).returncode == 0


def test_concurrent_same_checkout_agents_cannot_overwrite_shared_checkpoint(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
    control = repo / ".local-ai-hub"
    control.mkdir()
    (control / ".gitignore").write_text("local/\n", encoding="utf-8")
    (control / "project.json").write_text(json.dumps({
        "schema_version": 1,
        "project_id": "9caf2080-c985-4a4b-9acd-b1ce9e18bc4c",
        "mode": "shared",
    }), encoding="utf-8")
    ensure_agent_os_layout(repo)
    subprocess.run(["git", "-C", str(repo), "add", ".local-ai-hub"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "--quiet", "-m", "project identity"], check=True)

    task_id = "task-concurrent-checkpoint"
    agent_a = TaskStore(AgentStateStore(tmp_path / "agent-a" / "agent_state.sqlite"))
    agent_b = TaskStore(AgentStateStore(tmp_path / "agent-b" / "agent_state.sqlite"))
    agent_a.create(
        GoalContract(goal="Coordinate offline work", acceptance_criteria=["Conflicts remain visible"]),
        ScopeContext(task_id=task_id), task_id=task_id, repo_root=str(repo),
    )
    current_a = agent_a.get(task_id, repo_root=str(repo))
    current_b = agent_b.get(task_id, repo_root=str(repo))
    assert current_a is not None and current_b is not None
    start = Barrier(2)

    def update(store: TaskStore, current, phase: str, actor: str) -> str:
        updated = replace(
            current,
            checkpoint=replace(current.checkpoint, phase=phase, next_action=f"{actor} progress"),
        )
        event = AgentEvent.create(
            f"task:{task_id}", "task.checkpoint",
            {"phase": phase, "next_action": f"{actor} progress"}, actor=actor,
        )
        start.wait(timeout=5)
        try:
            store._commit_update(current, updated, event)
            return "committed"
        except ConcurrentTaskUpdateError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            pool.submit(update, agent_a, current_a, "agent_a", "agent-a"),
            pool.submit(update, agent_b, current_b, "agent_b", "agent-b"),
        ]
        outcomes = [future.result(timeout=10) for future in results]

    assert sorted(outcomes) == ["committed", "conflict"]
    canonical = RepoKnowledgeStore(repo).get("task", task_id, verify_sources=False)["record"]
    checkpoint = canonical["payload"]["checkpoint"]
    assert checkpoint["phase"] in {"agent_a", "agent_b"}
    assert checkpoint["next_action"] in {"agent-a progress", "agent-b progress"}
    assert (checkpoint["phase"] == "agent_a") == (checkpoint["next_action"] == "agent-a progress")

from __future__ import annotations

from pathlib import Path
import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_incidents import IncidentStore, ToolOutcome


@pytest.fixture
def store(tmp_path: Path) -> IncidentStore:
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite")
    return IncidentStore(state_store)


def test_auto_mint_negative_knowledge_missing_module(store: IncidentStore, tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    outcome = ToolOutcome(
        tool_name="command",
        command="python -m myapp",
        error="ModuleNotFoundError: No module named 'fastapi'",
        exit_code=1,
        state_revision="rev-1",
        repository_root=str(root), )
    incident = store.capture(outcome)
    assert incident is not None
    assert "fastapi" in (incident.root_cause or "")
    assert incident.verified_fix is None
    assert "install" in (incident.suggested_fix or "")

    decision = store.retry_decision(incident.fingerprint, incident.state_revision, root=str(root))
    assert decision.action == "stop"
    assert decision.verified_fix is None


def test_auto_mint_negative_knowledge_sqlite_lock(store: IncidentStore, tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    outcome = ToolOutcome(
        tool_name="command",
        command="python migrate.py",
        error="sqlite3.OperationalError: database is locked",
        exit_code=1,
        state_revision="rev-2",
        repository_root=str(root), )
    incident = store.capture(outcome)
    assert incident is not None
    assert "lock" in (incident.root_cause or "").lower()
    assert incident.verified_fix is None
    assert "backoff" in (incident.suggested_fix or "").lower()
    found = store.find_negative_knowledge("backoff", root=str(root))
    assert len(found) == 1
    assert found[0]["verified_fix"] == ""
    assert "backoff" in found[0]["suggested_fix"].lower()


def test_find_negative_knowledge_by_query(store: IncidentStore, tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    store.capture(ToolOutcome(
        tool_name="command",
        command="pytest",
        error="ModuleNotFoundError: No module named 'requests'",
        exit_code=1,
        state_revision="rev-3",
        repository_root=str(root), ))
    results = store.find_negative_knowledge("requests", root=str(root))
    assert len(results) >= 1
    assert "requests" in results[0]["root_cause"]


def test_command_broker_skips_unscoped_known_pitfalls(tmp_path: Path):
    from local_ai_hub.command_broker import CommandBroker
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite")
    store = IncidentStore(state_store)

    store.capture(ToolOutcome(
        tool_name="command",
        command="pytest tests/test_broken.py",
        error="ModuleNotFoundError: No module named 'numpy'",
        exit_code=1,
        state_revision="rev-4",
    ))

    cb = CommandBroker({"server": {"state_dir": str(tmp_path)}}, repo_state=None)
    cb.set_incident_store(store)

    cb._execute = lambda *args, **kwargs: {"success": True, "exit_code": 0, "stdout": "", "stderr": ""}
    cb.classify = lambda *args, **kwargs: {"class": "validation", "cacheable": False, "allowed": True}

    res = cb.run("pytest tests/test_broken.py", str(tmp_path))
    assert 'known_pitfalls' not in res


def test_command_broker_reads_known_pitfalls_from_git_not_sqlite(tmp_path: Path):
    import json
    import subprocess
    import uuid

    from local_ai_hub.command_broker import CommandBroker
    from local_ai_hub.repo_knowledge import RepoKnowledgeStore
    from local_ai_hub.repo_project_incidents import build_project_incident_record

    root = tmp_path / "repo"
    control = root / ".local-ai-hub"
    (control / "agent-os/incidents").mkdir(parents=True)
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    (root / ".gitignore").write_text(".local-ai-hub/local/\n", encoding="utf-8")
    (control / "project.json").write_text(json.dumps({
        "schema_version": 1, "project_id": str(uuid.uuid5(uuid.NAMESPACE_URL, str(root.resolve()))),
        "mode": "shared",
    }), encoding="utf-8")
    record = build_project_incident_record(RepoKnowledgeStore(root), {
        "incident_id": "inc-known-numpy", "operation_class": "command",
        "error_class": "ModuleNotFoundError", "signature_hash": "a1b2c3d4e5f60718",
        "resolved": False, "redacted_message": "Missing numpy during tests",
        "root_cause": "Add numpy to the test requirements",
    })
    (control / "agent-os/incidents/inc-known-numpy.json").write_text(
        json.dumps(record), encoding="utf-8",
    )
    cb = CommandBroker({"server": {"state_dir": str(tmp_path)}}, repo_state=None)
    cb.set_incident_store(IncidentStore(AgentStateStore(tmp_path / "state.sqlite")))
    cb._execute = lambda *args, **kwargs: {"success": True, "exit_code": 0, "stdout": "1 passed in 0.01s\n", "stderr": ""}
    cb.classify = lambda *args, **kwargs: {"class": "validation", "cacheable": False, "allowed": True}

    result = cb.run("pytest tests/test_numpy.py", str(root))
    assert result.get("known_pitfalls") == [{
        "incident_id": "inc-known-numpy", "root_cause": "Add numpy to the test requirements",
        "verified_fix": "",
    }], result

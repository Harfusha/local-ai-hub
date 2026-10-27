from __future__ import annotations

from pathlib import Path
import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_incidents import IncidentFingerprint, IncidentRecord, IncidentStore, ToolOutcome


def test_incident_record_persists_affected_paths(tmp_path: Path):
    state_store = AgentStateStore(tmp_path / "state.sqlite3")
    store = IncidentStore(state_store)

    outcome = ToolOutcome(
        tool_name="test_runner",
        command="pytest tests/test_payment.py",
        error="IndexError in src/services/payment.py: list index out of range",
        exit_code=1,
        state_revision="rev-1",
        affected_paths=("src/services/payment.py", "tests/test_payment.py"),
        repository_root=str(tmp_path.resolve()),
    )
    inc = store.capture(outcome)
    assert inc is not None
    assert "src/services/payment.py" in inc.affected_paths
    assert "tests/test_payment.py" in inc.affected_paths

    # Reload from DB
    loaded = store.get(inc.incident_id)
    assert loaded is not None
    assert loaded.affected_paths == inc.affected_paths

    # Resolve incident with verified fix
    resolved = store.resolve(inc.incident_id, verified_fix="Check list bounds before indexing", confidence=0.95)
    assert resolved.resolved is True
    assert resolved.affected_paths == inc.affected_paths

    # Verify find_regressions detects when editing payment.py
    regs = store.find_regressions(["src/services/payment.py"], root=str(tmp_path.resolve()))
    assert len(regs) == 1
    assert regs[0]["incident_id"] == inc.incident_id
    assert regs[0]["verified_fix"] == "Check list bounds before indexing"

    # A changed repository revision must not surface an already-fixed incident
    # as a live regression warning.
    assert store.find_regressions(["src/services/payment.py"], root=str(tmp_path.resolve()), state_revision="rev-2") == []

    # Unrelated files do not trigger regression warning
    assert len(store.find_regressions(["src/auth/login.py"], root=str(tmp_path.resolve()))) == 0


def test_incident_watchdog_in_commands(tmp_path: Path):
    from local_ai_hub.commands import CommandBroker

    state_store = AgentStateStore(tmp_path / "state.sqlite3")
    inc_store = IncidentStore(state_store)

    # Seed an incident with verified fix on math_ops.py
    outcome = ToolOutcome(
        tool_name="test",
        command="python -m pytest",
        error="ZeroDivisionError in src/math_ops.py",
        exit_code=1,
        affected_paths=("src/math_ops.py",),
        repository_root=str(tmp_path.resolve()),
    )
    inc = inc_store.capture(outcome)
    assert inc is not None
    inc_store.resolve(inc.incident_id, verified_fix="Guard against division by zero", confidence=0.9)

    # Setup command broker with incident store
    cfg = {"commands": {"enabled": True}, "server": {"state_dir": str(tmp_path)}}
    broker = CommandBroker(cfg, artifacts=None, repo_state=None)
    broker.set_incident_store(inc_store)

    # Simulated command result that produces diagnostic path in math_ops.py
    sim_result = {
        "success": False,
        "exit_code": 1,
        "stdout": "src/math_ops.py:10: ZeroDivisionError: division by zero",
        "stderr": "",
        "diagnostics": [{"path": "src/math_ops.py", "line": 10, "column": 0, "message": "division by zero"}],
    }

    # Verify find_regressions matches
    regs = inc_store.find_regressions(["src/math_ops.py"], root=str(tmp_path.resolve()))
    assert len(regs) == 1
    assert "Guard against division by zero" in regs[0]["verified_fix"]


def test_regression_lookup_requires_root_and_excludes_foreign_or_unverified_incidents(tmp_path):
    root_a, root_b = str((tmp_path / "a").resolve()), str((tmp_path / "b").resolve())
    store = IncidentStore(AgentStateStore(tmp_path / "scope.sqlite3"))
    local = store.capture(ToolOutcome(
        tool_name="command", error="local failure", exit_code=1, state_revision="rev-1",
        affected_paths=("src/common.py",), repository_root=root_a,
    ))
    foreign = store.capture(ToolOutcome(
        tool_name="command", error="local failure", exit_code=1, state_revision="rev-1",
        affected_paths=("src/common.py",), repository_root=root_b,
    ))
    unverified = store.capture(ToolOutcome(
        tool_name="command", error="unresolved failure", exit_code=1, state_revision="rev-1",
        affected_paths=("src/common.py",), repository_root=root_a,
        metadata={"verified_fix": "unverified advice", "confidence": 1.0},
    ))
    assert local and foreign and unverified
    store.resolve(local.incident_id, verified_fix="local validated fix")
    store.resolve(foreign.incident_id, verified_fix="foreign private fix")
    results = store.find_regressions(["src/common.py"], root=root_a, state_revision="rev-1")
    assert [row["incident_id"] for row in results] == [local.incident_id]
    assert results[0]["verified_fix"] == "local validated fix"
    with pytest.raises(TypeError):
        store.find_regressions(["src/common.py"])
    with pytest.raises(ValueError):
        store.find_regressions(["src/common.py"], root="")


def test_review_diff_uses_only_explicit_repository_incidents(tmp_path):
    from types import SimpleNamespace
    from local_ai_hub.services import LocalAIServices

    root_a, root_b = str((tmp_path / "a").resolve()), str((tmp_path / "b").resolve())
    store = IncidentStore(AgentStateStore(tmp_path / "review-scope.sqlite3"))
    local = store.capture(ToolOutcome(
        tool_name="command", error="local failure", exit_code=1,
        affected_paths=("src/common.py",), repository_root=root_a,
    ))
    foreign = store.capture(ToolOutcome(
        tool_name="command", error="foreign failure", exit_code=1,
        affected_paths=("src/common.py",), repository_root=root_b,
    ))
    assert local and foreign
    store.resolve(local.incident_id, verified_fix="local repair")
    store.resolve(foreign.incident_id, verified_fix="foreign private repair")
    service = SimpleNamespace(
        config={}, incident_store=store,
        repo_diff=lambda *_args, **_kwargs: {"success": True, "diff": "+change", "changed_files": ["src/common.py"]},
        deterministic=SimpleNamespace(diff_facts=lambda _text: {"additions": 1, "deletions": 0, "hunks": 1}),
    )
    scoped = LocalAIServices.review_diff(service, {"root": root_a, "mode": "ast"})
    assert [row["incident_id"] for row in scoped["regressions"]] == [local.incident_id]
    unscoped = LocalAIServices.review_diff(service, {"mode": "ast"})
    assert unscoped["regressions"] == []

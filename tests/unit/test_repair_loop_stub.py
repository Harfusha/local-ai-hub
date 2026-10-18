from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.commands import CommandBroker


class _RepoState:
    def fingerprint(self, _cwd: str | Path) -> dict[str, str]:
        return {"fingerprint": "test-fingerprint"}


@pytest.mark.parametrize(
    ("has_generator", "generator_result", "expected_generator_calls"),
    [(False, None, 0), (True, None, 1), (True, {}, 1)],
)
def test_repair_loop_terminates_when_generator_has_no_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    has_generator: bool,
    generator_result: Any,
    expected_generator_calls: int,
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    broker = CommandBroker(
        {
            "features": {"diagnostic_artifacts": True},
            "commands": {"allowed": True, "allow_unknown": True, "allow_validation": True},
            "server": {"state_dir": str(state_dir)},
        },
        ArtifactStore(state_dir / "artifacts"),
        _RepoState(),
    )
    monkeypatch.setattr(broker, "_transaction_root_for_context", lambda _context: tmp_path)
    monkeypatch.setattr(broker, "_require_task_worktree", lambda *_args, **_kwargs: None)
    (tmp_path / "target.py").write_text("original", encoding="utf-8")

    generator_calls = 0

    def generator(*_args: Any) -> Any:
        nonlocal generator_calls
        generator_calls += 1
        return generator_result

    result = broker.repair_loop(
        "python -m pytest",
        tmp_path,
        max_attempts=4,
        fix_generator=generator if has_generator else None,
        initial_result={"success": False, "exit_code": 1},
        paths=["target.py"],
        _transaction_context="unit-test-transaction",
    )

    assert result["success"] is False
    assert result["repaired"] is False
    assert result["reason"] == "no_candidate_synthesizer"
    assert result["attempts"] == 0
    assert result.get("history", []) == []
    assert generator_calls == expected_generator_calls
    assert (tmp_path / "target.py").read_text(encoding="utf-8") == "original"


def test_repair_loop_uses_verified_incident_fix_when_generator_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    broker = CommandBroker(
        {
            "features": {"diagnostic_artifacts": True},
            "commands": {"allowed": True, "allow_unknown": True, "allow_validation": True},
            "server": {"state_dir": str(state_dir)},
        },
        ArtifactStore(state_dir / "artifacts"),
        _RepoState(),
    )
    broker.incident_store = object()
    monkeypatch.setattr(broker, "_transaction_root_for_context", lambda _context: tmp_path)
    monkeypatch.setattr(broker, "_require_task_worktree", lambda *_args, **_kwargs: None)
    (tmp_path / "target.py").write_text("original", encoding="utf-8")
    monkeypatch.setattr(
        broker,
        "run",
        lambda *_args, **_kwargs: {"success": True, "exit_code": 0},
    )

    result = broker.repair_loop(
        "python -m pytest",
        tmp_path,
        max_attempts=4,
        fix_generator=lambda *_args: {},
        initial_result={
            "success": False,
            "exit_code": 1,
            "remediation": {"verified_fix": {"target.py": "verified"}},
        },
        paths=["target.py"],
        _transaction_context="unit-test-transaction",
    )

    assert result["success"] is True
    assert result["repaired"] is True
    assert result["attempts"] == 1
    assert result["patches_applied"] == ["target.py"]
    assert (tmp_path / "target.py").read_text(encoding="utf-8") == "verified"

from __future__ import annotations

import os

import local_ai_hub.commands as commands_module
from local_ai_hub.commands import CommandBroker


class _DummyArtifacts:
    def put(self, *args, **kwargs):
        return "artifact-id"


class _DummyRevisionState:
    def fingerprint(self, _cwd):
        return {"fingerprint": "rev-1"}


def test_posix_command_normal_exit_confirms_cleanup(monkeypatch, tmp_path):
    broker = CommandBroker(
        {"server": {"state_dir": str(tmp_path / "state")}},
        _DummyArtifacts(),
        _DummyRevisionState(),
    )

    killpg_calls = []

    def mock_killpg(pgid, sig):
        killpg_calls.append((pgid, sig))
        if sig == 0:
            raise ProcessLookupError("group no longer exists")

    real_os = os

    class FakePosixOs:
        name = "posix"
        killpg = staticmethod(mock_killpg)

        def __getattr__(self, name):
            return getattr(real_os, name)

    fake_os = FakePosixOs()
    monkeypatch.setattr(commands_module, "os", fake_os)

    result = broker._execute(
        ["python", "-c", "print(123)"],
        cwd=str(tmp_path),
        timeout=10,
    )

    assert result["exit_code"] == 0
    assert result["cleanup_unconfirmed"] is False
    assert result["success"] is True
    assert "123" in result["stdout"]
    assert any(sig == 0 for _, sig in killpg_calls)


def test_posix_command_lingering_children_terminates_group(monkeypatch, tmp_path):
    broker = CommandBroker(
        {"server": {"state_dir": str(tmp_path / "state")}},
        _DummyArtifacts(),
        _DummyRevisionState(),
    )

    killpg_calls = []

    def mock_killpg(pgid, sig):
        killpg_calls.append((pgid, sig))
        # Group still alive
        return None

    terminate_tree_calls = []

    def mock_terminate_tree(pid, **kwargs):
        terminate_tree_calls.append((pid, kwargs))
        return True

    real_os = os

    class FakePosixOs:
        name = "posix"
        killpg = staticmethod(mock_killpg)

        def __getattr__(self, name):
            return getattr(real_os, name)

    fake_os = FakePosixOs()
    monkeypatch.setattr(commands_module, "os", fake_os)
    monkeypatch.setattr(commands_module, "terminate_tree", mock_terminate_tree)

    result = broker._execute(
        ["python", "-c", "print('done')"],
        cwd=str(tmp_path),
        timeout=10,
    )

    assert result["exit_code"] == 0
    assert result["cleanup_unconfirmed"] is False
    assert result["success"] is True
    assert len(terminate_tree_calls) == 1

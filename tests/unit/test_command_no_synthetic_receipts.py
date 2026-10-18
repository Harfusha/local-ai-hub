from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from local_ai_hub import commands
from local_ai_hub.commands import CommandBroker


class _VerificationStore:
    def __init__(self) -> None:
        self.records: list[Any] = []

    def record(self, receipt: Any) -> None:
        self.records.append(receipt)


def _broker(state_dir: Path) -> tuple[CommandBroker, _VerificationStore]:
    state_dir.mkdir(parents=True, exist_ok=True)
    broker = CommandBroker(
        {
            "commands": {"allowed": True, "allow_unknown": True, "allow_validation": True},
            "server": {"state_dir": str(state_dir)},
        }
    )
    store = _VerificationStore()
    broker.verification_store = store
    return broker, store


def _stub_patch_pipeline(monkeypatch: pytest.MonkeyPatch, broker: CommandBroker, root: Path, result: dict[str, Any]) -> None:
    monkeypatch.setattr(broker, "_transaction_root_for_context", lambda _context: root)
    monkeypatch.setattr(commands, "_patch_write_paths", lambda *_args: ["note.txt"])
    monkeypatch.setattr(commands, "_snapshot_patch_targets", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(commands, "_assert_patch_root", lambda *_args: None)
    monkeypatch.setattr(
        commands.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stderr=b""),
    )
    broker.run = lambda *_args, **_kwargs: dict(result)  # type: ignore[method-assign]


@pytest.mark.parametrize("returned_receipt", [None, {"task_id": "task-1", "passed": True}])
def test_patch_and_verify_forwards_only_broker_receipts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    returned_receipt: dict[str, Any] | None,
) -> None:
    root = tmp_path.resolve()
    broker, store = _broker(tmp_path / "state")
    run_result: dict[str, Any] = {"success": True, "exit_code": 0}
    if returned_receipt is not None:
        run_result["verification_receipt"] = returned_receipt
    _stub_patch_pipeline(monkeypatch, broker, root, run_result)

    result = broker.patch_and_verify(
        "diff --git a/note.txt b/note.txt\n",
        root,
        command="echo verify",
        task_id="task-1",
        _transaction_context="transaction-1",
    )

    assert result["success"] is True
    assert result["tests_passed"] is True
    assert result["verification_receipt"] is returned_receipt
    assert store.records == []
    if returned_receipt is None:
        assert result["verification_receipt_warning"]
    else:
        assert "verification_receipt_warning" not in result


@pytest.mark.parametrize("returned_receipt", [None, {"task_id": "task-1", "passed": True}])
def test_repair_loop_forwards_only_broker_receipts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    returned_receipt: dict[str, Any] | None,
) -> None:
    root = tmp_path.resolve()
    broker, store = _broker(tmp_path / "state")
    (root / "note.txt").write_text("before", encoding="utf-8")
    monkeypatch.setattr(broker, "_transaction_root_for_context", lambda _context: root)
    monkeypatch.setattr(broker, "_require_task_worktree", lambda *_args, **_kwargs: None)
    run_result: dict[str, Any] = {"success": True, "exit_code": 0}
    if returned_receipt is not None:
        run_result["verification_receipt"] = returned_receipt
    broker.run = lambda *_args, **_kwargs: dict(run_result)  # type: ignore[method-assign]

    result = broker.repair_loop(
        "pytest -q",
        root,
        task_id="task-1",
        initial_result={"success": False, "exit_code": 1},
        fix_generator=lambda *_args: {"note.txt": "after"},
        paths=["note.txt"],
        _transaction_context="transaction-1",
    )

    assert result["success"] is True
    assert result["repaired"] is True
    assert result["verification_receipt"] is returned_receipt
    assert store.records == []
    if returned_receipt is None:
        assert result["verification_receipt_warning"]
    else:
        assert "verification_receipt_warning" not in result

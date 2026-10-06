from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path

import pytest

from local_ai_hub.work_fencing import FencingLeaseStore, LeaseLostError
from local_ai_hub.work_orchestrator import WorkOrchestrator, _JournalEntry


class _NoServices:
    verification_store = None

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str):
        self.calls.append(name)
        raise AssertionError(f"service call after terminal completion: {name}")


class _Leases:
    def claim_batch(self, tenant, root, paths, ttl_seconds=900, purpose="", *, coordination_id=None):
        return {"success": True, "lease_id": "unused", "paths": paths}

    def release(self, tenant, lease_id=""):
        return {"success": True}


class _Artifacts:
    def put(self, text, tenant, kind):
        return "unused-artifact"


def _orchestrator(tmp_path: Path) -> tuple[WorkOrchestrator, Path]:
    root = tmp_path / "repo"
    root.mkdir()
    app = WorkOrchestrator(
        {"work_orchestrator": {"enabled": True, "max_pending_work_orders": 4, "max_steps": 4, "max_llm_steps": 4, "max_seconds": 30}},
        tmp_path / "state",
        services=_NoServices(),
        commands=object(),
        leases=_Leases(),
        artifacts=_Artifacts(),
    )
    app._ensure_workers = lambda: None
    return app, root


def _submit_and_terminal(app: WorkOrchestrator, root: Path, work_id: str):
    response = app.submit("tenant", {
        "root": str(root),
        "task": "inspect fixture",
        "work_id": work_id,
        "acceptance_criteria": ["report result"],
        "budget": {"max_seconds": 30},
    })
    assert response["success"] is True
    row = app._next()
    assert row is not None and row["work_id"] == work_id
    terminal = {"summary": "successor already completed"}
    assert app._set_terminal_if_active(work_id, "complete", terminal) is True
    return row, terminal


def test_delayed_worker_does_not_claim_or_execute_after_successor_terminal_state(tmp_path: Path) -> None:
    app, root = _orchestrator(tmp_path)
    work_id = "delayed-worker-terminal"
    try:
        row, terminal = _submit_and_terminal(app, root, work_id)
        app._execute(row)

        stored = app._row(work_id, "tenant")
        assert stored is not None and stored["state"] == "complete"
        assert json.loads(stored["result_json"]) == terminal
        assert app.services.calls == []
        con = sqlite3.connect(app.fencing_store.path)
        try:
            assert con.execute("SELECT COUNT(*) FROM writer_fence_attempts").fetchone()[0] == 0
        finally:
            con.close()
    finally:
        app.close()


def test_fresh_attempt_cannot_rewrite_terminal_work_state(tmp_path: Path) -> None:
    app, root = _orchestrator(tmp_path)
    work_id = "terminal-state-immutable"
    try:
        _, terminal = _submit_and_terminal(app, root, work_id)
        attempt = app.fencing_store.claim_attempt(str(root), work_id, "late-owner", ttl_seconds=30)

        with pytest.raises(LeaseLostError):
            app._set_state(work_id, "planning", {"summary": "late worker"}, attempt=attempt)

        stored = app._row(work_id, "tenant")
        assert stored is not None and stored["state"] == "complete"
        assert json.loads(stored["result_json"]) == terminal
    finally:
        app.close()


def test_rollback_preflights_all_hardlinks_before_restoring_any_file(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    first = root / "first.txt"
    second = root / "second.txt"
    alias = tmp_path / "outside-alias.txt"
    first.write_bytes(b"first postimage\n")
    second.write_bytes(b"second postimage\n")
    try:
        os.link(second, alias)
    except OSError as exc:
        pytest.skip(f"hard links unavailable: {exc}")
    journal = [
        _JournalEntry(
            "second.txt", True, b"second before\n", True,
            hashlib.sha256(b"second postimage\n").hexdigest(),
        ),
        _JournalEntry(
            "first.txt", True, b"first before\n", True,
            hashlib.sha256(b"first postimage\n").hexdigest(),
        ),
    ]

    with pytest.raises(RuntimeError, match="hardlinked postimage"):
        WorkOrchestrator._rollback(root, journal)

    assert first.read_bytes() == b"first postimage\n"
    assert second.read_bytes() == b"second postimage\n"
    assert alias.read_bytes() == b"second postimage\n"


def test_rollback_preflights_non_directory_ancestors_before_restoring_any_file(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    first = root / "first.txt"
    first.write_bytes(b"first postimage\n")
    (root / "dir").write_bytes(b"replaced former directory\n")
    journal = [
        _JournalEntry(
            "dir/deleted.txt", False, b"", False,
            hashlib.sha256(b"").hexdigest(),
        ),
        _JournalEntry(
            "first.txt", True, b"first before\n", True,
            hashlib.sha256(b"first postimage\n").hexdigest(),
        ),
    ]

    with pytest.raises(RuntimeError, match="non-directory ancestor"):
        WorkOrchestrator._rollback(root, journal)

    assert first.read_bytes() == b"first postimage\n"
    assert (root / "dir").read_bytes() == b"replaced former directory\n"

from __future__ import annotations

import json
import time
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from local_ai_hub.async_jobs import AsyncJobManager


@pytest.mark.parametrize("workspace", [None, ""])
def test_rag_index_replay_requires_workspace(tmp_path, workspace):
    manager = SimpleNamespace(max_attempts=2)
    payload = {"root": str(tmp_path)}
    if workspace is not None:
        payload["workspace"] = workspace

    assert not AsyncJobManager._can_replay_after_interruption(
        manager, "rag_index", payload, attempts=1,
    )


def test_rag_index_replay_accepts_absolute_root_and_workspace(tmp_path):
    manager = SimpleNamespace(max_attempts=2)

    assert AsyncJobManager._can_replay_after_interruption(
        manager,
        "rag_index",
        {"root": str(tmp_path), "workspace": "repo-workspace"},
        attempts=1,
    )


def test_recovery_does_not_dispatch_rag_job_without_workspace(tmp_path, monkeypatch):
    manager = AsyncJobManager(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "async_jobs": {"max_attempts": 2},
        },
        scheduler=object(),
        artifacts=None,
        executor=lambda *_args: {"success": True},
    )
    dispatch = Mock()
    monkeypatch.setattr(manager, "_dispatch", dispatch)
    job_id = "rag-index-missing-workspace"
    now = time.time()
    try:
        with closing(manager._connect()) as con:
            con.execute(
                """INSERT INTO async_jobs(
                       job_id,action,request_hash,payload_json,state,created_at,updated_at,expires_at,attempts
                   ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    job_id, "rag_index", "request-hash",
                    json.dumps({"root": str(tmp_path)}), "running", now, now, now + 600, 1,
                ),
            )
            con.commit()

        assert manager.recover() == 0
        dispatch.assert_not_called()
        with closing(manager._connect()) as con:
            row = con.execute(
                "SELECT state,error FROM async_jobs WHERE job_id=?", (job_id,),
            ).fetchone()
        assert row[0] == "outcome_unknown"
        assert row[1] == "async job outcome unknown after restart; safe replay unavailable"
    finally:
        manager.close()

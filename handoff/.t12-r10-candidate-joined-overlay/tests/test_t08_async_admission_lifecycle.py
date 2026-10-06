from __future__ import annotations

import json
import importlib.util
import os
import sys
import threading
from contextlib import closing
from pathlib import Path
from typing import Any

_async_jobs_source = os.environ.get("T08_ASYNC_JOBS_SOURCE")
if _async_jobs_source:
    import local_ai_hub

    _spec = importlib.util.spec_from_file_location("local_ai_hub.async_jobs", _async_jobs_source)
    assert _spec is not None and _spec.loader is not None
    _module = importlib.util.module_from_spec(_spec)
    sys.modules["local_ai_hub.async_jobs"] = _module
    _spec.loader.exec_module(_module)
    AsyncJobManager = _module.AsyncJobManager
else:
    from local_ai_hub.async_jobs import AsyncJobManager


class _Artifacts:
    def put(self, *_args: Any, **_kwargs: Any) -> str:
        return "artifact-1"

    def get(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"success": True, "content": "{}"}


def _manager(tmp_path: Path, executor=None) -> AsyncJobManager:
    return AsyncJobManager(
        {"server": {"state_dir": str(tmp_path)}, "async_jobs": {"enabled": True}},
        scheduler=object(),
        artifacts=_Artifacts(),
        executor=executor or (lambda *_args: {"success": True}),
    )


def _allow_active_mode(manager: AsyncJobManager, monkeypatch) -> None:
    monkeypatch.setattr(
        manager,
        "_operational_mode_snapshot",
        lambda: {"mode": "active", "revision": 0, "degraded": False, "snapshot": None, "gate_error": None},
    )


def test_direct_service_admission_waits_for_full_handler_lifetime(tmp_path: Path, monkeypatch):
    manager = _manager(tmp_path)
    _allow_active_mode(manager, monkeypatch)
    entered, release, drained = threading.Event(), threading.Event(), threading.Event()

    def handler() -> None:
        with manager.inference_admission("transcribe") as rejection:
            assert rejection is None
            entered.set()
            assert release.wait(3)

    worker = threading.Thread(target=handler)
    try:
        worker.start()
        assert entered.wait(2)
        assert manager.inference_actions_active()
        assert not manager.wait_for_inference_actions({"transcribe"}, 0.01)
        manager.when_inference_actions_drained({"transcribe"}, drained.set)
        release.set()
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert manager.wait_for_inference_actions({"transcribe"}, 0.1)
        assert drained.is_set()
    finally:
        release.set()
        worker.join(timeout=4)
        manager.close()


def test_async_executor_tracks_job_until_service_returns_and_preserves_root(tmp_path: Path, monkeypatch):
    entered, release, drained = threading.Event(), threading.Event(), threading.Event()
    seen_payload: list[dict[str, Any]] = []

    def executor(_action: str, payload: dict[str, Any], _tenant: str) -> dict[str, Any]:
        seen_payload.append(dict(payload))
        entered.set()
        assert release.wait(3)
        return {"success": True}

    manager = _manager(tmp_path, executor)
    _allow_active_mode(manager, monkeypatch)
    try:
        submitted = manager.submit(
            "tenant-a",
            "delegate",
            {"task": "hold", "root": str(tmp_path), "cwd": str(tmp_path)},
        )
        job_id = submitted["job_id"]
        assert entered.wait(2)
        assert not manager.wait_for_inference_actions({"delegate"}, 0.01)
        manager.when_inference_actions_drained({"delegate"}, drained.set)
        with closing(manager._connect()) as con:
            persisted = con.execute(
                "SELECT payload_json FROM async_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        payload = json.loads(persisted[0])
        assert payload["root"] == str(tmp_path)
        assert payload["cwd"] == str(tmp_path)

        release.set()
        assert manager.wait("tenant-a", job_id, 1.0)["state"] == "done"
        assert manager.wait_for_inference_actions({"delegate"}, 0.2)
        assert drained.is_set()
        assert seen_payload[0]["root"] == str(tmp_path)
        assert seen_payload[0]["cwd"] == str(tmp_path)
    finally:
        release.set()
        manager.close()

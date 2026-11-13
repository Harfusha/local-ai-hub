from __future__ import annotations

import threading

from local_ai_hub import async_jobs as async_jobs_module
from local_ai_hub.async_jobs import AsyncJobManager
from local_ai_hub.sqlite_support import write_transaction


class _Job:
    def __init__(self) -> None:
        self.id = 7
        self.done = threading.Event()
        self.error = None


class _Scheduler:
    config = {"models": {"heavy_code": "test-model"}}

    def enqueue(self, *_args, **_kwargs):
        return _Job()


class _Artifacts:
    def put(self, _content, *, kind):
        return "artifact-1"

    def get(self, _artifact_id, *, offset=0, max_chars=256):
        return {"success": True, "text": "{}"}


def test_cancel_uses_bounded_write_transaction(monkeypatch, tmp_path):
    manager = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path / "state")}, "async_jobs": {"wait_max_seconds": 90}},
        _Scheduler(),
        _Artifacts(),
        lambda action, payload: {"success": True, "action": action, "task": payload.get("task")},
    )
    try:
        submitted = manager.submit("reason", {"task": "cancel transaction"}, dispatch_delay_seconds=30.0)
        observed: list[dict[str, object]] = []

        def record_transaction(connection, **kwargs):
            observed.append(kwargs)
            return write_transaction(connection, **kwargs)

        monkeypatch.setattr(async_jobs_module, "write_transaction", record_transaction, raising=False)

        result = manager.cancel(submitted["job_id"])

        assert result["success"] is True
        assert result["state"] == "cancelled"
        assert len(observed) == 1
        assert observed[0]["max_duration_seconds"] == 5.0
        assert observed[0]["rollback_label"] == "async job cancellation"
    finally:
        manager.close()

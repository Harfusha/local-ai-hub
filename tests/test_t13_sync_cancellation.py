"""Cancellation uses the job ID; retired tenant selectors reject by presence."""
import pytest

from test_async_jobs import _manager


def test_retired_tenant_selector_rejects_without_removing_queued_timer(tmp_path):
    manager, _scheduler = _manager(tmp_path)
    try:
        submitted = manager.submit(
            "reason", {"task": "delayed dispatch"},
            dispatch_delay_seconds=30,
        )
        job_id = submitted["job_id"]
        timer = manager._delayed_dispatch[job_id]

        with pytest.raises(TypeError, match="retired async job field: tenant"):
            manager.cancel(job_id, tenant="")
        assert manager._delayed_dispatch[job_id] is timer
        assert not timer.finished.is_set()
        assert manager.status(job_id)["state"] == "queued"

        cancelled = manager.cancel(job_id)
        assert cancelled["state"] == "cancelled"
        assert job_id not in manager._delayed_dispatch
        assert timer.finished.is_set()
    finally:
        manager.close()

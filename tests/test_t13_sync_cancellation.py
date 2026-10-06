"""Regression check for the tenant-first cancellation hunk retained during merge."""
from test_async_jobs import _manager


def test_foreign_tenant_cannot_remove_queued_dispatch_timer(tmp_path):
    manager, _scheduler = _manager(tmp_path)
    try:
        submitted = manager.submit(
            "tenant-a", "reason", {"task": "tenant-owned delayed dispatch"},
            dispatch_delay_seconds=30,
        )
        job_id = submitted["job_id"]
        timer = manager._delayed_dispatch[job_id]

        rejected = manager.cancel("tenant-b", job_id)

        assert rejected["success"] is False
        assert rejected["error"] == "async job not found"
        assert manager._delayed_dispatch[job_id] is timer
        assert not timer.finished.is_set()
        assert manager.status("tenant-a", job_id)["state"] == "queued"

        cancelled = manager.cancel("tenant-a", job_id)
        assert cancelled["state"] == "cancelled"
        assert job_id not in manager._delayed_dispatch
        assert timer.finished.is_set()
    finally:
        manager.close()

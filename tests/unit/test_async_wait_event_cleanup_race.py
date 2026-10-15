import threading

from local_ai_hub.async_jobs import AsyncJobManager


class _Job:
    id = 7

    def __init__(self):
        self.done = threading.Event()
        self.error = None


class _Scheduler:
    config = {"models": {"heavy_code": "test-model"}}

    def enqueue(self, model, tenant, source, execute, priority=1, *, background=True):
        return _Job()


class _Artifacts:
    def put(self, _content, _tenant, _kind):
        return "artifact-1"


def test_wait_rechecks_terminal_state_after_tick_removes_event(tmp_path, monkeypatch):
    manager = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path / "state")}, "async_jobs": {"wait_max_seconds": 90}},
        _Scheduler(),
        _Artifacts(),
        lambda action, payload, tenant: {"success": True, "action": action, "task": payload.get("task"), "tenant": tenant},
    )
    real_event_wait = threading.Event.wait
    try:
        monkeypatch.setattr(manager, "_dispatch_background", lambda _job_id: None)
        submitted = manager.submit("tenant-a", "reason", {"task": "wait race"})
        job_id = submitted["job_id"]

        real_status = manager.status
        first_status = True
        second_status_probed = False
        second_status_lock_probe = []

        def status_with_completion(tenant, requested_job_id):
            nonlocal first_status, second_status_probed
            snapshot = real_status(tenant, requested_job_id)
            if first_status:
                first_status = False
                assert snapshot["state"] == "queued"
                con = manager._connect()
                try:
                    con.execute(
                        "UPDATE async_jobs SET state='failed',error='completed during wait setup' WHERE job_id=?",
                        (job_id,),
                    )
                    con.commit()
                finally:
                    con.close()
                manager.tick()
                return snapshot
            if not second_status_probed:
                second_status_probed = True
                probe_done = threading.Event()

                def probe_lock_from_another_thread():
                    acquired = manager._lock.acquire(blocking=False)
                    second_status_lock_probe.append(acquired)
                    if acquired:
                        manager._lock.release()
                    probe_done.set()

                probe = threading.Thread(target=probe_lock_from_another_thread)
                probe.start()
                assert probe_done.wait(1)
                probe.join(1)
            return real_status(tenant, requested_job_id)

        monkeypatch.setattr(manager, "status", status_with_completion)
        wait_calls = []

        def record_wait(event, timeout=None):
            if any(event is owned_event for owned_event in manager._events.values()):
                wait_calls.append((event.is_set(), timeout))
                return event.is_set()
            return real_event_wait(event, timeout)

        monkeypatch.setattr(threading.Event, "wait", record_wait)

        result = manager.wait("tenant-a", job_id, 1)

        assert result["state"] == "failed"
        assert wait_calls == []
        assert second_status_lock_probe == [True]
        assert job_id not in manager._events
    finally:
        monkeypatch.setattr(threading.Event, "wait", real_event_wait)
        manager.close()

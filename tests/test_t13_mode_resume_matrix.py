from __future__ import annotations

from local_ai_hub.async_jobs import AsyncJobManager
from local_ai_hub.operational_mode import load_operational_mode, set_operational_mode


class _Scheduler:
    config = {"models": {"heavy_code": "fake-model"}}

    def enqueue(self, *_args, **_kwargs):
        raise AssertionError("resume reason action must use the fake executor")


class _Artifacts:
    def put(self, *_args, **_kwargs):
        return "artifact"


def test_persisted_pause_blocks_jobs_and_active_resume_dispatches_again(tmp_path):
    state_dir = tmp_path / "state"
    set_operational_mode(state_dir, "active")

    def create_manager():
        return AsyncJobManager(
            {
                "server": {"state_dir": str(state_dir)},
                "async_jobs": {"wait_max_seconds": 5},
            },
            _Scheduler(),
            _Artifacts(),
            lambda action, payload: {
                "success": True, "action": action, "task": payload.get("task"),
            },
        )

    manager = create_manager()
    try:
        set_operational_mode(state_dir, "gaming")
        gaming = manager.submit("reason", {"task": "must not launch"})
        assert gaming["success"] is False
        assert gaming["operational_mode"] == "gaming"

        manager.close()
        manager = create_manager()
        assert load_operational_mode(state_dir).mode == "gaming"
        set_operational_mode(state_dir, "maintenance")
        maintenance = manager.submit("reason", {"task": "still paused"})
        assert maintenance["success"] is False
        assert maintenance["operational_mode"] == "maintenance"

        manager.close()
        manager = create_manager()
        assert load_operational_mode(state_dir).mode == "maintenance"
        set_operational_mode(state_dir, "active")
        resumed = manager.submit("reason", {"task": "resume dispatch"})
        assert resumed["success"] is True
        assert load_operational_mode(state_dir).mode == "active"
        assert manager.wait(resumed["job_id"], timeout_seconds=2)["state"] == "done"
        assert manager.result(resumed["job_id"])["success"] is True
    finally:
        manager.close()

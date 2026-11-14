from __future__ import annotations

import pytest
from contextlib import closing

from local_ai_hub.async_jobs import AsyncJobManager


class _Artifacts:
    def put(self, _content, *, kind):
        return "test-artifact"

    def get(self, _artifact_id, *, offset=0, max_chars=256):
        return {"success": True, "text": "{}"}


class _FailedResourceStatus:
    def resource_status(self):
        raise OSError("telemetry unavailable")


@pytest.mark.parametrize(
    ("scheduler", "telemetry_error"),
    [(object(), "sample_unavailable"), (_FailedResourceStatus(), "sample_failed")],
)
def test_resource_admission_does_not_claim_capacity_without_telemetry(
    scheduler, telemetry_error
):
    manager = object.__new__(AsyncJobManager)
    manager.scheduler = scheduler

    admission = manager._resource_admission()

    assert admission["state"] == "degraded"
    assert admission["reason"] == "resource_telemetry_unavailable"
    assert admission["retryable"] is False
    assert admission["resource_sample"]["available"] is not True
    assert admission["resource_sample"]["telemetry_error"] == telemetry_error


def test_status_reports_persisted_job_without_claiming_current_capacity(tmp_path, monkeypatch):
    manager = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path)}},
        object(),
        _Artifacts(),
        lambda action, payload: {"success": True, "action": action},
    )
    monkeypatch.setattr(
        manager,
        "_operational_mode_snapshot",
        lambda: {"mode": "active", "revision": 0, "degraded": False, "snapshot": None, "gate_error": None},
    )
    try:
        submitted = manager.submit(
            "reason", {"task": "bounded"}, dispatch_delay_seconds=30
        )
        assert submitted["success"] is True
        assert submitted["admission"]["reason"] == "resource_telemetry_unavailable"

        status = manager.status(submitted["job_id"])

        assert status["state"] == "queued"
        assert status["admission"]["state"] == "accepted"
        assert status["admission"]["reason"] == "job_persisted"
    finally:
        manager.close()


def test_worker_short_circuit_does_not_claim_capacity_for_terminal_unknown_job(
    tmp_path, monkeypatch
):
    manager = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path)}},
        object(),
        _Artifacts(),
        lambda _action, _payload: pytest.fail("terminal job must not execute"),
    )
    monkeypatch.setattr(
        manager,
        "_operational_mode_snapshot",
        lambda: {"mode": "active", "revision": 0, "degraded": False, "snapshot": None, "gate_error": None},
    )
    try:
        submitted = manager.submit(
            "reason", {"task": "bounded"}, dispatch_delay_seconds=30
        )
        assert submitted["success"] is True
        with closing(manager._connect()) as connection:
            connection.execute(
                "UPDATE async_jobs SET state='outcome_unknown', error=? WHERE job_id=?",
                ("persisted uncertainty", submitted["job_id"]),
            )
            connection.commit()

        result = manager._execute(submitted["job_id"])

        assert result["state"] == "outcome_unknown"
        assert result["outcome_unknown"] is True
        assert "admission" not in result
    finally:
        manager.close()

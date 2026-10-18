"""Tenant-free speculative lint scheduling contracts."""

from __future__ import annotations

import inspect

import pytest

from local_ai_hub.speculative_lint import SpeculativeLintQueue


class _AsyncJobs:
    def __init__(self) -> None:
        self.submissions: list[tuple[str, dict, float]] = []
        self.cancelled: list[str] = []
        self.next_id = 0

    def submit(self, action: str, payload: dict, *, dispatch_delay_seconds: float) -> dict:
        self.next_id += 1
        self.submissions.append((action, payload, dispatch_delay_seconds))
        return {"success": True, "job_id": f"job-{self.next_id}"}

    def cancel(self, job_id: str) -> dict:
        self.cancelled.append(job_id)
        return {"success": True}

    def status(self, job_id: str) -> dict:
        return {"success": True, "job_id": job_id}


def test_queue_replaces_only_same_root_job_and_keeps_bounds(tmp_path) -> None:
    jobs = _AsyncJobs()
    queue = SpeculativeLintQueue(
        jobs,
        {"speculative_lint": {"enabled": True, "debounce_seconds": 0.25, "max_paths": 1}},
    )
    root_a = str(tmp_path / "a")
    root_b = str(tmp_path / "b")
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()

    first = queue.submit(root_a, ["one.py", "two.py"])
    second = queue.submit(root_a, ["three.py"])
    third = queue.submit(root_b, ["four.py"])

    assert first["job_id"] == "job-1"
    assert second["job_id"] == "job-2"
    assert third["job_id"] == "job-3"
    assert jobs.cancelled == ["job-1"]
    assert [item[0] for item in jobs.submissions] == ["speculative_lint"] * 3
    assert jobs.submissions[0][2] == 0.25
    assert len(jobs.submissions[0][1]["paths"]) == 1
    assert "tenant" not in jobs.submissions[0][1]


def test_status_and_cancel_use_job_id_only() -> None:
    jobs = _AsyncJobs()
    queue = SpeculativeLintQueue(jobs, {"speculative_lint": {"enabled": True}})

    assert queue.status("job-1")["job_id"] == "job-1"
    assert queue.cancel("job-1")["success"] is True
    assert jobs.cancelled == ["job-1"]


def test_public_methods_reject_retired_tenant_argument() -> None:
    for method_name in ("submit", "status", "cancel"):
        signature = inspect.signature(getattr(SpeculativeLintQueue, method_name))
        assert "tenant" not in signature.parameters
        with pytest.raises(TypeError):
            signature.bind_partial(object(), tenant=None)

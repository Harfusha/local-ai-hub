from __future__ import annotations

from pathlib import Path

import pytest

from local_ai_hub.speculative_lint import SpeculativeLintQueue, normalize_changed_paths


class _FakeAsyncJobs:
    def __init__(self) -> None:
        self.submissions: list[dict[str, object]] = []
        self.cancelled: list[str] = []

    def submit(self, tenant: str, action: str, payload: dict[str, object], *, dispatch_delay_seconds: float = 0.0) -> dict[str, object]:
        job_id = f"job-{len(self.submissions) + 1}"
        self.submissions.append({"tenant": tenant, "action": action, "payload": payload, "delay": dispatch_delay_seconds})
        return {"success": True, "job_id": job_id, "state": "queued"}

    def cancel(self, tenant: str, job_id: str) -> dict[str, object]:
        self.cancelled.append(job_id)
        return {"success": True, "job_id": job_id, "state": "cancelled"}


def test_speculative_lint_is_disabled_by_default(tmp_path: Path) -> None:
    queue = SpeculativeLintQueue(_FakeAsyncJobs(), {"speculative_lint": {}})

    result = queue.submit("agent", str(tmp_path), ["src/main.py"])

    assert result["success"] is False
    assert result["unsupported"] is True


def test_speculative_lint_replaces_pending_root_job_and_preserves_changed_paths(tmp_path: Path) -> None:
    async_jobs = _FakeAsyncJobs()
    queue = SpeculativeLintQueue(
        async_jobs,
        {"speculative_lint": {"enabled": True, "debounce_seconds": 0.25, "max_paths": 4}},
    )

    first = queue.submit("agent", str(tmp_path), ["src/one.py"])
    second = queue.submit("agent", str(tmp_path), ["src/two.py"])

    assert first["job_id"] == "job-1"
    assert second["job_id"] == "job-2"
    assert async_jobs.cancelled == ["job-1"]
    assert async_jobs.submissions[-1]["action"] == "speculative_lint"
    assert async_jobs.submissions[-1]["payload"]["paths"] == ["src/two.py"]
    assert async_jobs.submissions[-1]["delay"] == 0.25


def test_speculative_lint_rejects_paths_outside_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="within root"):
        normalize_changed_paths(tmp_path, ["../outside.py"])


def test_speculative_lint_limits_to_caller_supplied_changed_paths(tmp_path: Path) -> None:
    paths = normalize_changed_paths(tmp_path, ["b.py", "a.py", "b.py"])

    assert paths == ["a.py", "b.py"]

from __future__ import annotations

from pathlib import Path

import pytest

from local_ai_hub.speculative_lint import SpeculativeLintQueue, normalize_changed_paths


class _DummyAsyncJobs:
    def __init__(self) -> None:
        self.submissions: list[dict[str, object]] = []
        self.cancelled: list[tuple[str, str]] = []

    def submit(self, tenant: str, _kind: str, payload: dict[str, object], **_kwargs: object) -> dict[str, object]:
        job_id = f"job-{len(self.submissions) + 1}"
        self.submissions.append({"tenant": tenant, "payload": payload})
        return {"success": True, "job_id": job_id, "state": "queued"}

    def cancel(self, tenant: str, job_id: str) -> dict[str, object]:
        self.cancelled.append((tenant, job_id))
        return {"success": True, "job_id": job_id, "state": "cancelled"}

    def status(self, tenant: str, job_id: str) -> dict[str, object]:
        return {"success": True, "tenant": tenant, "job_id": job_id, "state": "queued"}


def test_normalize_changed_paths_accepts_sets_deterministically_and_rejects_nul(tmp_path: Path) -> None:
    paths = normalize_changed_paths(tmp_path, {"file2.py", "file1.py"})
    assert paths == ["file1.py", "file2.py"]

    with pytest.raises(ValueError, match="null bytes"):
        normalize_changed_paths(tmp_path, ["bad\x00name.py"])


def test_speculative_lint_tracks_bounded_roots_per_tenant(tmp_path: Path) -> None:
    jobs = _DummyAsyncJobs()
    queue = SpeculativeLintQueue(
        jobs,
        {"speculative_lint": {"enabled": True, "max_paths": 1, "max_tracked_roots": 2}},
    )

    queue.submit("tenant-a", str(tmp_path), {"z.py", "a.py"})
    queue.submit("tenant-b", str(tmp_path), {"z.py", "a.py"})

    assert jobs.cancelled == []
    assert len(queue._root_jobs) == 2
    assert jobs.submissions[0]["payload"]["paths"] == ["a.py"]  # type: ignore[index]
    assert jobs.submissions[1]["payload"]["paths"] == ["a.py"]  # type: ignore[index]


def test_speculative_lint_validates_job_id_and_cleans_cancelled_root(tmp_path: Path) -> None:
    jobs = _DummyAsyncJobs()
    queue = SpeculativeLintQueue(jobs, {"speculative_lint": {"enabled": True}})
    result = queue.submit("tenant-a", str(tmp_path), ["file.py"])
    job_id = str(result["job_id"])

    with pytest.raises(ValueError, match="job_id cannot be empty"):
        queue.status("tenant-a", " ")
    with pytest.raises(ValueError, match="job_id cannot be empty"):
        queue.cancel("tenant-a", "")

    queue.cancel("tenant-a", job_id)
    assert queue._root_jobs == {}

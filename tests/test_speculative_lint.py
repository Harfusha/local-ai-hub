from __future__ import annotations

from pathlib import Path

import pytest

from local_ai_hub.speculative_lint import (
    SpeculativeLintQueue,
    apply_path_coverage,
    normalize_changed_paths,
)
from local_ai_hub.services import LocalAIServices


class _FakeAsyncJobs:
    def __init__(self) -> None:
        self.submissions: list[dict[str, object]] = []
        self.cancelled: list[str] = []

    def submit(self, action: str, payload: dict[str, object], *, dispatch_delay_seconds: float = 0.0) -> dict[str, object]:
        job_id = f"job-{len(self.submissions) + 1}"
        self.submissions.append({"action": action, "payload": payload, "delay": dispatch_delay_seconds})
        return {"success": True, "job_id": job_id, "state": "queued"}

    def cancel(self, job_id: str) -> dict[str, object]:
        self.cancelled.append(job_id)
        return {"success": True, "job_id": job_id, "state": "cancelled"}


class _FakeCommandPolicy:
    def classify(self, _command: str) -> dict[str, object]:
        return {"allowed": True, "class": "read_only"}


class _FakeLintDaemon:
    def run(self, _executable: str, _root: str, *, paths: list[str], **_kwargs: object) -> dict[str, object]:
        return {"success": True, "linted_paths": list(paths)}


def test_speculative_lint_is_disabled_by_default(tmp_path: Path) -> None:
    queue = SpeculativeLintQueue(_FakeAsyncJobs(), {"speculative_lint": {}})

    result = queue.submit(str(tmp_path), ["src/main.py"])

    assert result["success"] is False
    assert result["unsupported"] is True


def test_speculative_lint_replaces_pending_root_job_and_preserves_changed_paths(tmp_path: Path) -> None:
    async_jobs = _FakeAsyncJobs()
    queue = SpeculativeLintQueue(
        async_jobs,
        {"speculative_lint": {"enabled": True, "debounce_seconds": 0.25, "max_paths": 4}},
    )

    first = queue.submit(str(tmp_path), ["src/one.py"])
    second = queue.submit(str(tmp_path), ["src/two.py"])

    assert first["job_id"] == "job-1"
    assert second["job_id"] == "job-2"
    assert async_jobs.cancelled == ["job-1"]
    assert async_jobs.submissions[-1]["action"] == "speculative_lint"
    assert async_jobs.submissions[-1]["payload"]["paths"] == ["src/two.py"]
    assert async_jobs.submissions[-1]["payload"]["root"] == str(tmp_path.resolve())
    assert "tenant" not in async_jobs.submissions[-1]
    assert async_jobs.submissions[-1]["delay"] == 0.25


def test_speculative_lint_rejects_paths_outside_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="within root"):
        normalize_changed_paths(tmp_path, ["../outside.py"])


def test_speculative_lint_limits_to_caller_supplied_changed_paths(tmp_path: Path) -> None:
    paths = normalize_changed_paths(tmp_path, ["b.py", "a.py", "b.py"])

    assert paths == ["a.py", "b.py"]


def test_speculative_lint_reports_path_truncation_in_submission_and_payload(tmp_path: Path) -> None:
    async_jobs = _FakeAsyncJobs()
    queue = SpeculativeLintQueue(
        async_jobs,
        {"speculative_lint": {"enabled": True, "max_paths": 2}},
    )

    result = queue.submit(str(tmp_path), ["c.py", "a.py", "b.py"])

    assert result["paths"] == ["a.py", "c.py"]
    assert result["requested_paths_count"] == 3
    assert result["accepted_paths_count"] == 2
    assert result["truncated"] is True
    assert result["omitted_paths_count"] == 1
    payload = async_jobs.submissions[0]["payload"]
    assert payload["requested_paths_count"] == 3
    assert payload["accepted_paths_count"] == 2
    assert payload["truncated"] is True
    assert payload["omitted_paths_count"] == 1


def test_speculative_lint_marks_capped_result_partial(tmp_path: Path) -> None:
    result = apply_path_coverage(
        {"success": True},
        {"requested_paths_count": 3, "truncated": True},
        ["a.py", "b.py"],
    )

    assert result["partial"] is True
    assert result["requested_paths_count"] == 3
    assert result["accepted_paths_count"] == 2
    assert result["omitted_paths_count"] == 1


def test_speculative_lint_service_marks_truncated_async_result_partial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    services = object.__new__(LocalAIServices)
    services.config = {"speculative_lint": {"daemon_mode": True, "timeout_seconds": 5}}
    services.commands = _FakeCommandPolicy()
    services._lint_daemons = _FakeLintDaemon()
    monkeypatch.setattr("local_ai_hub.services.shutil.which", lambda name: "ruff.exe" if name == "ruff" else None)

    result = services.speculative_lint({
        "root": str(tmp_path),
        "paths": ["a.py", "b.py"],
        "requested_paths_count": 3,
        "accepted_paths_count": 2,
        "truncated": True,
        "omitted_paths_count": 1,
    })

    assert result["success"] is True
    assert result["partial"] is True
    assert result["requested_paths_count"] == 3
    assert result["accepted_paths_count"] == 2
    assert result["omitted_paths_count"] == 1

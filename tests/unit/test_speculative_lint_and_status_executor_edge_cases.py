from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace
import pytest

from local_ai_hub import speculative_lint
from local_ai_hub.speculative_lint import SpeculativeLintQueue, normalize_changed_paths
from local_ai_hub.status_executor import StatusDependencyExecutor


def test_normalize_changed_paths_edge_cases(tmp_path: Path):
    # Null byte in root
    with pytest.raises(ValueError, match="null bytes"):
        normalize_changed_paths(f"{tmp_path}\x00bad", ["file.py"])

    # Null byte in path
    with pytest.raises(ValueError, match="null bytes"):
        normalize_changed_paths(tmp_path, ["file\x00bad.py"])

    # Valid path normalization
    (tmp_path / "valid.py").write_text("content", encoding="utf-8")
    assert normalize_changed_paths(tmp_path, ["valid.py"]) == ["valid.py"]


def test_speculative_lint_queue_edge_cases(tmp_path: Path):
    async_jobs = SimpleNamespace(
        cancel=lambda tenant, job_id: {"success": True},
        submit=lambda tenant, task_type, payload, **kwargs: {"job_id": "job_123"},
        status=lambda tenant, job_id: {"status": "running"},
    )
    config = {
        "speculative_lint": {
            "enabled": True,
            "debounce_seconds": float("nan"),
            "max_paths": float("inf"),
        }
    }
    queue = SpeculativeLintQueue(async_jobs, config)
    assert queue.is_enabled() is True
    assert queue.active_roots() == []

    (tmp_path / "f1.py").write_text("pass", encoding="utf-8")
    res = queue.submit("tenant_a", str(tmp_path), ["f1.py"])
    assert res.get("job_id") == "job_123"
    assert len(queue.active_roots()) == 1

    queue.clear()
    assert queue.active_roots() == []


def test_status_dependency_executor_edge_cases():
    # NaN/Inf or bool in capacity or max_workers
    with pytest.raises(ValueError, match="status executor capacity must be positive"):
        StatusDependencyExecutor(max_workers=1, capacity=0)

    executor = StatusDependencyExecutor(max_workers=float("nan"), capacity=float("inf"))  # type: ignore
    try:
        assert executor.is_closed() is False
        assert executor.pending_count() == 0
        assert executor.capacity() >= 1

        future = executor.submit(lambda x: x * 2, 21)
        assert future.result(timeout=2.0) == 42
    finally:
        executor.shutdown(wait=True)
        assert executor.is_closed() is True

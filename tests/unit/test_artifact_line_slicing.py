from __future__ import annotations

import time
from pathlib import Path
import pytest

from local_ai_hub.artifacts import ArtifactStore


def test_artifact_get_lines_returns_exact_range(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts.sqlite")
    content = "\n".join([f"line {i}" for i in range(1, 21)])  # 20 lines
    artifact_id = store.put(content, "agent", "test_log")

    # Fetch lines 5 to 10
    res = store.get_lines(artifact_id, start_line=5, end_line=10)
    assert res["success"] is True
    assert res["artifact_id"] == artifact_id
    assert res["start_line"] == 5
    assert res["end_line"] == 10
    assert res["total_lines"] == 20
    assert len(res["lines"]) == 6
    assert res["lines"][0] == "line 5"
    assert res["lines"][-1] == "line 10"
    assert res["text"] == "line 5\nline 6\nline 7\nline 8\nline 9\nline 10"


def test_artifact_get_lines_from_start_to_end(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts.sqlite")
    content = "first\nsecond\nthird"
    artifact_id = store.put(content, "agent", "summary")

    # Omit end_line -> read to end of file
    res = store.get_lines(artifact_id, start_line=2)
    assert res["success"] is True
    assert res["start_line"] == 2
    assert res["end_line"] == 3
    assert res["total_lines"] == 3
    assert res["lines"] == ["second", "third"]


def test_artifact_get_lines_out_of_bounds_handling(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts.sqlite")
    content = "alpha\nbeta"
    artifact_id = store.put(content, "agent", "short")

    # start_line beyond total_lines
    res = store.get_lines(artifact_id, start_line=50, end_line=60)
    assert res["success"] is True
    assert res["lines"] == []
    assert res["total_lines"] == 2

    # end_line greater than total_lines clamps to total_lines
    res2 = store.get_lines(artifact_id, start_line=1, end_line=100)
    assert res2["success"] is True
    assert res2["end_line"] == 2
    assert res2["lines"] == ["alpha", "beta"]


def test_artifact_get_lines_invalid_range_rejected(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts.sqlite")
    artifact_id = store.put("sample", "agent", "test")

    res = store.get_lines(artifact_id, start_line=10, end_line=5)
    assert res["success"] is False
    assert "greater than or equal" in res["error"]


def test_artifact_get_lines_tenant_isolation(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts.sqlite")
    artifact_id = store.put("tenant a secret\nline 2", "tenant_a", "secret")

    # Other tenant cannot read lines
    res = store.get_lines(artifact_id, start_line=1, end_line=2, tenant="tenant_b")
    assert res["success"] is False
    assert "not found" in res["error"]

    # Owning tenant can read
    res_ok = store.get_lines(artifact_id, start_line=1, end_line=2, tenant="tenant_a")
    assert res_ok["success"] is True
    assert res_ok["lines"] == ["tenant a secret", "line 2"]

from pathlib import Path
import pytest
from local_ai_hub import mcp_server


def test_artifact_direct_file_slice_by_lines(tmp_path: Path):
    sample_file = tmp_path / "hello.py"
    lines = [f"line {i}\n" for i in range(1, 21)]
    sample_file.write_text("".join(lines), encoding="utf-8")

    res = mcp_server.local_ai_artifact(
        action="slice",
        path=str(sample_file),
        line_start=5,
        line_end=10,
    )

    assert res["success"] is True
    assert res["line_start"] == 5
    assert res["line_end"] == 10
    assert res["total_lines"] == 20
    assert res["text"] == "".join(lines[4:10])


def test_artifact_direct_file_slice_nonexistent(tmp_path: Path):
    res = mcp_server.local_ai_artifact(
        action="slice",
        path=str(tmp_path / "missing.txt"),
    )
    assert res["success"] is False
    assert "not found" in res["error"].lower()

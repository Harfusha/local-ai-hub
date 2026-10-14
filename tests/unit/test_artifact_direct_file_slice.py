from pathlib import Path
import pytest
from local_ai_hub import mcp_server


def test_artifact_direct_file_slice_by_lines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(mcp_server, "_workspace", str(workspace))
    sample_file = workspace / "hello.py"
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


def test_artifact_direct_file_slice_nonexistent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(mcp_server, "_workspace", str(workspace))
    res = mcp_server.local_ai_artifact(
        action="slice",
        path=str(workspace / "missing.txt"),
    )
    assert res["success"] is False
    assert "not found" in res["error"].lower()


def test_artifact_direct_file_slice_rejects_paths_outside_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("secret\n", encoding="utf-8")
    monkeypatch.setattr(mcp_server, "_workspace", str(workspace))

    absolute_result = mcp_server.local_ai_artifact(action="slice", path=str(outside_file))
    traversal_result = mcp_server.local_ai_artifact(action="slice", path="../outside.txt")

    assert absolute_result["success"] is False
    assert traversal_result["success"] is False
    assert "workspace" in absolute_result["error"].lower()
    assert "workspace" in traversal_result["error"].lower()


def test_artifact_direct_file_slice_rejects_symlink_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("secret\n", encoding="utf-8")
    linked_file = workspace / "linked.txt"
    monkeypatch.setattr(mcp_server, "_workspace", str(workspace))
    try:
        linked_file.symlink_to(outside_file)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    result = mcp_server.local_ai_artifact(action="slice", path=str(linked_file))

    assert result["success"] is False
    assert "workspace" in result["error"].lower()

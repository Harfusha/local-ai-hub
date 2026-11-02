from local_ai_hub.source_slice import read_source_slice


def test_outside_source_error_explains_authorized_root_without_reading(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    target = other / "source.txt"
    target.write_text("private fixture content", encoding="utf-8")

    denied = read_source_slice(str(workspace), str(target))

    assert denied["success"] is False
    assert denied["terminal"] is True and denied["retryable"] is False
    assert "authorized" in denied["error"] and "root" in denied["error"]
    assert "private fixture content" not in repr(denied)
    accepted = read_source_slice(str(other), str(target))
    assert accepted["success"] is True
    assert accepted["text"] == "private fixture content"

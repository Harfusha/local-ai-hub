import pytest

from local_ai_hub.deterministic import DeterministicEngine


@pytest.mark.parametrize("external_path", ["../outside.py", "absolute"])
def test_slice_dependency_graph_rejects_paths_outside_repository(tmp_path, external_path):
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("def secret_symbol():\n    return 'private'\n", encoding="utf-8")
    path = str(outside) if external_path == "absolute" else external_path
    engine = object.__new__(DeterministicEngine)

    result = engine.slice_dependency_graph(str(root), "secret_symbol", path)

    assert result["success"] is False
    assert result["status_code"] == 400
    assert "inside the repository root" in result["error"]
    assert "sliced_code" not in result


def test_slice_dependency_graph_accepts_path_inside_repository(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "module.py"
    source.write_text("def visible_symbol():\n    return 'public'\n", encoding="utf-8")
    engine = object.__new__(DeterministicEngine)

    result = engine.slice_dependency_graph(str(root), "visible_symbol", "module.py")

    assert result["success"] is True
    assert result["file"] == "module.py"
    assert "return 'public'" in result["sliced_code"]

from __future__ import annotations

from pathlib import Path
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.repo_tools import RepositoryTools


def test_deterministic_affected_tests_mapping(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    (src / "math_ops.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_math_ops.py").write_text("def test_add():\n    pass\n", encoding="utf-8")
    (tests_dir / "test_unrelated.py").write_text("def test_other():\n    pass\n", encoding="utf-8")

    rt = RepositoryTools({})
    det = DeterministicEngine({}, repo_tools=rt)

    res = det.affected_tests(str(tmp_path), changed_paths=["src/math_ops.py"])
    assert res["success"] is True
    assert res["framework"] == "pytest"
    assert "tests/test_math_ops.py" in [p.replace("\\", "/") for p in res["test_files"]]
    assert "tests/test_unrelated.py" not in [p.replace("\\", "/") for p in res["test_files"]]
    assert "pytest" in res["suggested_command"]
    assert "test_math_ops.py" in res["suggested_command"]


def test_deterministic_affected_tests_no_changes(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    rt = RepositoryTools({})
    det = DeterministicEngine({}, repo_tools=rt)

    res = det.affected_tests(str(tmp_path), changed_paths=[])
    assert res["success"] is True
    assert res["test_files"] == []
    assert res["suggested_command"] == ""

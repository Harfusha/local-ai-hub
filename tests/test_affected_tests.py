from __future__ import annotations

from pathlib import Path
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.code_index import CodeIndex
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


def test_affected_tests_includes_ast_callers_from_code_index(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    src = tmp_path / "src"
    tests_dir = tmp_path / "tests"
    src.mkdir()
    tests_dir.mkdir()
    (src / "session_api.py").write_text("def resolveAuthToken(): pass\n", encoding="utf-8")
    (tests_dir / "test_login_journey.py").write_text(
        "def test_login_journey():\n    resolveAuthToken()\n", encoding="utf-8"
    )

    config = {"server": {"state_dir": str(tmp_path / "state")}}
    repo_tools = RepositoryTools(config)
    code_index = CodeIndex(config, repo_tools)
    assert code_index.update_file(str(tmp_path), "src/session_api.py")["success"] is True
    assert code_index.update_file(str(tmp_path), "tests/test_login_journey.py")["success"] is True
    deterministic = DeterministicEngine(config, repo_tools=repo_tools, code_index=code_index)

    result = deterministic.affected_tests(str(tmp_path), changed_paths=["src/session_api.py"])

    assert result["success"] is True
    assert "tests/test_login_journey.py" in result["test_files"]
    assert "test_login_journey.py" in result["suggested_command"]

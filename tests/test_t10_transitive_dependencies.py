from pathlib import Path
from contextlib import closing

from local_ai_hub.code_index import CodeIndex
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.repo_tools import RepositoryTools


def test_affected_tests_include_transitive_importers(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='impact-demo'\n", encoding="utf-8")
    sources = {
        "src/shared.py": "def shared_value():\n    return 1\n",
        "src/core.py": "from src.shared import shared_value\ndef core_value():\n    return shared_value()\n",
        "src/app.py": "from src.core import core_value\ndef app_value():\n    return core_value()\n",
        "tests/test_shared.py": "from src.shared import shared_value\ndef test_shared():\n    assert shared_value() == 1\n",
        "tests/test_core.py": "from src.core import core_value\ndef test_core():\n    assert core_value() == 1\n",
        "tests/test_app.py": "from src.app import app_value\ndef test_app():\n    assert app_value() == 1\n",
    }
    for relative, content in sources.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    config = {"server": {"state_dir": str(tmp_path / "state")}}
    repo_tools = RepositoryTools(config)
    code_index = CodeIndex(config, repo_tools)
    for relative in sources:
        assert code_index.update_file(str(tmp_path), relative)["success"] is True

    engine = DeterministicEngine(config, repo_tools=repo_tools, code_index=code_index)
    result = engine.affected_tests(str(tmp_path), changed_paths=["src/shared.py"])

    assert result["success"] is True
    assert {"tests/test_shared.py", "tests/test_core.py", "tests/test_app.py"}.issubset(
        set(result["test_files"])
    )


def test_impact_traverses_imports_when_changed_file_has_no_symbols(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src/shared.py").write_text("# intentionally empty module\n", encoding="utf-8")
    (root / "src/core.py").write_text("from src.shared import missing_name\n", encoding="utf-8")
    config = {"server": {"state_dir": str(tmp_path / "state")}}
    index = CodeIndex(config, RepositoryTools(config))
    assert index.update_file(str(root), "src/shared.py")["success"] is True
    assert index.update_file(str(root), "src/core.py")["success"] is True

    result = index.impact(str(root), ["src/shared.py"])

    assert result["changed_symbols"] == []
    assert "src/core.py" in {item["path"] for item in result["likely_dependents"]}


def test_truncated_import_graph_does_not_claim_exact_dependent_count(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src/shared.py").write_text("def shared_value():\n    return 1\n", encoding="utf-8")
    config = {"server": {"state_dir": str(tmp_path / "state")}}
    index = CodeIndex(config, RepositoryTools(config))
    assert index.update_file(str(root), "src/shared.py")["success"] is True
    resolved = str(root.resolve())
    with closing(index._connect()) as con:
        con.executemany(
            "INSERT INTO edges(root,src,dst,kind,path,line) VALUES(?,?,?,?,?,?)",
            [
                (resolved, "<module>", f"dependency_{number}", "imports", f"pkg/file_{number}.py", 1)
                for number in range(201)
            ],
        )
        con.commit()

    result = index.impact(str(root), ["src/shared.py"], max_dependents=1)

    assert result["coverage"]["complete"] is False
    assert result["coverage"]["dependent_candidate_count_exact"] is False
    assert result["coverage"]["dependent_count"] is None

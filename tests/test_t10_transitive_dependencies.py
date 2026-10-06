from pathlib import Path

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

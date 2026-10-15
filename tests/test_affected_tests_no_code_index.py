from pathlib import Path

from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.repo_tools import RepositoryTools


def test_affected_tests_include_transitive_importers_without_code_index(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    sources = {
        "src/shared.py": "VALUE = 1\n",
        "src/core.py": "from src.shared import VALUE\n",
        "src/app.py": "from src.core import VALUE\n",
        "tests/test_shared.py": "from src.shared import VALUE\n",
        "tests/test_core.py": "from src.core import VALUE\n",
        "tests/test_app.py": "from src.app import VALUE\n",
    }
    for relative, content in sources.items():
        (tmp_path / relative).write_text(content, encoding="utf-8")

    config = {"server": {"state_dir": str(tmp_path / "state")}}
    engine = DeterministicEngine(config, repo_tools=RepositoryTools(config))

    result = engine.affected_tests(str(tmp_path), changed_paths=["src/shared.py"])

    assert result["success"] is True
    assert {"tests/test_shared.py", "tests/test_core.py", "tests/test_app.py"}.issubset(
        set(result["test_files"])
    )

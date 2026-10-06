from __future__ import annotations

from pathlib import Path

from local_ai_hub.repo_tools import RepositoryTools


def test_python_search_fallback_has_its_own_file_budget(tmp_path: Path) -> None:
    for index in range(6):
        (tmp_path / f"file_{index}.py").write_text("unrelated content\n", encoding="utf-8")
    config = {
        "rag": {"extensions": [".py"]},
        "search": {
            "prefer_git_files": False,
            "use_git_grep_fallback": False,
            "use_ripgrep_if_available": False,
            "max_files": 50,
            "python_fallback_max_files": 2,
            "ripgrep_timeout_seconds": 0.75,
        },
    }
    tools = RepositoryTools(config)

    result = tools.search(str(tmp_path), "missingneedle")

    assert result["engine"] == "python"
    assert result["scanned_files"] == 2
    assert result["python_fallback_files_scanned"] == 2
    assert result["python_fallback_file_limit"] == 2
    assert tools.ripgrep_timeout == 0.75

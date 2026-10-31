import pytest
from pathlib import Path
from local_ai_hub.repo_tools import RepositoryTools

def test_python_fallback_search_respects_context_lines(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    file_path = repo / "sample.py"
    file_content = "\n".join(f"line_{i}" for i in range(1, 31))
    file_path.write_text(file_content, encoding="utf-8")

    # Create RepositoryTools and force fallback by setting ripgrep/git unavailable
    tools = RepositoryTools({})
    tools._ripgrep_path = None
    tools._git_path = None

    # Search for line_15 with context_lines=2
    res = tools.search(str(repo), "line_15", context_lines=2)
    assert res["success"] is True
    assert len(res["results"]) > 0
    hit = res["results"][0]
    # start_line should be 15 - 2 = 13, end_line should be 15 + 2 = 17
    assert hit["start_line"] == 13
    assert hit["end_line"] == 17
    lines = hit["text"].splitlines()
    assert len(lines) == 5
    assert "15: line_15" in hit["text"]

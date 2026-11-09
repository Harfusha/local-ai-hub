import shutil

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


@pytest.mark.parametrize("accelerated", [False, True], ids=["python", "ripgrep"])
@pytest.mark.parametrize("context_lines", [1, 9, None], ids=["low", "high", "default"])
def test_search_context_lines_match_across_engines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    accelerated: bool,
    context_lines: int | None,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "sample.py").write_text(
        "\n".join(f"line_{i}" for i in range(1, 31)), encoding="utf-8"
    )

    tools = RepositoryTools({})
    tools._ripgrep_path = None
    tools._git_path = None
    candidates = [("sample.py", 15)] if accelerated else None
    monkeypatch.setattr(tools, "_ripgrep_candidates", lambda *_args, **_kwargs: (candidates, False))
    monkeypatch.setattr(tools, "_git_grep_candidates", lambda *_args, **_kwargs: (None, False))

    if context_lines is None:
        result = tools.search(str(repo), "line_15")
        radius = tools.snippet_lines
    else:
        result = tools.search(str(repo), "line_15", context_lines=context_lines)
        radius = context_lines

    assert result["success"] is True
    assert result["engine"] == ("ripgrep" if accelerated else "python")
    assert len(result["results"]) == 1
    hit = result["results"][0]
    assert hit["start_line"] == max(1, 15 - radius)
    assert hit["end_line"] == min(30, 15 + radius)
    assert len(hit["text"].splitlines()) == hit["end_line"] - hit["start_line"] + 1


@pytest.mark.skipif(not shutil.which("rg"), reason="ripgrep required")
@pytest.mark.parametrize("context_lines", [1, 9, None], ids=["low", "high", "default"])
def test_search_context_lines_with_live_ripgrep(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    context_lines: int | None,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "sample.py").write_text(
        "\n".join(f"line_{i}" for i in range(1, 31)), encoding="utf-8"
    )

    tools = RepositoryTools({})
    monkeypatch.setattr(tools, "_git_grep_candidates", lambda *_args, **_kwargs: (None, False))

    if context_lines is None:
        result = tools.search(str(repo), "line_15")
        radius = tools.snippet_lines
    else:
        result = tools.search(str(repo), "line_15", context_lines=context_lines)
        radius = context_lines

    assert result["success"] is True
    assert result["engine"] == "ripgrep"
    assert len(result["results"]) == 1
    hit = result["results"][0]
    assert hit["start_line"] == max(1, 15 - radius)
    assert hit["end_line"] == min(30, 15 + radius)


@pytest.mark.parametrize("accelerated", [False, True], ids=["python", "ripgrep"])
def test_search_dedup_and_page_limits_hold_across_engines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    accelerated: bool,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    lines = [f"line_{i}" for i in range(1, 31)]
    for line_no in (5, 15, 25):
        lines[line_no - 1] = f"needle_{line_no}"
    (repo / "sample.py").write_text("\n".join(lines), encoding="utf-8")

    tools = RepositoryTools({})
    tools._ripgrep_path = None
    tools._git_path = None
    tools.max_snippets_per_file = 2
    candidates = [("sample.py", line_no) for line_no in (5, 15, 25)] if accelerated else None
    monkeypatch.setattr(tools, "_ripgrep_candidates", lambda *_args, **_kwargs: (candidates, False))
    monkeypatch.setattr(tools, "_git_grep_candidates", lambda *_args, **_kwargs: (None, False))

    result = tools.search(str(repo), "needle", context_lines=1, limit=1)

    assert result["success"] is True
    assert result["engine"] == ("ripgrep" if accelerated else "python")
    assert len(result["results"]) == 1
    assert result["matches_count"] == 2
    assert result["has_more"] is True
    assert result["truncated"] is True
    assert "result_limit" in result["truncation_reasons"]

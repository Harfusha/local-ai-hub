from pathlib import Path
import shutil
import subprocess

import pytest

from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.repo_tools import RepositoryTools


def test_structural_search_reports_incomplete_400_file_scan(tmp_path: Path, monkeypatch) -> None:
    filenames = [f"source_{index:03}.py" for index in range(401)]
    for filename in filenames:
        (tmp_path / filename).write_text("needle\n" if filename == filenames[-1] else "pass\n", encoding="utf-8")

    monkeypatch.setattr(
        "local_ai_hub.deterministic.os.walk",
        lambda _root: iter([(str(tmp_path), [], filenames)]),
    )

    result = DeterministicEngine().structural_search(str(tmp_path), pattern="needle")

    assert result["success"] is True
    assert result["files_scanned"] == 400
    assert result["matches"] == []
    assert result["truncated"] is True
    assert result["truncation_reasons"] == ["file_limit"]


def test_structural_search_only_reports_result_limit_when_match_is_omitted(tmp_path: Path) -> None:
    source = tmp_path / "one.ts"
    source.write_text("needle\nother\n", encoding="utf-8")
    engine = DeterministicEngine()

    exact = engine.structural_search(str(tmp_path), pattern="needle", path="one.ts", max_results=1)
    assert exact["count"] == 1
    assert exact["truncated"] is False

    source.write_text("needle\nneedle\n", encoding="utf-8")
    capped = engine.structural_search(str(tmp_path), pattern="needle", path="one.ts", max_results=1)
    assert capped["count"] == 1
    assert capped["truncated"] is True
    assert capped["truncation_reasons"] == ["result_limit"]


def test_structural_search_marks_syntax_fallback_partial(tmp_path: Path) -> None:
    source = tmp_path / "broken.py"
    source.write_text("def broken(:\n    needle()\n", encoding="utf-8")

    result = DeterministicEngine().structural_search(str(tmp_path), pattern="needle", path="broken.py")

    assert result["parse_errors"] == 1
    assert result["truncated"] is True
    assert result["truncation_reasons"] == ["parse_errors"]
    assert len(result["matches"]) == 1


def test_structural_search_marks_file_read_failure_partial(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "blocked.ts"
    source.write_text("needle\n", encoding="utf-8")
    original_read_text = Path.read_text

    def denied_read(path: Path, *args, **kwargs):
        if path == source:
            raise PermissionError("private path detail")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", denied_read)
    result = DeterministicEngine().structural_search(str(tmp_path), pattern="needle", path="blocked.ts")

    assert result["read_errors"] == 1
    assert result["truncated"] is True
    assert result["truncation_reasons"] == ["read_errors"]
    assert "private path detail" not in str(result)


def test_structural_search_skips_absolute_path_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("needle()\n", encoding="utf-8")

    result = DeterministicEngine().structural_search(str(root), pattern="needle", path=str(outside))

    assert result["success"] is True
    assert result["matches"] == []
    assert result["files_scanned"] == 0


def test_structural_search_does_not_swallow_unexpected_parser_failure(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "valid.py"
    source.write_text("needle()\n", encoding="utf-8")

    def broken_parser(*_args, **_kwargs):
        raise RuntimeError("parser bug")

    monkeypatch.setattr("local_ai_hub.deterministic.ast.parse", broken_parser)
    with pytest.raises(RuntimeError, match="parser bug"):
        DeterministicEngine().structural_search(str(tmp_path), pattern="needle", path="valid.py")


def test_python_repository_search_reports_file_scan_cap(tmp_path: Path, monkeypatch) -> None:
    filenames = [f"source_{index:03}.py" for index in range(3)]
    for filename in filenames:
        (tmp_path / filename).write_text("needle\n" if filename == filenames[-1] else "pass\n", encoding="utf-8")
    monkeypatch.setattr("local_ai_hub.repo_tools.os.walk", lambda _root, **_kwargs: iter([(str(tmp_path), [], filenames)]))
    tools = RepositoryTools({
        "rag": {"extensions": [".py"]},
        "search": {
            "max_files": 2,
            "prefer_git_files": False,
            "use_ripgrep_if_available": False,
            "use_git_grep_fallback": False,
        },
    })

    result = tools.search(str(tmp_path), "needle")

    assert result["engine"] == "python"
    assert result["scanned_files"] == 2
    assert result["results"] == []
    assert result["truncated"] is True
    assert result["truncation_reasons"] == ["file_limit"]


def test_python_repository_search_does_not_mark_exact_file_limit_truncated(tmp_path: Path, monkeypatch) -> None:
    filenames = ["first.py", "last.py"]
    for filename in filenames:
        (tmp_path / filename).write_text("needle\n", encoding="utf-8")
    monkeypatch.setattr("local_ai_hub.repo_tools.os.walk", lambda _root, **_kwargs: iter([(str(tmp_path), [], filenames)]))
    tools = RepositoryTools({
        "rag": {"extensions": [".py"]},
        "search": {
            "max_files": 2,
            "prefer_git_files": False,
            "use_ripgrep_if_available": False,
            "use_git_grep_fallback": False,
        },
    })

    result = tools.search(str(tmp_path), "needle")

    assert result["scanned_files"] == 2
    assert result["truncated"] is False
    assert result["truncation_reasons"] == []


def test_python_repository_search_cap_counts_only_readable_size_eligible_files(tmp_path: Path, monkeypatch) -> None:
    filenames = ["oversized.py", "first.py", "second.py", "last.py"]
    for filename in filenames:
        content = "x" * 20 if filename == "oversized.py" else ("needle\n" if filename == "last.py" else "pass\n")
        (tmp_path / filename).write_text(content, encoding="utf-8")
    monkeypatch.setattr("local_ai_hub.repo_tools.os.walk", lambda _root, **_kwargs: iter([(str(tmp_path), [], filenames)]))
    tools = RepositoryTools({
        "rag": {"extensions": [".py"], "max_file_bytes": 8},
        "search": {
            "max_files": 2,
            "prefer_git_files": False,
            "use_ripgrep_if_available": False,
            "use_git_grep_fallback": False,
        },
    })

    result = tools.search(str(tmp_path), "needle")

    assert result["scanned_files"] == 2
    assert result["truncated"] is True
    assert result["truncation_reasons"] == ["file_limit"]


@pytest.mark.skipif(shutil.which("git") is None, reason="Git is required for tracked/untracked inventory")
def test_git_inventory_probe_expands_cached_cap_and_filters_oversized_files(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    contents = {
        "aaa-oversized.py": "x" * 20,
        "bbb-first.py": "pass\n",
        "ccc-second.py": "pass\n",
        "ddd-last.py": "needle\n",
    }
    for filename, content in contents.items():
        (root / filename).write_text(content, encoding="utf-8")
    tools = RepositoryTools({
        "rag": {"extensions": [".py"], "max_file_bytes": 8},
        "search": {
            "max_files": 2,
            "prefer_git_files": True,
            "use_ripgrep_if_available": False,
            "use_git_grep_fallback": False,
        },
    })

    # Prime ordinary capped cache with an oversized candidate ahead of valid files.
    list(tools.iter_files(str(root)))
    result = tools.search(str(root), "needle")

    assert result["engine"] == "python"
    assert result["scanned_files"] == 2
    assert result["results"] == []
    assert result["truncated"] is True
    assert result["truncation_reasons"] == ["file_limit"]


def test_python_repository_search_reports_omitted_match_limit(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "many.py"
    source.write_text("\n".join(line for _ in range(5) for line in ("needle", *([""] * 8))), encoding="utf-8")
    monkeypatch.setattr("local_ai_hub.repo_tools.os.walk", lambda _root, **_kwargs: iter([(str(tmp_path), [], [source.name])]))
    tools = RepositoryTools({
        "rag": {"extensions": [".py"]},
        "search": {
            "max_hits": 1,
            "max_snippets_per_file": 10,
            "prefer_git_files": False,
            "use_ripgrep_if_available": False,
            "use_git_grep_fallback": False,
        },
    })

    result = tools.search(str(tmp_path), "needle", top_k=10)

    assert len(result["results"]) == 4
    assert result["truncated"] is True
    assert result["truncation_reasons"] == ["result_limit"]


def test_python_repository_search_reports_unreadable_file(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "blocked.py"
    source.write_text("needle\n", encoding="utf-8")
    monkeypatch.setattr("local_ai_hub.repo_tools.os.walk", lambda _root, **_kwargs: iter([(str(tmp_path), [], [source.name])]))
    tools = RepositoryTools({
        "rag": {"extensions": [".py"]},
        "search": {
            "prefer_git_files": False,
            "use_ripgrep_if_available": False,
            "use_git_grep_fallback": False,
        },
    })
    monkeypatch.setattr(tools, "_read_snapshot", lambda _path: (_ for _ in ()).throw(PermissionError("private path detail")))

    result = tools.search(str(tmp_path), "needle")

    assert result["truncated"] is True
    assert result["truncation_reasons"] == ["read_errors"]
    assert result["read_errors"] == 1
    assert "private path detail" not in str(result)


def test_accelerated_repository_search_reports_candidate_cap(tmp_path: Path, monkeypatch) -> None:
    names = [f"source_{index}.py" for index in range(5)]
    for name in names:
        (tmp_path / name).write_text("needle\n", encoding="utf-8")
    tools = RepositoryTools({
        "rag": {"extensions": [".py"]},
        "search": {"max_hits": 1, "max_snippets_per_file": 10},
    })
    monkeypatch.setattr(
        tools,
        "_ripgrep_candidates",
        lambda _base, _terms, _limit: ([(name, 1) for name in names], False),
    )

    result = tools.search(str(tmp_path), "needle", top_k=10)

    assert len(result["results"]) == 4
    assert result["truncated"] is True
    assert result["truncation_reasons"] == ["result_limit"]

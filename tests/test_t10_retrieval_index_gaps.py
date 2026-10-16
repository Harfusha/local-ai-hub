from __future__ import annotations

import subprocess
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub import code_index as code_index_module
from local_ai_hub.code_index import CodeIndex
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.treesitter_parser import is_treesitter_available


def test_typescript_named_arrow_call_edges_are_indexed(tmp_path: Path) -> None:
    if not is_treesitter_available("typescript"):
        pytest.skip("Tree-sitter parser unavailable for typescript")

    root = tmp_path / "repo"
    root.mkdir()
    (root / "runner.ts").write_text("const caller = () => target();\nfunction target() {}\n", encoding="utf-8")
    index = CodeIndex({"server": {"state_dir": str(tmp_path / "state")}}, repo_tools=RepositoryTools({}))

    assert index.update_files_batch(str(root), ["runner.ts"])["success"] is True
    callers = index.find_callers(str(root), "target", limit=10)
    assert any(edge.get("caller") == "caller" and edge.get("callee") == "target" for edge in callers["callers"])


def test_parser_analyzer_version_rejects_old_parse_blobs(tmp_path: Path) -> None:
    index = CodeIndex({"server": {"state_dir": str(tmp_path / "state")}}, repo_tools=None)
    old_version = f"{code_index_module.__version__}:call-edges-v15-native-point-tuples"
    with closing(index._connect()) as con:
        con.execute(
            "INSERT INTO parse_blobs(content_hash,analyzer_version,language,payload_json,updated_at) VALUES(?,?,?,?,?)",
            ("same-content", old_version, "rust", '{"edges":[]}', 0.0),
        )
        con.commit()

    assert code_index_module._PARSER_ANALYZER_VERSION != old_version
    assert index._parse_blob_get("same-content", "rust") is None


@pytest.mark.parametrize("mode", ["single", "batch"])
def test_same_content_reindexes_after_analyzer_version_bump(tmp_path: Path, monkeypatch, mode: str) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "module.py"
    source.write_text("def caller():\n    target()\n", encoding="utf-8")
    index = CodeIndex({"server": {"state_dir": str(tmp_path / "state")}}, repo_tools=RepositoryTools({}))
    content_hash, _lines = index.repo_tools._read_snapshot(source)
    assert index.update_file(str(root), "module.py")["success"] is True

    new_version = f"{code_index_module._PARSER_ANALYZER_VERSION}:test-bump"
    monkeypatch.setattr(code_index_module, "_PARSER_ANALYZER_VERSION", new_version)
    parse_calls: list[tuple[str, str]] = []
    parse_file_content = index._parse_file_content

    def track_parse(text: str, language: str, *, source_key: str | None = None):
        parse_calls.append((text, language))
        return parse_file_content(text, language, source_key=source_key)

    monkeypatch.setattr(index, "_parse_file_content", track_parse)
    if mode == "single":
        result = index.update_file(str(root), "module.py", content_hash)
        assert result["cached"] is False
    else:
        result = index.update_files_batch(str(root), [("module.py", content_hash)])
        assert result["files_processed"] == 1

    assert parse_calls == [("def caller():\n    target()", "python")]
    with closing(index._connect()) as con:
        row = con.execute(
            "SELECT analyzer_version FROM files WHERE root=? AND path=?",
            (str(root.resolve()), "module.py"),
        ).fetchone()
    assert row["analyzer_version"] == new_version


def test_capped_python_fallback_counter_is_separate_from_ripgrep_timeout(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "module.py").write_text("def target(): pass\n", encoding="utf-8")
    tools = RepositoryTools({
        "rag": {"extensions": [".py"]},
        "search": {
            "prefer_git_files": False,
            "max_files": 5,
            "use_git_grep_fallback": False,
            "use_ripgrep_if_available": False,
        },
    })

    result = tools.search(str(root), "target", 5)

    assert result["engine"] == "python"
    assert tools._git_stats["python_search_fallbacks"] == 1
    assert tools._git_stats["ripgrep_timeouts"] == 0


def test_ripgrep_timeout_counter_does_not_count_python_fallback(monkeypatch, tmp_path: Path) -> None:
    tools = RepositoryTools({})
    tools._rg = "rg"

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs.get("timeout"))

    monkeypatch.setattr("local_ai_hub.repo_tools.subprocess.run", timeout)
    candidates, failed = tools._ripgrep_candidates(tmp_path, ["needle"], 10)

    assert candidates is None
    assert failed is True
    assert tools._git_stats["ripgrep_timeouts"] == 1
    assert tools._git_stats["python_search_fallbacks"] == 0

from __future__ import annotations

from contextlib import closing

import pytest

from local_ai_hub.code_index import CodeIndex
from local_ai_hub import code_index as code_index_module
from local_ai_hub.treesitter_parser import is_treesitter_available, parse_treesitter

@pytest.mark.parametrize(
    ("language", "source", "caller", "callee"),
    [
        ("python", "def caller():\n    target()\n", "caller", "target"),
        ("csharp", "class Runner { void Caller() { Target(); } void Target() {} }", "Caller", "Target"),
        ("typescript", "function caller() { target(); }\nfunction target() {}", "caller", "target"),
        ("javascript", "function caller() { target(); }\nfunction target() {}", "caller", "target"),
        ("go", "package main\nfunc caller() { target() }\nfunc target() {}", "caller", "target"),
        (
            "rust",
            "struct Thing;\nimpl Thing { fn caller(&self) { Thing::target(); } fn target() {} }",
            "Thing::caller",
            "Thing::target",
        ),
    ],
)
def test_treesitter_extracts_direct_call_edges(language: str, source: str, caller: str, callee: str) -> None:
    if not is_treesitter_available(language):
        pytest.skip(f"Tree-sitter parser unavailable for {language}")

    parsed = parse_treesitter(source, language)

    assert parsed is not None
    _symbols, _refs, edges = parsed
    expected_target = callee if language == "rust" else callee.split("::")[-1]
    assert any(
        edge.get("kind") == "calls"
        and str(edge.get("src", "")).endswith(caller)
        and str(edge.get("dst", "")).endswith(expected_target)
        for edge in edges
    )

def test_code_index_call_queries_filter_non_call_edges_and_match_rust_paths(tmp_path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    index = CodeIndex({"server": {"state_dir": str(tmp_path / "state")}}, repo_tools=None)
    resolved = str(root.resolve())
    with closing(index._connect()) as con:
        con.executemany(
            "INSERT INTO edges(root,src,dst,kind,path,line) VALUES(?,?,?,?,?,?)",
            [
                (resolved, "Thing::caller", "Thing::target", "calls", "src/lib.rs", 2),
                (resolved, "Thing::caller", "Thing::target", "implements", "src/lib.rs", 1),
                (resolved, "Thing::target", "Thing::other", "imports", "src/lib.rs", 3),
            ],
        )
        con.commit()

    callers = index.find_callers(str(root), "target")
    callees = index.find_callees(str(root), "caller")

    assert [(item["caller"], item["callee"], item["kind"]) for item in callers["callers"]] == [
        ("Thing::caller", "Thing::target", "calls")
    ]
    assert [(item["caller"], item["callee"], item["kind"]) for item in callees["callees"]] == [
        ("Thing::caller", "Thing::target", "calls")
    ]

@pytest.mark.parametrize("wildcard", ["_", "%", "!"])
def test_call_queries_treat_like_metacharacters_as_literal_suffixes(tmp_path, wildcard) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    index = CodeIndex({"server": {"state_dir": str(tmp_path / "state")}}, repo_tools=None)
    resolved = str(root.resolve())
    target = f"target{wildcard}tail"
    caller = f"caller{wildcard}tail"
    with closing(index._connect()) as con:
        con.executemany(
            "INSERT INTO edges(root,src,dst,kind,path,line) VALUES(?,?,?,?,?,?)",
            [
                (resolved, "Pkg::caller_exact", f"Pkg::{target}", "calls", "src/lib.rs", 1),
                (resolved, "Pkg::caller_false", "Pkg::targetXtail", "calls", "src/lib.rs", 2),
                (resolved, f"Pkg::{caller}", "Pkg::target_exact", "calls", "src/lib.rs", 3),
                (resolved, "Pkg::callerXtail", "Pkg::target_false", "calls", "src/lib.rs", 4),
            ],
        )
        con.commit()

    callers = index.find_callers(str(root), target)["callers"]
    callees = index.find_callees(str(root), caller)["callees"]

    assert [item["caller"] for item in callers] == ["Pkg::caller_exact"]
    assert [item["callee"] for item in callees] == ["Pkg::target_exact"]

def test_missing_tree_sitter_language_returns_none(monkeypatch) -> None:
    import local_ai_hub.treesitter_parser as parser

    monkeypatch.setattr(parser, "_INIT_ATTEMPTED", True)
    monkeypatch.setattr(parser, "_PARSERS", {})

    assert parse_treesitter("fn caller() { target(); }", "rust") is None

def test_code_index_falls_back_when_tree_sitter_is_unavailable(monkeypatch, tmp_path) -> None:
    import local_ai_hub.treesitter_parser as parser

    index = CodeIndex({"server": {"state_dir": str(tmp_path / "state")}}, repo_tools=None)
    source = "def caller():\n    target()\n"
    parser_calls = []

    def unavailable(text, language):
        parser_calls.append((text, language))
        return {
            "result": None, "status": "unavailable", "parser": "tree_sitter",
            "fallback_reason": "parser_unavailable", "syntax_error_count": 0,
        }

    monkeypatch.setattr(parser, "parse_treesitter_with_status", unavailable)

    symbols, _refs, edges, diagnostic = index._parse_file_content_report(source, "python")

    assert parser_calls == [(source, "python")]
    assert any(item.get("name") == "caller" for item in symbols)
    assert any(
        item.get("kind") == "calls" and item.get("src") == "caller" and item.get("dst") == "target"
        for item in edges
    )
    assert diagnostic["fallback_used"] is True
    assert diagnostic["fallback_reason"] == "parser_unavailable"

def test_call_edge_analyzer_version_rejects_stale_parse_blobs(tmp_path) -> None:
    index = CodeIndex({"server": {"state_dir": str(tmp_path / "state")}}, repo_tools=None)
    with closing(index._connect()) as con:
        con.execute(
            "INSERT INTO parse_blobs(content_hash,analyzer_version,language,payload_json,updated_at) VALUES(?,?,?,?,?)",
            ("same-content", code_index_module.__version__, "rust", '{"edges":[]}', 0.0),
        )
        con.commit()

    assert code_index_module._PARSER_ANALYZER_VERSION != code_index_module.__version__
    assert index._parse_blob_get("same-content", "rust") is None

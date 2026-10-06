from __future__ import annotations

from pathlib import Path

import pytest

from local_ai_hub import treesitter_parser
from local_ai_hub.code_index import CodeIndex
from local_ai_hub.repo_tools import RepositoryTools


def _matching_edges(index: CodeIndex, root: Path, caller: str, callee: str) -> list[tuple[str, str]]:
    return [
        (edge["caller"].casefold(), edge["callee"].casefold())
        for edge in index.find_callees(str(root), caller)["callees"]
        if edge["caller"].casefold().endswith(caller.casefold())
        and edge["callee"].casefold().endswith(callee.casefold())
    ]


def test_fallback_call_owner_includes_constructor_bodies() -> None:
    symbols = [
        {"name": "Runner", "kind": "constructor", "line": 2, "end_line": 4, "name_path": "Runner/Runner"},
    ]

    owners = CodeIndex._call_owners_by_line(symbols, line_count=5)

    assert owners[3] == "Runner/Runner"


@pytest.mark.parametrize(
    ("language", "filename", "source", "caller", "callee"),
    [
        (
            "csharp",
            "runner.cs",
            "class Runner {\n void Caller() {\n  Target();\n }\n void Target() {}\n}\n",
            "Caller",
            "Target",
        ),
        (
            "typescript",
            "runner.ts",
            "function caller() {\n  target();\n}\nfunction target() {}\n",
            "caller",
            "target",
        ),
        (
            "javascript",
            "runner.js",
            "function caller() {\n  target();\n}\nfunction target() {}\n",
            "caller",
            "target",
        ),
        (
            "go",
            "runner.go",
            "package main\nfunc caller() {\n target()\n}\nfunc target() {}\n",
            "caller",
            "target",
        ),
        (
            "rust",
            "runner.rs",
            "fn caller() {\n target();\n}\nfn target() {}\n",
            "caller",
            "target",
        ),
        (
            "java",
            "Runner.java",
            "class Runner {\n void caller() {\n  target();\n }\n void target() {}\n}\n",
            "caller",
            "target",
        ),
        (
            "php",
            "Runner.php",
            "<?php\nclass Runner {\n public function caller() {\n  target();\n }\n public function target() {}\n}\n",
            "caller",
            "target",
        ),
        (
            "python",
            "runner.py",
            "def caller():\n    target()\n\ndef target():\n    return None\n",
            "caller",
            "target",
        ),
    ],
)
def test_builtin_fallback_preserves_callers_and_callees(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    language: str,
    filename: str,
    source: str,
    caller: str,
    callee: str,
) -> None:
    monkeypatch.setattr(treesitter_parser, "parse_treesitter", lambda *_args: None)
    root = tmp_path / "repo"
    target = root / "src" / filename
    target.parent.mkdir(parents=True)
    target.write_text(source, encoding="utf-8")
    config = {"server": {"state_dir": str(tmp_path / "state")}}

    tree_sitter_edges: list[tuple[str, str]] | None = None
    if treesitter_parser.is_treesitter_available(language):
        ast_root = tmp_path / "ast-repo"
        ast_target = ast_root / "src" / filename
        ast_target.parent.mkdir(parents=True)
        ast_target.write_text(source, encoding="utf-8")
        ast_config = {"server": {"state_dir": str(tmp_path / "ast-state")}}
        ast_index = CodeIndex(ast_config, RepositoryTools(ast_config))
        assert ast_index.update_file(str(ast_root), f"src/{filename}")["success"] is True
        tree_sitter_edges = _matching_edges(ast_index, ast_root, caller, callee)

    index = CodeIndex(config, RepositoryTools(config))

    assert index.update_file(str(root), f"src/{filename}")["success"] is True
    callers = index.find_callers(str(root), callee)["callers"]
    callees = index.find_callees(str(root), caller)["callees"]
    fallback_edges = _matching_edges(index, root, caller, callee)

    assert len(callers) == 1, callers
    assert len(callees) == 1, callees
    assert len(fallback_edges) == 1, fallback_edges
    assert fallback_edges[0][0].endswith(caller.casefold())
    assert fallback_edges[0][1].endswith(callee.casefold())
    if tree_sitter_edges is not None:
        assert tree_sitter_edges == fallback_edges
    assert any(
        edge["caller"].casefold().endswith(caller.casefold())
        and edge["callee"].casefold().endswith(callee.casefold())
        for edge in callers
    ), callers
    assert any(
        edge["caller"].casefold().endswith(caller.casefold())
        and edge["callee"].casefold().endswith(callee.casefold())
        for edge in callees
    ), callees


@pytest.mark.parametrize(
    ("caller", "caller_decoy", "callee", "callee_decoy"),
    [
        ("caller_a", "callerXa", "target_a", "targetXa"),
        ("caller%a", "callerXa", "target%a", "targetXa"),
        ("caller!a", "callera", "target!a", "targeta"),
    ],
)
def test_callgraph_suffix_queries_escape_sql_like_wildcards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caller: str,
    caller_decoy: str,
    callee: str,
    callee_decoy: str,
) -> None:
    monkeypatch.setattr(treesitter_parser, "parse_treesitter", lambda *_args: None)
    root = tmp_path / "repo"
    target = root / "src" / "calls.py"
    target.parent.mkdir(parents=True)
    target.write_text("# callgraph suffix matcher fixture\n", encoding="utf-8")
    config = {"server": {"state_dir": str(tmp_path / "state")}}
    index = CodeIndex(config, RepositoryTools(config))

    assert index.update_file(str(root), "src/calls.py")["success"] is True
    resolved = index.find_callers(str(root), callee)["root"]
    con = index._connect()
    try:
        con.execute(
            "INSERT INTO edges(root, src, dst, kind, path, line) VALUES (?, ?, ?, ?, ?, ?)",
            (resolved, f"module/{caller}", f"module/{callee}", "calls", "src/calls.py", 1),
        )
        con.execute(
            "INSERT INTO edges(root, src, dst, kind, path, line) VALUES (?, ?, ?, ?, ?, ?)",
            (
                resolved,
                f"module/{caller_decoy}",
                f"module/{callee_decoy}",
                "calls",
                "src/calls.py",
                2,
            ),
        )
        con.commit()
    finally:
        con.close()

    callers = index.find_callers(str(root), callee)["callers"]
    callees = index.find_callees(str(root), caller)["callees"]

    assert len(callers) == 1, callers
    assert callers[0]["callee"].endswith(callee), callers
    assert len(callees) == 1, callees
    assert callees[0]["caller"].endswith(caller), callees

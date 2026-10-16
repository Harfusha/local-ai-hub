from __future__ import annotations

from contextlib import closing
import sqlite3
import sys
from types import SimpleNamespace

import pytest

from local_ai_hub.code_index import CodeIndex
from local_ai_hub import code_index as code_index_module
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.retrieval import fuse_ranked_paths
from local_ai_hub import treesitter_parser
from local_ai_hub.treesitter_parser import is_treesitter_available, parse_treesitter


def test_fused_path_ranking_is_stable_across_backend_completion_order() -> None:
    groups = {
        "backend-0": ["src/p6.py", "src/p1.py", "src/p7.py", "src/p0.py", "src/p2.py", "src/p4.py", "src/p3.py"],
        "backend-1": ["src/p4.py", "src/p3.py", "src/p5.py"],
        "backend-2": ["src/p0.py", "src/p3.py", "src/p2.py", "src/p4.py", "src/p7.py", "src/p6.py"],
        "backend-3": ["src/p4.py", "src/p7.py", "src/p5.py", "src/p6.py"],
        "backend-4": ["src/p3.py", "src/p5.py", "src/p6.py", "src/p2.py", "src/p0.py"],
        "backend-5": ["src/p7.py", "src/p3.py", "src/p2.py", "src/p1.py", "src/p0.py", "src/p5.py"],
        "backend-6": ["src/p1.py", "src/p2.py", "src/p4.py", "src/p6.py"],
        "backend-7": ["src/p5.py", "src/p6.py", "src/p4.py", "src/p3.py", "src/p0.py", "src/p1.py"],
        "backend-8": ["src/p2.py", "src/p4.py", "src/p3.py", "src/p5.py", "src/p1.py", "src/p6.py", "src/p0.py", "src/p7.py"],
        "backend-9": ["src/p5.py", "src/p6.py", "src/p2.py"],
    }
    completion_order = ["backend-8", "backend-1", "backend-0", "backend-5", "backend-3", "backend-2", "backend-6", "backend-9", "backend-4", "backend-7"]

    expected = fuse_ranked_paths(groups, limit=8, max_per_path=8)
    completed = fuse_ranked_paths(
        {name: groups[name] for name in completion_order}, limit=8, max_per_path=8
    )

    assert completed == expected


def test_tree_sitter_loader_only_loads_dispatched_languages(monkeypatch) -> None:
    from local_ai_hub import treesitter_parser

    loaded: list[str] = []
    fake_pack = SimpleNamespace(
        has_language=lambda language: True,
        get_language=lambda language: (loaded.append(language) or object()),
        get_parser=lambda language: object(),
    )
    monkeypatch.setitem(sys.modules, "tree_sitter_language_pack", fake_pack)
    # Exercise lazy language loading independently of the Windows/Python 3.13+
    # safety guard, which intentionally disables native Tree-sitter there.
    monkeypatch.setattr(treesitter_parser.os, "name", "posix")
    monkeypatch.setattr(treesitter_parser, "_INIT_ATTEMPTED", False)
    monkeypatch.setattr(treesitter_parser, "_PARSERS", {})
    monkeypatch.setattr(treesitter_parser, "_LANGUAGES", {})

    assert treesitter_parser._init_treesitter() is True
    assert set(loaded) == {"c_sharp", "typescript", "tsx", "javascript", "python", "go", "rust", "cpp", "java"}


def test_deterministic_callers_intent_combines_direct_symbols_path_hints_and_ast_edges(tmp_path) -> None:
    root = tmp_path / "repo"
    files = {
        "src/target.py": "def load_record():\n    return 1\n",
        "src/web/caller.py": "def web_handler():\n    return load_record()\n",
        "tests/test_target.py": "def test_load_record():\n    return load_record()\n",
    }
    for relative, source in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")

    repo_tools = RepositoryTools({})
    index = CodeIndex({"server": {"state_dir": str(tmp_path / "state")}}, repo_tools=repo_tools)
    assert index.update_files_batch(str(root), list(files))["success"] is True
    engine = DeterministicEngine(
        {"server": {"state_dir": str(tmp_path / "state")}},
        repo_tools=repo_tools,
        code_index=index,
    )

    result = engine.query(str(root), "who calls load_record in src/web/caller.py?", limit=20)

    graph = result["code_index"]
    assert result["intent"] == "callers"
    assert any(symbol["name"] == "load_record" for symbol in graph["symbols"])
    assert any(symbol["path"] == "src/web/caller.py" for symbol in graph["symbols"])
    assert any(
        edge["callee"] == "load_record" and edge["path"] == "src/web/caller.py"
        for edge in graph["callers"]
    )
    assert {edge["path"] for edge in graph["callers"]} == {
        "src/web/caller.py",
        "tests/test_target.py",
    }
    assert "web_handler calls load_record — src/web/caller.py:2" in engine.render_answer(result)


@pytest.mark.parametrize(
    ("language", "filename", "source", "caller", "callee"),
    [
        ("csharp", "runner.cs", "class Runner { void Caller() { Target(); } void Target() {} }", "Caller", "Target"),
        ("typescript", "runner.ts", "function caller() { target(); } function target() {}", "caller", "target"),
        ("javascript", "runner.js", "function caller() { target(); } function target() {}", "caller", "target"),
        ("go", "runner.go", "package main\nfunc caller() { target() }\nfunc target() {}\n", "caller", "target"),
        ("rust", "runner.rs", "struct Thing; impl Thing { fn caller(&self) { Thing::target(); } fn target() {} }", "caller", "target"),
    ],
)
def test_deterministic_caller_query_resolves_tree_sitter_edges_across_languages(
    tmp_path, language: str, filename: str, source: str, caller: str, callee: str,
) -> None:
    if not is_treesitter_available(language):
        pytest.skip(f"Tree-sitter parser unavailable for {language}")

    root = tmp_path / "repo"
    relative = f"src/{filename}"
    source_path = root / relative
    source_path.parent.mkdir(parents=True)
    source_path.write_text(source, encoding="utf-8")
    repo_tools = RepositoryTools({})
    index = CodeIndex({"server": {"state_dir": str(tmp_path / "state")}}, repo_tools=repo_tools)
    assert index.update_files_batch(str(root), [relative])["success"] is True
    engine = DeterministicEngine(
        {"server": {"state_dir": str(tmp_path / "state")}},
        repo_tools=repo_tools,
        code_index=index,
    )

    result = engine.query(str(root), f"who calls {callee}?", limit=20)

    graph = result["code_index"]
    assert result["intent"] == "callers"
    assert graph["callers_success"] is True
    assert any(
        edge["path"] == relative
        and str(edge["caller"]).casefold().endswith(caller.casefold())
        and str(edge["callee"]).casefold().endswith(callee.casefold())
        for edge in graph["callers"]
    ), graph["callers"]

@pytest.mark.parametrize(
    ("language", "source", "caller", "callee"),
    [
        ("python", "def caller():\n    target()\n", "caller", "target"),
        ("csharp", "class Runner { void Caller() { Target(); } void Target() {} }", "Caller", "Target"),
        ("typescript", "function caller() { target(); }\nfunction target() {}", "caller", "target"),
        ("typescript", "const caller = () => target(); function target() {}", "caller", "target"),
        ("tsx", "function caller() { target(); return <div />; }\nfunction target() {}", "caller", "target"),
        ("tsx", "const caller = () => <div>{target()}</div>; function target() {}", "caller", "target"),
        ("javascript", "function caller() { target(); }\nfunction target() {}", "caller", "target"),
        ("go", "package main\nfunc caller() { target() }\nfunc target() {}", "caller", "target"),
        ("java", "class Runner {\n    void caller() { target(); }\n    void target() {}\n}", "caller", "target"),
        ("cpp", "class Runner { public:\n    void caller() { target(); }\n    void target() {}\n};", "caller", "target"),
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


@pytest.mark.parametrize(
    ("language", "source", "caller"),
    [
        ("python", "def caller():\n    f()\n", "caller"),
        ("csharp", "class Handler { void Caller() { f(); } }", "Caller"),
        ("typescript", "function caller() { f(); }", "caller"),
        ("javascript", "function caller() { f(); }", "caller"),
        ("go", "package api\nfunc caller() { f() }", "caller"),
        ("rust", "fn caller() { f(); }", "caller"),
        ("java", "class Handler { void caller() { f(); } }", "caller"),
        ("cpp", "class Handler { public: void caller() { f(); } };", "caller"),
    ],
)
def test_treesitter_keeps_single_character_calls_in_function_scope(
    language: str, source: str, caller: str
) -> None:
    if not is_treesitter_available(language):
        pytest.skip(f"Tree-sitter parser unavailable for {language}")

    parsed = parse_treesitter(source, language)

    assert parsed is not None
    _symbols, _refs, edges = parsed
    assert any(
        edge.get("kind") == "calls"
        and edge.get("dst") == "f"
        and str(edge.get("src", "")).endswith(caller)
        for edge in edges
    )


def test_code_index_finds_typescript_arrow_callers(tmp_path) -> None:
    if not is_treesitter_available("typescript"):
        pytest.skip("Tree-sitter parser unavailable for typescript")

    root = tmp_path / "repo"
    source_path = root / "src" / "runner.ts"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("const caller = () => target();\nfunction target() {}\n", encoding="utf-8")
    index = CodeIndex({"server": {"state_dir": str(tmp_path / "state")}}, repo_tools=RepositoryTools({}))

    assert index.update_files_batch(str(root), ["src/runner.ts"])["success"] is True
    callers = index.find_callers(str(root), "target", limit=10)
    callees = index.find_callees(str(root), "caller", limit=10)

    assert any(edge.get("caller") == "caller" and edge.get("callee") == "target" for edge in callers["callers"])
    assert any(edge.get("caller") == "caller" and edge.get("callee") == "target" for edge in callees["callees"])

@pytest.mark.parametrize(
    ("language", "source", "caller", "callee"),
    [
        ("java", "class Runner {\n    void caller() { target(); }\n    void target() {}\n}", "caller", "target"),
        ("cpp", "class Runner { public:\n    void caller() { target(); }\n    void target() {}\n};", "caller", "target"),
    ],
)
def test_code_index_fallback_keeps_java_cpp_calls_with_degraded_parser_status(
    tmp_path, language, source, caller, callee, monkeypatch
) -> None:
    monkeypatch.setattr(
        treesitter_parser,
        "parse_treesitter_with_status",
        lambda _source, _language: {
            "result": None, "status": "unavailable", "parser": "tree_sitter",
            "fallback_reason": "parser_unavailable", "syntax_error_count": 0,
        },
    )
    index = CodeIndex({"server": {"state_dir": str(tmp_path / f"state-{language}")}}, repo_tools=None)

    _symbols, _refs, edges, diagnostic = index._parse_file_content_report(source, language)

    assert diagnostic["fallback_used"] is True
    assert diagnostic["fallback_reason"] == "parser_unavailable"
    assert any(
        edge.get("kind") == "calls"
        and str(edge.get("src", "")).endswith(caller)
        and str(edge.get("dst", "")).endswith(callee)
        for edge in edges
    )


def test_code_index_call_queries_filter_non_call_edges_and_match_rust_paths(tmp_path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    index = CodeIndex({"server": {"state_dir": str(tmp_path / "state")}}, repo_tools=None)
    resolved = str(root.resolve())
    with closing(index._connect()) as con:
        con.executemany(
            "INSERT INTO edges(root,src,dst,src_name,dst_name,kind,path,line) VALUES(?,?,?,?,?,?,?,?)",
            [
                (resolved, "Thing::caller", "Thing::target", "caller", "target", "calls", "src/lib.rs", 2),
                (resolved, "Thing::caller", "Thing::target", "caller", "target", "implements", "src/lib.rs", 1),
                (resolved, "Thing::target", "Thing::other", "target", "other", "imports", "src/lib.rs", 3),
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


def test_call_graph_queries_report_truncation_and_unverified_freshness(tmp_path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    index = CodeIndex({"server": {"state_dir": str(tmp_path / "state")}}, repo_tools=None)
    resolved = str(root.resolve())
    with closing(index._connect()) as con:
        con.executemany(
            "INSERT INTO edges(root,src,dst,src_name,dst_name,kind,path,line) VALUES(?,?,?,?,?,?,?,?)",
            [
                (resolved, f"caller_{number}", "target", f"caller_{number}", "target", "calls", f"src/{number}.py", 1)
                for number in range(4)
            ],
        )
        con.commit()

    callers = index.find_callers(str(root), "target", limit=2)
    callees = index.find_callees(str(root), "caller_0", limit=2)

    assert callers["count"] == 2
    assert callers["truncated"] is True
    assert callers["coverage"]["complete"] is False
    assert callers["freshness"]["status"] == "not_checked"
    assert callees["count"] == 1
    assert callees["truncated"] is False
    assert callees["coverage"]["complete"] is True


def test_incremental_file_rename_and_delete_clear_caller_and_callee_edges(tmp_path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    old_file = root / "old.py"
    new_file = root / "new.py"
    old_file.write_text("def old_caller(): old_target()\n", encoding="utf-8")
    config = {"server": {"state_dir": str(tmp_path / "state")}}
    index = CodeIndex(config, repo_tools=RepositoryTools(config))

    assert index.update_files_batch(str(root), ["old.py"])["success"] is True
    assert index.find_callers(str(root), "old_target")["callers"]
    assert index.find_callees(str(root), "old_caller")["callees"]

    old_file.rename(new_file)
    new_file.write_text("def new_caller(): new_target()\n", encoding="utf-8")
    renamed = index.update_files_batch(str(root), ["old.py", "new.py"])

    assert renamed["success"] is True
    assert index.find_callers(str(root), "old_target")["callers"] == []
    assert index.find_callees(str(root), "old_caller")["callees"] == []
    assert index.find_callers(str(root), "new_target")["callers"]
    assert index.find_callees(str(root), "new_caller")["callees"]

    new_file.unlink()
    deleted = index.update_files_batch(str(root), ["new.py"])

    assert deleted["success"] is True
    assert index.find_callers(str(root), "new_target")["callers"] == []
    assert index.find_callees(str(root), "new_caller")["callees"] == []


def test_caller_and_callee_queries_are_ordered_and_sql_bounded(tmp_path, monkeypatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    index = CodeIndex({"server": {"state_dir": str(tmp_path / "state")}}, repo_tools=None)
    resolved = str(root.resolve())
    with closing(index._connect()) as con:
        con.executemany(
            "INSERT INTO edges(root,src,dst,src_name,dst_name,kind,path,line) VALUES(?,?,?,?,?,?,?,?)",
            [
                (resolved, f"caller_{i}", "target", f"caller_{i}", "target", "calls", path, 1)
                for i, path in [(0, "z.py"), (1, "a.py"), (2, "m.py")]
            ]
            + [
                (resolved, "Pkg::caller", f"Pkg::target_{i}", "caller", f"target_{i}", "calls", path, 1)
                for i, path in [(0, "z.py"), (1, "a.py"), (2, "m.py")]
            ],
        )
        con.commit()

    statements: list[str] = []
    original_connect = index._connect

    def traced_connect():
        con = original_connect()
        con.set_trace_callback(statements.append)
        return con

    monkeypatch.setattr(index, "_connect", traced_connect)
    callers = index.find_callers(str(root), "target", limit=2)
    callees = index.find_callees(str(root), "caller", limit=2)

    assert [item["path"] for item in callers["callers"]] == ["a.py", "m.py"]
    assert [item["path"] for item in callees["callees"]] == ["a.py", "m.py"]
    assert callers["truncated"] is True and callees["truncated"] is True
    graph_queries = [statement for statement in statements if "FROM edges" in statement]
    assert len(graph_queries) == 2
    assert all("ORDER BY path, line, src, dst, kind LIMIT 3" in statement for statement in graph_queries)


def test_call_graph_queries_honor_large_explicit_result_limits(tmp_path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    index = CodeIndex({"server": {"state_dir": str(tmp_path / "state")}}, repo_tools=None)
    resolved = str(root.resolve())
    result_limit = 5001
    with closing(index._connect()) as con:
        con.executemany(
            "INSERT INTO edges(root,src,dst,src_name,dst_name,kind,path,line) VALUES(?,?,?,?,?,?,?,?)",
            [
                (resolved, f"caller_{number}", "target", f"caller_{number}", "target", "calls", f"src/{number}.py", 1)
                for number in range(result_limit)
            ],
        )
        con.commit()

    result = index.find_callers(str(root), "target", limit=result_limit)

    assert result["count"] == result_limit
    assert result["truncated"] is False
    assert result["coverage"]["complete"] is True


def test_impact_reports_dependent_coverage_and_truncation(tmp_path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    target = root / "target.py"
    target.write_text("def SharedNeedle(): pass\n", encoding="utf-8")
    callers = []
    for number in range(3):
        path = root / f"caller_{number}.py"
        path.write_text(
            f"from target import SharedNeedle\ndef caller_{number}(): SharedNeedle()\n",
            encoding="utf-8",
        )
        callers.append(path.name)
    config = {"server": {"state_dir": str(tmp_path / "state")}}
    repo_tools = RepositoryTools(config)
    index = CodeIndex(config, repo_tools=repo_tools)
    items = [str(target.relative_to(root))] + callers
    assert index.update_files_batch(str(root), items)["success"] is True

    result = index.impact(str(root), ["target.py"], max_dependents=1)

    assert len(result["likely_dependents"]) == 1
    assert result["coverage"]["dependent_candidate_count"] == 3
    assert result["coverage"]["dependent_candidate_count_exact"] is True
    assert result["coverage"]["dependent_count"] == 3
    assert result["coverage"]["dependent_returned_count"] == 1
    assert result["coverage"]["dependents_truncated"] is True
    assert result["coverage"]["complete"] is False
    assert result["truncated"] is True
    assert result["truncation"]["likely_dependents"] is True


def test_impact_result_cache_reuses_warm_result_and_invalidates_after_index_update(tmp_path, monkeypatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "target.py").write_text("def SharedNeedle(): pass\n", encoding="utf-8")
    caller = root / "caller.py"
    caller.write_text("from target import SharedNeedle\ndef caller(): SharedNeedle()\n", encoding="utf-8")
    config = {"server": {"state_dir": str(tmp_path / "state")}}
    tools = RepositoryTools(config)
    index = CodeIndex(config, repo_tools=tools)
    assert index.update_files_batch(str(root), ["target.py", "caller.py"])["success"] is True

    initial = index.impact(str(root), ["target.py"])
    original_connect = index._connect
    connect_calls = 0

    def counted_connect():
        nonlocal connect_calls
        connect_calls += 1
        return original_connect()

    monkeypatch.setattr(index, "_connect", counted_connect)
    warm = index.impact(str(root), ["target.py"])
    assert connect_calls == 0
    assert warm == initial
    warm["likely_dependents"].clear()
    assert index.impact(str(root), ["target.py"]) == initial
    assert connect_calls == 0

    caller.write_text("def caller(): return 1\n", encoding="utf-8")
    assert index.update_files_batch(str(root), ["caller.py"])["success"] is True
    connect_calls = 0
    updated = index.impact(str(root), ["target.py"])

    assert connect_calls > 0
    assert updated["likely_dependents"] == []


def test_impact_reports_exact_candidate_count_when_bounded_scan_truncates(tmp_path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    resolved_root = str(root.resolve())
    index = CodeIndex({"server": {"state_dir": str(tmp_path / "state")}}, repo_tools=None)
    with closing(index._connect()) as con:
        con.execute(
            "INSERT INTO files(root,path,content_hash,language,updated_at) VALUES(?,?,?,?,?)",
            (resolved_root, "target.py", "target-hash", "python", 1.0),
        )
        con.execute(
            "INSERT INTO symbols(root,path,name,kind,line,end_line,container,name_path,signature,access,docstring) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (resolved_root, "target.py", "SharedNeedle", "function", 1, 1, "", "SharedNeedle", "", "public", ""),
        )
        con.executemany(
            "INSERT INTO refs(root,path,name,line,kind) VALUES(?,?,?,?,?)",
            [(resolved_root, "target.py", "SharedNeedle", 1, "call")]
            + [
                (resolved_root, f"consumer_{number:04}.py", "SharedNeedle", 1, "call")
                for number in range(2_001)
            ],
        )
        con.commit()

    result = index.impact(str(root), ["target.py"], max_dependents=100)

    assert len(result["likely_dependents"]) == 100
    assert result["coverage"]["dependent_candidate_count"] == 2_001
    assert result["coverage"]["dependent_candidate_count_exact"] is True
    assert result["coverage"]["dependent_count"] == 2_001
    assert result["coverage"]["dependent_returned_count"] == 100
    assert result["coverage"]["dependents_truncated"] is True
    assert result["coverage"]["complete"] is False
    assert result["truncation"]["likely_dependents"] is True

    full_result = index.impact(str(root), ["target.py"], max_dependents=2_001)

    assert len(full_result["likely_dependents"]) == 2_001
    assert full_result["coverage"]["dependent_candidate_count"] == 2_001
    assert full_result["coverage"]["complete"] is True
    assert full_result["truncated"] is False


def test_impact_exact_count_normalizes_mixed_path_separators(tmp_path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    resolved_root = str(root.resolve())
    index = CodeIndex({"server": {"state_dir": str(tmp_path / "state")}}, repo_tools=None)
    with closing(index._connect()) as con:
        con.execute(
            "INSERT INTO files(root,path,content_hash,language,updated_at) VALUES(?,?,?,?,?)",
            (resolved_root, "target.py", "target-hash", "python", 1.0),
        )
        con.execute(
            "INSERT INTO symbols(root,path,name,kind,line,end_line,container,name_path,signature,access,docstring) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (resolved_root, "target.py", "SharedNeedle", "function", 1, 1, "", "SharedNeedle", "", "public", ""),
        )
        con.executemany(
            "INSERT INTO refs(root,path,name,line,kind) VALUES(?,?,?,?,?)",
            [(resolved_root, f"consumer_{number:04}.py", "SharedNeedle", 1, "call") for number in range(201)]
            + [
                (resolved_root, "changed\\consumer.py", "SharedNeedle", 1, "call"),
                (resolved_root, "/changed/consumer.py", "SharedNeedle", 2, "call"),
                (resolved_root, "duplicate/consumer.py", "SharedNeedle", 1, "call"),
                (resolved_root, "duplicate\\consumer.py", "SharedNeedle", 1, "call"),
            ],
        )
        con.executemany(
            "INSERT INTO edges(root,src,dst,src_name,dst_name,kind,path,line) VALUES(?,?,?,?,?,?,?,?)",
            [
                (resolved_root, "caller", "SharedNeedle", "caller", "SharedNeedle", "calls", "/changed/consumer.py", 3),
                (resolved_root, "caller", "SharedNeedle", "caller", "SharedNeedle", "calls", "duplicate/consumer.py", 4),
            ],
        )
        con.execute(
            "INSERT INTO files(root,path,content_hash,language,updated_at) VALUES(?,?,?,?,?)",
            (resolved_root, "canonical_target.py", "canonical-target-hash", "python", 1.0),
        )
        con.execute(
            "INSERT INTO symbols(root,path,name,kind,line,end_line,container,name_path,signature,access,docstring) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (resolved_root, "canonical_target.py", "CanonicalNeedle", "function", 1, 1, "", "CanonicalNeedle", "", "public", ""),
        )
        con.executemany(
            "INSERT INTO refs(root,path,name,line,kind) VALUES(?,?,?,?,?)",
            [
                (resolved_root, f"canonical_consumer_{number:04}.py", "CanonicalNeedle", 1, "call")
                for number in range(201)
            ],
        )
        con.commit()

    canonical_prime = index.impact(str(root), ["canonical_target.py"], max_dependents=1)
    assert canonical_prime["coverage"]["dependent_candidate_count"] == 201
    assert canonical_prime["coverage"]["dependent_candidate_count_exact"] is True

    result = index.impact(str(root), ["target.py", "changed/consumer.py"], max_dependents=1)

    assert result["coverage"]["dependent_candidate_count"] == 202
    assert result["coverage"]["dependent_candidate_count_exact"] is True
    exact_count_cache_hits = index._impact_candidate_count_l1.hits
    index._impact_result_l1.clear()

    repeated_result = index.impact(str(root), ["target.py", "changed/consumer.py"], max_dependents=1)

    assert repeated_result["coverage"]["dependent_candidate_count"] == 202
    assert index._impact_candidate_count_l1.hits == exact_count_cache_hits + 1

    with closing(index._connect()) as con:
        con.execute(
            "INSERT INTO refs(root,path,name,line,kind) VALUES(?,?,?,?,?)",
            (resolved_root, "legacy\\consumer.py", "SharedNeedle", 1, "call"),
        )
        con.commit()
    other_index = CodeIndex({"server": {"state_dir": str(tmp_path / "state")}}, repo_tools=None)
    other_index._advance_query_cache_generation()

    after_mutation = index.impact(str(root), ["target.py", "changed/consumer.py"], max_dependents=1)

    assert after_mutation["coverage"]["dependent_candidate_count"] == 203
    assert after_mutation["coverage"]["dependent_candidate_count_exact"] is True


def test_impact_candidate_indexes_cover_symbol_and_path_columns(tmp_path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    index = CodeIndex({"server": {"state_dir": str(tmp_path / "state")}}, repo_tools=None)
    with closing(index._connect()) as con:
        ref_indexes = {str(row[1]) for row in con.execute("PRAGMA index_list(refs)")}
        edge_indexes = {str(row[1]) for row in con.execute("PRAGMA index_list(edges)")}

    assert "idx_refs_name_path" in ref_indexes
    assert "idx_edges_dst_path" in edge_indexes


def test_impact_marks_candidate_count_inexact_when_changed_symbols_are_truncated(tmp_path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    files = {
        "target_a.py": "def AlphaNeedle(): pass\n",
        "target_b.py": "def BetaNeedle(): pass\n",
        "consumer_a.py": "from target_a import AlphaNeedle\nAlphaNeedle()\n",
        "consumer_b.py": "from target_b import BetaNeedle\nBetaNeedle()\n",
    }
    for name, body in files.items():
        (root / name).write_text(body, encoding="utf-8")
    index = CodeIndex({"server": {"state_dir": str(tmp_path / "state")}}, repo_tools=RepositoryTools({}))
    assert index.update_files_batch(str(root), list(files))["success"] is True

    result = index.impact(str(root), ["target_a.py", "target_b.py"], max_symbols=1)

    assert result["truncation"]["changed_symbols"] is True
    assert result["coverage"]["dependent_candidate_count_exact"] is False
    assert result["coverage"]["dependents_truncated"] is True


def test_impact_checks_later_changed_file_chunks_before_reporting_symbol_truncation(tmp_path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    index = CodeIndex({"server": {"state_dir": str(tmp_path / "state")}}, repo_tools=None)
    with closing(index._connect()) as con:
        con.execute(
            "INSERT INTO symbols(root,path,name,kind,line,end_line,container,name_path,signature,access,docstring) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (str(root.resolve()), "changed_000.py", "OnlySymbol", "function", 1, 1, "", "OnlySymbol", "", "public", ""),
        )
        con.commit()

    changed_paths = [f"changed_{number:03}.py" for number in range(401)]
    result = index.impact(str(root), changed_paths, max_symbols=1)

    assert result["truncation"]["changed_symbols"] is False
    assert result["coverage"]["dependent_candidate_count_exact"] is True


@pytest.mark.parametrize("operation", ["callers", "callees", "impact"])
def test_graph_database_failures_report_incomplete_coverage(monkeypatch, tmp_path, operation) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    index = CodeIndex({"server": {"state_dir": str(tmp_path / "state")}}, repo_tools=None)

    def fail_connect():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(index, "_connect", fail_connect)
    if operation == "callers":
        result = index.find_callers(str(root), "target")
    elif operation == "callees":
        result = index.find_callees(str(root), "caller")
    else:
        result = index.impact(str(root), ["target.py"])

    assert result["success"] is False
    assert result["coverage"]["complete"] is False
    assert result["freshness"]["status"] == "not_checked"


def test_read_only_graph_queries_skip_global_database_lock(tmp_path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    index = CodeIndex({"server": {"state_dir": str(tmp_path / "state")}}, repo_tools=None)

    class RejectGlobalLock:
        def __enter__(self):
            raise AssertionError("read-only graph query serialized on the global writer lock")

        def __exit__(self, *_args):
            return False

    index._lock = RejectGlobalLock()

    callers = index.find_callers(str(root), "unused_symbol", limit=10)
    callees = index.find_callees(str(root), "unused_symbol", limit=10)

    assert callers["success"] is True
    assert callers["callers"] == []
    assert callees["success"] is True
    assert callees["callees"] == []


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
            "INSERT INTO edges(root,src,dst,src_name,dst_name,kind,path,line) VALUES(?,?,?,?,?,?,?,?)",
            [
                (resolved, "Pkg::caller_exact", f"Pkg::{target}", "caller_exact", target, "calls", "src/lib.rs", 1),
                (resolved, "Pkg::caller_false", "Pkg::targetXtail", "caller_false", "targetXtail", "calls", "src/lib.rs", 2),
                (resolved, f"Pkg::{caller}", "Pkg::target_exact", caller, "target_exact", "calls", "src/lib.rs", 3),
                (resolved, "Pkg::callerXtail", "Pkg::target_false", "callerXtail", "target_false", "calls", "src/lib.rs", 4),
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

    assert code_index_module._PARSER_ANALYZER_VERSION == f"{code_index_module.__version__}:call-edges-v13-scoped-fallback"
    assert index._parse_blob_get("same-content", "rust") is None

from __future__ import annotations

import re
import os
import hashlib
import time
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub.code_index import CodeIndex
from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.treesitter_parser import is_treesitter_available


@pytest.mark.parametrize(
    ("language", "filename", "source", "caller", "callee"),
    [
        ("csharp", "runner.cs", "class Runner { void Caller() { Target(); } void Target() {} }", "Caller", "Target"),
        ("typescript", "runner.ts", "function caller() { target(); }\nfunction target() {}", "caller", "target"),
        ("javascript", "runner.js", "function caller() { target(); }\nfunction target() {}", "caller", "target"),
        ("go", "runner.go", "package main\nfunc caller() { target() }\nfunc target() {}", "caller", "target"),
        ("rust", "lib.rs", "fn caller() { target(); }\nfn target() {}", "caller", "target"),
        ("tsx", "runner.tsx", "function caller() { target(); }\nfunction target() {}", "caller", "target"),
        ("java", "Runner.java", "class Runner { void caller() { target(); } void target() {} }", "caller", "target"),
        ("cpp", "runner.cpp", "void target() {}\nvoid caller() { target(); }", "caller", "target"),
    ],
)
def test_tree_sitter_language_edges_reach_sqlite_callers_and_callees(
    tmp_path: Path, language: str, filename: str, source: str, caller: str, callee: str,
) -> None:
    if language in ("java", "cpp"):
        assert is_treesitter_available(language), f"Tree-sitter parser unavailable for {language}"
    elif not is_treesitter_available(language):
        pytest.skip(f"Tree-sitter parser unavailable for {language}")

    root = tmp_path / "repo"
    relative = f"src/{filename}"
    target = root / relative
    target.parent.mkdir(parents=True)
    target.write_text(source, encoding="utf-8")
    config = {"server": {"state_dir": str(tmp_path / "state")}}
    index = CodeIndex(config, RepositoryTools(config))

    assert index.update_files_batch(str(root), [relative])["success"] is True
    callers = index.find_callers(str(root), callee)["callers"]
    callees = index.find_callees(str(root), caller)["callees"]

    assert any(
        edge["path"] == relative
        and edge["caller"].casefold().endswith(caller.casefold())
        and edge["callee"].casefold().endswith(callee.casefold())
        for edge in callers
    ), callers
    assert any(
        edge["path"] == relative
        and edge["caller"].casefold().endswith(caller.casefold())
        and edge["callee"].casefold().endswith(callee.casefold())
        for edge in callees
    ), callees


def test_call_queries_exclude_non_call_graph_edges(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    index = CodeIndex({"server": {"state_dir": str(tmp_path / "state")}}, repo_tools=None)
    resolved = str(root.resolve())
    with closing(index._connect()) as con:
        con.executemany(
            "INSERT INTO edges(root,src,dst,kind,path,line) VALUES(?,?,?,?,?,?)",
            [
                (resolved, "Pkg/real_caller", "Pkg/target", "calls", "src/caller.py", 1),
                (resolved, "Pkg/import_source", "Pkg/target", "imports", "src/importer.py", 2),
                (resolved, "Pkg/owner", "Pkg/real_callee", "calls", "src/callee.py", 3),
                (resolved, "Pkg/owner", "Pkg/imported_name", "imports", "src/importer.py", 4),
            ],
        )
        con.commit()

    callers = index.find_callers(str(root), "target")["callers"]
    callees = index.find_callees(str(root), "owner")["callees"]

    assert [(row["caller"], row["kind"]) for row in callers] == [("Pkg/real_caller", "calls")]
    assert [(row["callee"], row["kind"]) for row in callees] == [("Pkg/real_callee", "calls")]


def test_batch_rename_and_delete_remove_stale_call_edges(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    config = {"server": {"state_dir": str(tmp_path / "state")}}
    index = CodeIndex(config, RepositoryTools(config))
    old_file, new_file = root / "old.py", root / "new.py"
    old_file.write_text("def old_caller(): old_target()\n", encoding="utf-8")

    assert index.update_files_batch(str(root), ["old.py"])["success"] is True
    assert index.find_callers(str(root), "old_target")["callers"]
    assert index.find_callees(str(root), "old_caller")["callees"]

    old_file.rename(new_file)
    new_file.write_text("def new_caller(): new_target()\n", encoding="utf-8")
    assert index.update_files_batch(str(root), ["old.py", "new.py"])["success"] is True
    assert index.find_callers(str(root), "old_target")["callers"] == []
    assert index.find_callees(str(root), "old_caller")["callees"] == []
    assert index.find_callers(str(root), "new_target")["callers"]
    assert index.find_callees(str(root), "new_caller")["callees"]

    new_file.unlink()
    assert index.update_files_batch(str(root), ["new.py"])["success"] is True
    assert index.find_callers(str(root), "new_target")["callers"] == []
    assert index.find_callees(str(root), "new_caller")["callees"] == []


@pytest.mark.parametrize("mode", ["single", "batch"])
def test_same_size_same_mtime_reindex_invalidates_symbol_query_cache(tmp_path: Path, mode: str) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "module.py"
    before = "def alpha_old():\n    return 1\n"
    after = "def bravo_new():\n    return 1\n"
    assert len(before) == len(after)
    source.write_text(before, encoding="utf-8")
    config = {"server": {"state_dir": str(tmp_path / "state")}}
    index = CodeIndex(config, RepositoryTools(config))
    assert index.update_file(str(root), "module.py")["success"] is True
    assert index.query(str(root), "alpha_old")["symbols"]

    prior = source.stat()
    source.write_text(after, encoding="utf-8")
    os.utime(source, ns=(prior.st_atime_ns, prior.st_mtime_ns))
    current = source.stat()
    assert current.st_size == prior.st_size
    assert current.st_mtime_ns == prior.st_mtime_ns
    if mode == "single":
        updated = index.update_file(str(root), "module.py")
        assert updated["cached"] is False
    else:
        updated = index.update_files_batch(str(root), ["module.py"])
        assert updated["files_processed"] == 1

    assert index.query(str(root), "alpha_old")["symbols"] == []
    assert any(row["name"] == "bravo_new" for row in index.query(str(root), "bravo_new")["symbols"])


def test_preprocess_hash_and_code_index_refresh_same_size_same_mtime_edit(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "module.py"
    before = "def alpha_old():\n    return 1\n"
    after = "def bravo_new():\n    return 1\n"
    assert len(before) == len(after)
    source.write_text(before, encoding="utf-8")
    config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {"hash_files_per_step": 4},
    }
    tools = RepositoryTools(config)
    code_index = CodeIndex(config, tools)
    assert code_index.update_file(str(root), "module.py")["success"] is True
    old_hash = tools._hash_file_only(source)
    prior = source.stat()
    source.write_text(after, encoding="utf-8")
    os.utime(source, ns=(prior.st_atime_ns, prior.st_mtime_ns))
    current = source.stat()
    assert current.st_size == prior.st_size
    assert current.st_mtime_ns == prior.st_mtime_ns

    pre = ProjectPreprocessor(config, None, None, None, None, tools, code_index=code_index)
    try:
        with closing(pre._connect()) as con:
            now = time.time()
            con.execute(
                "INSERT INTO file_refs(root,path,content_hash,size,mtime_ns,needs_hash,rag_hash,last_accessed_at,generation,card_key,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (str(root), "module.py", old_hash, len(after), prior.st_mtime_ns, 1, None, 0.0, 1, None, now),
            )
            con.commit()

        assert pre._step_hash({"root": str(root), "generation": 1}) is True
        with closing(pre._connect()) as con:
            row = con.execute(
                "SELECT content_hash,needs_hash FROM file_refs WHERE root=? AND path=?",
                (str(root), "module.py"),
            ).fetchone()
        current_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        assert row[0] == current_hash
        assert row[1] == 0

        indexed = code_index.update_files_batch(str(root), [("module.py", current_hash)])
        assert indexed["files_processed"] == 1
        assert code_index.query(str(root), "alpha_old")["symbols"] == []
        assert any(row["name"] == "bravo_new" for row in code_index.query(str(root), "bravo_new")["symbols"])
    finally:
        pre.close()


def test_impact_chunks_large_changed_path_sets_and_caps_graph_queries(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    index = CodeIndex({"server": {"state_dir": str(tmp_path / "state")}}, repo_tools=None)
    resolved = str(root.resolve())
    changed = [f"src/file_{number}.py" for number in range(1200)]
    with closing(index._connect()) as con:
        con.executemany(
            "INSERT INTO files(root,path,content_hash,language,updated_at) VALUES(?,?,?,?,?)",
            [(resolved, path, f"hash-{i}", "python", 0.0) for i, path in enumerate(changed[:12])],
        )
        con.executemany(
            "INSERT INTO symbols(root,path,name,kind,line,end_line,container,name_path,signature,access,docstring) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            [
                (resolved, path, f"Symbol{i}", "function", i + 1, i + 1, "", f"Symbol{i}", "", "public", "")
                for i, path in enumerate(changed[:12])
            ],
        )
        con.executemany(
            "INSERT INTO edges(root,src,dst,kind,path,line) VALUES(?,?,?,?,?,?)",
            [
                (resolved, f"dependent_{i}", f"Symbol{i % 12}", "calls", f"src/dependent_{i}.py", i + 1)
                for i in range(40)
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
    result = index.impact(str(root), changed, max_symbols=12, max_dependents=7)

    assert result["success"] is True
    assert result["changed_files_count"] == 1200
    assert result["indexed_changed_files"] == 12
    assert len(result["changed_symbols"]) <= 12
    assert len(result["likely_dependents"]) <= 7

    path_queries = [sql for sql in statements if "SELECT path FROM files" in sql and "path IN" in sql]
    assert len(path_queries) == 3
    for sql in path_queries:
        match = re.search(r"path IN \((.*?)\)", sql, re.DOTALL)
        assert match is not None
        assert match.group(1).count(",") + 1 <= 400
    symbol_queries = [sql for sql in statements if "SELECT path,name,kind,line,name_path FROM symbols" in sql]
    assert len(symbol_queries) == 1
    assert "LIMIT 12" in symbol_queries[0]
    graph_queries = [sql for sql in statements if "SELECT path,dst,kind FROM edges" in sql]
    assert len(graph_queries) == 1
    assert "LIMIT 200" in graph_queries[0]

def test_code_index_maps_cpp_and_keeps_tsx_on_typescript() -> None:
    assert CodeIndex._lang("src/runner.cpp") == "cpp"
    assert CodeIndex._lang("src/runner.tsx") == "typescript"
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub import code_index as code_index_module
from local_ai_hub import treesitter_parser
from local_ai_hub.code_index import CodeIndex
from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.process_utils import canonical_root
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.services import LocalAIServices
from local_ai_hub.treesitter_parser import is_treesitter_available, parse_treesitter

class _SnapshotReader:
    ignore_dirs: set[str] = set()

    @staticmethod
    def _read_snapshot(path: Path) -> tuple[str, list[str]]:
        source = Path(path).read_bytes()
        return hashlib.sha256(source).hexdigest(), source.decode("utf-8", errors="replace").splitlines()

def _new_index(tmp_path: Path) -> tuple[CodeIndex, Path]:
    root = tmp_path / "repo"
    root.mkdir()
    index = CodeIndex({"server": {"state_dir": str(tmp_path / "state")}}, _SnapshotReader())
    return index, root

def test_code_index_query_reports_candidate_freshness_coverage_and_truncation(tmp_path: Path) -> None:
    index, root = _new_index(tmp_path)
    for number in range(4):
        source = root / "src" / f"controller_{number}.py"
        source.parent.mkdir(exist_ok=True)
        source.write_text(f"def WidgetController{number}(): pass\n", encoding="utf-8")

    indexed = index.update_files_batch(str(root), [f"src/controller_{number}.py" for number in range(4)])
    assert indexed["success"] is True

    result = index.query(str(root), "WidgetController", limit=1, verify_freshness=True)

    assert result["truncated"] is True
    assert result["returned_count"] == 1
    assert result["coverage"]["query_term_coverage"] == 1.0
    assert result["coverage"]["complete"] is False
    assert result["freshness"]["status"] == "verified_current_candidates"
    assert result["parse_outcomes"]["files_examined"] == 1
    current = index.query(str(root), "WidgetController", limit=20, verify_freshness=True)
    assert current["confidence"] >= 0.90
    stale_path = result["symbols"][0]["path"]
    (root / stale_path).write_text("def UnrelatedController(): pass\n", encoding="utf-8")

    stale = index.query(str(root), "WidgetController", limit=1, verify_freshness=True)

    assert stale["freshness"]["status"] == "stale_candidates"
    assert stale_path in stale["freshness"]["stale_paths"]
    assert stale["confidence"] < current["confidence"]

def test_code_index_missing_root_reports_incomplete_freshness_and_coverage(tmp_path: Path) -> None:
    index, _root = _new_index(tmp_path)

    result = index.query(str(tmp_path / "missing"), "WidgetController", verify_freshness=True)

    assert result["success"] is False
    assert result["stale_root"] is True
    assert result["freshness"]["status"] == "stale_root"
    assert result["freshness"]["complete"] is False
    assert result["coverage"]["complete"] is False
    assert result["truncated"] is False

def test_code_index_reports_syntax_failure_and_parser_fallback_outcomes(tmp_path: Path) -> None:
    if not is_treesitter_available("python"):
        pytest.skip("Tree-sitter parser unavailable for Python")
    index, root = _new_index(tmp_path)
    broken = root / "src" / "broken.py"
    unsupported = root / "src" / "Legacy.java"
    broken.parent.mkdir()
    broken.write_text("def broken():\n    if True\n        return target()\n", encoding="utf-8")
    unsupported.write_text("class Legacy { void run() { target(); } }\n", encoding="utf-8")

    result = index.update_files_batch(str(root), ["src/broken.py", "src/Legacy.java"])

    outcomes = result["parse_outcomes"]
    assert outcomes["syntax_error_files"] == 1
    assert outcomes["fallback_files"] == 1
    reports = {item["path"]: item for item in outcomes["diagnostics"]}
    assert reports["src/broken.py"]["status"] == "syntax_error"
    assert reports["src/broken.py"]["syntax_error_count"] >= 1
    assert reports["src/Legacy.java"]["status"] == "fallback"
    assert reports["src/Legacy.java"]["fallback_reason"] == "parser_unavailable"
    broken_query = index.query(str(root), "broken", limit=5, verify_freshness=True)
    assert broken_query["parse_outcomes"]["syntax_error_files"] == 1
    legacy_query = index.query(str(root), "Legacy", limit=5, verify_freshness=True)
    assert legacy_query["parse_outcomes"]["fallback_files"] == 1
    assert legacy_query["parse_outcomes"]["unavailable_files"] == 1

@pytest.mark.parametrize(
    ("language", "source", "expected_call"),
    [
        ("python", "from fastapi import APIRouter\nrouter = APIRouter()\n@router.get('/items')\ndef list_items():\n    # phantom_comment_call()\n    note = 'phantom_string_call()'\n    return repository.load_items()\ndef unused_target(): pass\n", "load_items"),
        ("csharp", "using Microsoft.AspNetCore.Mvc; class ItemsController : Controller { IActionResult Get() { // phantom_comment_call()\n var note = \"phantom_string_call()\"; return service.LoadAsync(); } void UnusedTarget() {} }", "LoadAsync"),
        ("typescript", "import { useState } from 'react'; function ItemsPage() { // phantom_comment_call()\n const note = 'phantom_string_call()'; useState([]); return service.loadItems(); } function unusedTarget() {}", "loadItems"),
        ("javascript", "function handler() { // phantom_comment_call()\n const note = 'phantom_string_call()'; return service.fetchItems(); } function unusedTarget() {}", "fetchItems"),
        ("go", "package api\nimport \"net/http\"\nfunc Handler(w http.ResponseWriter, r *http.Request) { // phantom_comment_call()\n note := \"phantom_string_call()\"\n service.LoadItems()\n}\nfunc unusedTarget() {}\n", "LoadItems"),
        ("rust", "async fn handler() { // phantom_comment_call()\n let note = \"phantom_string_call()\"; repo::fetch_items().await; }\nfn unused_target() {}\n", "fetch_items"),
    ],
)
def test_framework_fixtures_keep_only_real_call_edges(language: str, source: str, expected_call: str) -> None:
    if not is_treesitter_available(language):
        pytest.skip(f"Tree-sitter parser unavailable for {language}")

    parsed = parse_treesitter(source, language)

    assert parsed is not None
    _symbols, _refs, edges = parsed
    targets = [str(edge.get("dst", "")) for edge in edges if edge.get("kind") == "calls"]
    assert any(target.endswith(expected_call) for target in targets)
    assert not any("phantom_" in target or "unusedTarget" in target or "unused_target" in target for target in targets)


@pytest.mark.parametrize(
    ("language", "source", "expected_call"),
    [
        (
            "csharp",
            'class Handler { void Run() { // phantomCommentCall()\n'
            ' /* void phantomMethod() {} phantomBlockCall(); */\n'
            ' var note = @"phantomVerbatimCall()"; service.LoadAsync(); } }',
            "LoadAsync",
        ),
        (
            "typescript",
            '/* function phantomFunction() {} phantomBlockCall(); */\n'
            'function handler() { // phantomCommentCall()\n'
            ' const sep = /[/*]/; const note = `phantomTemplateCall()`; return service.loadItems(); }',
            "loadItems",
        ),
        (
            "javascript",
            'function handler() { /* phantomBlockCall() */\n'
            ' const sep = /[/*]/; const note = "phantomStringCall()"; return service.fetchItems(); }',
            "fetchItems",
        ),
        (
            "go",
            'package api\n/* func phantomFunction() {} phantomBlockCall() */\n'
            'func handler() { // phantomCommentCall()\n'
            ' note := `phantomRawCall()`; service.LoadItems() }',
            "LoadItems",
        ),
        (
            "rust",
            '/* fn phantom_function() {} phantom_block_call() */\n'
            "fn handler(value: &'static str) { // phantom_comment_call()\n"
            ' let note = r##"phantom_raw_call()"##; service.fetch_items(); }',
            "fetch_items",
        ),
        (
            "java",
            'class Handler { /* void phantomMethod() {} phantomBlockCall(); */\n'
            ' void handle() { String note = "phantomStringCall()"; service.loadItems(); } }',
            "loadItems",
        ),
        (
            "php",
            '<?php\n/* function phantomMethod() {} phantomBlockCall(); */\n'
            'function handler() { # phantomCommentCall()\n'
            ' $note = "phantomStringCall()"; $service->loadItems(); }',
            "loadItems",
        ),
    ],
)
def test_fallback_parsers_mask_comments_and_literals_before_building_call_edges(
    language: str, source: str, expected_call: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        treesitter_parser,
        "parse_treesitter_with_status",
        lambda _source, _language: {
            "result": None, "status": "unavailable", "parser": "tree_sitter",
            "fallback_reason": "parser_unavailable", "syntax_error_count": 0,
        },
    )
    index = CodeIndex({"server": {"state_dir": str(tmp_path)}}, repo_tools=None)

    symbols, _refs, edges, report = index._parse_file_content_report(source, language)
    targets = [str(edge.get("dst", "")) for edge in edges if edge.get("kind") == "calls"]

    assert report["status"] == "fallback"
    assert any(target.endswith(expected_call) for target in targets)
    assert not any("phantom" in target or target.endswith(("handler", "handle")) for target in targets)
    assert not any("phantom" in str(symbol.get("name", "")) for symbol in symbols)


def test_fallback_parser_keeps_quoted_dependency_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        treesitter_parser,
        "parse_treesitter_with_status",
        lambda _source, _language: {
            "result": None, "status": "unavailable", "parser": "tree_sitter",
            "fallback_reason": "parser_unavailable", "syntax_error_count": 0,
        },
    )
    index = CodeIndex({"server": {"state_dir": str(tmp_path)}}, repo_tools=None)

    _symbols, _refs, edges, report = index._parse_file_content_report(
        '<?php\nrequire_once "bootstrap.php";\nfunction handler() { helper(); }',
        "php",
    )

    assert report["fallback_used"] is True
    assert any(edge.get("kind") == "imports" and edge.get("dst") == "bootstrap.php" for edge in edges)
    assert any(edge.get("kind") == "calls" and edge.get("dst") == "helper" for edge in edges)


@pytest.mark.parametrize(
    ("source", "following_call"),
    [
        ("if (ready) /[/*]/.test(value); process();", "process"),
        ("if (ready) {} /[/*]/.test(value); processAfterBlock();", "processAfterBlock"),
        ("function f() {}\n/[/*]/.test(value);\nprocessAfterFunction();", "processAfterFunction"),
        ("function handler()\n{\n}\n/[/*]/.test(value);\nprocessAfterMultilineFunction();", "processAfterMultilineFunction"),
    ],
)
def test_fallback_parser_masks_regex_after_if_without_losing_following_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, source: str, following_call: str
) -> None:
    monkeypatch.setattr(
        treesitter_parser,
        "parse_treesitter_with_status",
        lambda _source, _language: {
            "result": None, "status": "unavailable", "parser": "tree_sitter",
            "fallback_reason": "parser_unavailable", "syntax_error_count": 0,
        },
    )
    index = CodeIndex({"server": {"state_dir": str(tmp_path)}}, repo_tools=None)

    _symbols, _refs, edges, _report = index._parse_file_content_report(source, "javascript")
    targets = [str(edge.get("dst", "")) for edge in edges if edge.get("kind") == "calls"]

    assert any(target.endswith("test") for target in targets)
    assert any(target.endswith(following_call) for target in targets)


def test_fallback_parser_does_not_treat_property_if_as_regex_prefix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        treesitter_parser,
        "parse_treesitter_with_status",
        lambda _source, _language: {
            "result": None, "status": "unavailable", "parser": "tree_sitter",
            "fallback_reason": "parser_unavailable", "syntax_error_count": 0,
        },
    )
    index = CodeIndex({"server": {"state_dir": str(tmp_path)}}, repo_tools=None)

    _symbols, _refs, edges, _report = index._parse_file_content_report(
        "object.if(ready) / foo() / process();", "javascript"
    )
    targets = [str(edge.get("dst", "")) for edge in edges if edge.get("kind") == "calls"]

    assert any(target.endswith("foo") for target in targets)
    assert any(target.endswith("process") for target in targets)


@pytest.mark.parametrize("mode", ["single", "batch"])
def test_code_index_reindexes_unchanged_content_after_analyzer_version_change(tmp_path: Path, monkeypatch, mode: str) -> None:
    index, root = _new_index(tmp_path)
    source = root / "src" / "module.py"
    source.parent.mkdir()
    source.write_text("def caller():\n    target()\n", encoding="utf-8")
    content_hash, _lines = index.repo_tools._read_snapshot(source)

    initial = index.update_file(str(root), "src/module.py")
    assert initial["success"] is True
    old_version = code_index_module._PARSER_ANALYZER_VERSION
    new_version = f"{old_version}:test-bump"
    monkeypatch.setattr(code_index_module, "_PARSER_ANALYZER_VERSION", new_version)
    parse_calls = []
    parse_content = index._parse_file_content_report

    def track_parse(text: str, language: str):
        parse_calls.append((text, language))
        return parse_content(text, language)

    monkeypatch.setattr(index, "_parse_file_content_report", track_parse)

    if mode == "single":
        result = index.update_file(str(root), "src/module.py", content_hash)
        assert result["cached"] is False
    else:
        result = index.update_files_batch(str(root), [("src/module.py", content_hash)])
        assert result["files_processed"] == 1

    assert parse_calls == [("def caller():\n    target()", "python")]
    assert index._parse_blob_get_with_report(content_hash, "python") is not None
    with closing(index._connect()) as con:
        row = con.execute(
            "SELECT analyzer_version FROM files WHERE root=? AND path=?",
            (canonical_root(str(root)), "src/module.py"),
        ).fetchone()
    assert row["analyzer_version"] == new_version

    if mode == "single":
        repeated = index.update_file(str(root), "src/module.py", content_hash)
        assert repeated["cached"] is True
    else:
        repeated = index.update_files_batch(str(root), [("src/module.py", content_hash)])
        assert repeated["files_processed"] == 0
        assert repeated["cached"] == 1
    assert len(parse_calls) == 1


def test_code_index_rebuilds_disposable_index_with_obsolete_file_shape(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "module.py"
    source.write_text("def caller():\n    target()\n", encoding="utf-8")
    content_hash, _lines = _SnapshotReader._read_snapshot(source)
    root_key = canonical_root(str(root))
    db_path = state_dir / "code-index.sqlite3"
    with closing(sqlite3.connect(db_path)) as con:
        con.execute(
            "CREATE TABLE files(root TEXT,path TEXT,content_hash TEXT,language TEXT,updated_at REAL,PRIMARY KEY(root,path))"
        )
        con.execute(
            "INSERT INTO files(root,path,content_hash,language,updated_at) VALUES(?,?,?,?,?)",
            (root_key, "module.py", content_hash, "python", 1.0),
        )
        con.commit()

    index = CodeIndex({"server": {"state_dir": str(state_dir)}}, _SnapshotReader())
    with closing(index._connect()) as con:
        file_columns = {str(row[1]) for row in con.execute("PRAGMA table_info(files)")}
        old_row = con.execute(
            "SELECT content_hash FROM files WHERE root=? AND path=?",
            (root_key, "module.py"),
        ).fetchone()

    assert "analyzer_version" in file_columns
    assert old_row is None
    rebuilt = index.update_file(str(root), "module.py")
    assert rebuilt["cached"] is False
    with closing(index._connect()) as con:
        row = con.execute(
            "SELECT content_hash,analyzer_version FROM files WHERE root=? AND path=?",
            (root_key, "module.py"),
        ).fetchone()
    assert row["content_hash"] == content_hash
    assert row["analyzer_version"] == code_index_module._PARSER_ANALYZER_VERSION


def test_preprocessor_queues_unchanged_files_after_analyzer_version_change(tmp_path: Path, monkeypatch) -> None:
    index, root = _new_index(tmp_path)
    source = root / "module.py"
    source.write_text("def caller():\n    target()\n", encoding="utf-8")
    content_hash, _lines = index.repo_tools._read_snapshot(source)
    assert index.update_file(str(root), "module.py")["success"] is True

    config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {"code_index_files_per_step": 8},
    }
    preprocessor = ProjectPreprocessor(
        config, services=None, rag=None, scheduler=None, runtime=None,
        repo_tools=index.repo_tools, code_index=index,
    )
    root_key = canonical_root(str(root))
    generation = 7
    preprocessor._missing_refs_checked_generations.add((root_key, generation))
    preprocessor._code_index_pruned_generations.add((root_key, generation))
    with closing(preprocessor._connect()) as con:
        con.execute(
            "INSERT INTO file_refs(root,path,content_hash,size,generation,updated_at) VALUES(?,?,?,?,?,?)",
            (root_key, "module.py", content_hash, source.stat().st_size, generation, 0.0),
        )
        con.commit()

    old_version = code_index_module._PARSER_ANALYZER_VERSION
    monkeypatch.setattr(code_index_module, "_PARSER_ANALYZER_VERSION", f"{old_version}:preprocess-bump")
    submitted = []
    update_batch = index.update_files_batch

    def track_batch(batch_root: str, items):
        submitted.extend(items)
        return update_batch(batch_root, items)

    monkeypatch.setattr(index, "update_files_batch", track_batch)
    monkeypatch.setattr(preprocessor, "_record_progress", lambda *_args: None)

    assert preprocessor._step_code_index({"root": root_key, "generation": generation}) is True

    assert submitted == [("module.py", content_hash)]
    assert index._parse_blob_get_with_report(content_hash, "python") is not None


def test_uninstall_removes_retired_codegraph_mcp_entry(tmp_path: Path) -> None:
    from tools.uninstall import clean_json

    config_path = tmp_path / "mcp.json"
    config_path.write_text(json.dumps({"mcpServers": {
        "local-ai": {"command": "hub"},
        "serena-local": {"command": "serena"},
        "codegraph-local": {"command": "codegraph"},
        "user-server": {"command": "keep"},
    }}), encoding="utf-8")

    clean_json(config_path)

    servers = json.loads(config_path.read_text(encoding="utf-8"))["mcpServers"]
    assert set(servers) == {"user-server"}


def test_hash_cache_detects_same_size_rewrite_with_restored_mtime(tmp_path: Path) -> None:
    source = tmp_path / "module.py"
    original = b"answer = 1\n"
    updated = b"answer = 2\n"
    source.write_bytes(original)
    before = source.stat()
    tools = RepositoryTools({"server": {"state_dir": str(tmp_path / "state")}})

    original_hash, _original_lines = tools._read_snapshot(source)
    source.write_bytes(updated)
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    after = source.stat()

    assert after.st_size == before.st_size
    assert after.st_mtime_ns == before.st_mtime_ns
    if (
        getattr(after, "st_ctime_ns", 0) != getattr(before, "st_ctime_ns", 0)
        or getattr(after, "st_ino", 0) != getattr(before, "st_ino", 0)
    ):
        pytest.skip("filesystem metadata already invalidates the hash cache")

    updated_hash = tools._hash_file_only(source)
    snapshot_hash, updated_lines = tools._read_snapshot(source)

    assert updated_hash == hashlib.sha256(updated).hexdigest()
    assert updated_hash != original_hash
    assert snapshot_hash == updated_hash
    assert updated_lines == ["answer = 2"]


def test_code_index_update_detects_same_size_rewrite_with_restored_mtime(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "module.py"
    original = b"def old_name(): pass\n"
    updated = b"def new_name(): pass\n"
    source.write_bytes(original)
    before = source.stat()
    config = {"server": {"state_dir": str(tmp_path / "state")}}
    tools = RepositoryTools(config)
    index = CodeIndex(config, tools)

    first = index.update_file(str(root), "module.py")
    source.write_bytes(updated)
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    after = source.stat()

    assert after.st_size == before.st_size
    assert after.st_mtime_ns == before.st_mtime_ns
    if (
        getattr(after, "st_ctime_ns", 0) != getattr(before, "st_ctime_ns", 0)
        or getattr(after, "st_ino", 0) != getattr(before, "st_ino", 0)
    ):
        pytest.skip("filesystem metadata already invalidates the decoded snapshot")

    second = index.update_file(str(root), "module.py")
    with closing(index._connect()) as con:
        row = con.execute(
            "SELECT content_hash FROM files WHERE root=? AND path=?",
            (canonical_root(str(root)), "module.py"),
        ).fetchone()

    assert first["success"] is True
    assert second["success"] is True
    assert second.get("cached") is False
    assert row["content_hash"] == hashlib.sha256(updated).hexdigest()


def test_verified_hash_revalidation_is_not_reported_as_cache_hit_and_refreshes_lru(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools = RepositoryTools({"server": {"state_dir": str(tmp_path / "state")}})
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("value = 1\n", encoding="utf-8")
    second.write_text("value = 2\n", encoding="utf-8")

    def always_revalidate(path: Path, stat: os.stat_result) -> tuple[tuple[int, int, int, int], bool]:
        return (
            int(stat.st_mtime_ns), int(stat.st_size),
            int(getattr(stat, "st_ctime_ns", 0)), int(getattr(stat, "st_ino", 0)),
        ), True

    monkeypatch.setattr(tools, "_cache_identity", always_revalidate)
    tools._hash_only_max_entries = 2
    tools._read_snapshot(first)
    tools._read_snapshot(second)

    expected = hashlib.sha256(first.read_bytes()).hexdigest()
    assert tools._hash_file_only(first) == expected

    stats = tools.snapshot_stats()
    assert stats["hits"] == 0
    assert stats["verified_rehashes"] == 1
    assert list(tools._hash_only_cache) == [str(second), str(first)]


@pytest.mark.skipif(os.name != "nt", reason="Windows ChangeTime cache identity")
def test_windows_change_time_keeps_unchanged_snapshot_on_cache_fast_path(tmp_path: Path) -> None:
    source = tmp_path / "module.py"
    source.write_text("answer = 42\n", encoding="utf-8")
    tools = RepositoryTools({"server": {"state_dir": str(tmp_path / "state")}})

    first = tools._read_snapshot(source)
    second = tools._read_snapshot(source)

    assert second == first
    stats = tools.snapshot_stats()
    assert stats["hits"] == 1
    assert stats["verified_rehashes"] == 0


def test_adaptive_retrieval_skips_optional_backends_when_builtin_confidence_is_high(tmp_path: Path) -> None:
    source = tmp_path / "src" / "controller.py"
    source.parent.mkdir()
    source.write_text("def controller_routing(): pass\n", encoding="utf-8")

    class FakeRepoTools:
        @staticmethod
        def context_pack_paths(root: str, query: str, paths: list[str], *, max_tokens: int, top_k: int) -> dict:
            return {
                "success": True, "root": root, "query": query, "context": "controller routing evidence",
                "evidence": [{
                    "path": "src/controller.py", "start_line": 1, "end_line": 1,
                    "score": 20, "text": "def controller_routing(): pass",
                }],
                "scanned_files": 1,
            }

    class FakeDeterministic:
        @staticmethod
        def related_paths(_root: str, _query: str, *, limit: int, result: dict) -> list[str]:
            return ["src/controller.py"]

    class FakeCodeIndex:
        @staticmethod
        def related_paths(_root: str, _query: str, *, limit: int) -> list[str]:
            return ["src/controller.py"]

    class FakeExternal:
        calls = 0

        @classmethod
        def query(cls, *_args, **_kwargs) -> dict:
            cls.calls += 1
            return {"success": True, "results": []}

    class FakeRag:
        calls = 0

        @classmethod
        def search(cls, *_args, **_kwargs) -> dict:
            cls.calls += 1
            return {"success": True, "results": []}

    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {
        "search": {"context_backend_timeout_seconds": 1, "context_rag_timeout_seconds": 1},
        "features": {"rag": True}, "preprocessing": {},
        "deterministic": {"context_confidence": 0.8},
    }
    services.learner = None
    services.repo_tools = FakeRepoTools()
    services.deterministic = FakeDeterministic()
    services.code_index = FakeCodeIndex()
    services.preprocessor = None
    services.external_tools = FakeExternal()
    services.evidence_store = None
    services.rag = FakeRag()
    services.deterministic_query = lambda *_args, **_kwargs: {
        "success": True, "confidence": 0.96, "facts": [{"path": "src/controller.py"}],
    }

    result = services._hybrid_context_uncached(
        str(tmp_path), "controller routing", "tenant", "workspace-1", 400, quality_first=True
    )

    states = result["retrieval"]["backend_states"]
    assert states["serena"] == "skipped"
    assert states["rag"] == "skipped"
    assert result["retrieval"]["backend_selection"]["decision"] == "builtin_confident"
    assert result["retrieval"]["backend_selection"]["confidence"] >= 0.8
    assert FakeExternal.calls == 0
    assert FakeRag.calls == 0


def test_adaptive_retrieval_skips_optional_backends_when_deadline_is_exhausted(tmp_path: Path) -> None:
    class FakeRepoTools:
        @staticmethod
        def context_pack_paths(root: str, query: str, paths: list[str], *, max_tokens: int, top_k: int) -> dict:
            return {
                "success": True, "root": root, "query": query, "context": "local evidence",
                "evidence": [{"path": "src/local.py", "start_line": 1, "end_line": 1, "text": "local"}],
                "scanned_files": 1,
            }

    class SlowDeterministic:
        @staticmethod
        def related_paths(_root: str, _query: str, *, limit: int) -> list[str]:
            time.sleep(0.08)
            return ["src/local.py"]

    class FakeExternal:
        calls = 0

        @classmethod
        def query(cls, *_args, **_kwargs) -> dict:
            cls.calls += 1
            return {"success": True, "results": []}

    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {
        "search": {"context_backend_timeout_seconds": 0.05, "context_rag_timeout_seconds": 0.05},
        "features": {"rag": False}, "preprocessing": {},
    }
    services.learner = None
    services.repo_tools = FakeRepoTools()
    services.deterministic = SlowDeterministic()
    services.code_index = None
    services.preprocessor = None
    services.external_tools = FakeExternal()
    services.evidence_store = None
    services.rag = None

    result = services._hybrid_context_uncached(
        str(tmp_path), "find local evidence", "tenant", None, 400, quality_first=True
    )

    assert result["retrieval"]["backend_states"]["serena"] == "skipped"
    assert result["retrieval"]["backend_selection"]["decision"] == "deadline_exhausted"
    assert FakeExternal.calls == 0


def test_adaptive_retrieval_passes_remaining_deadline_to_serena(tmp_path: Path) -> None:
    class FakeRepoTools:
        @staticmethod
        def search_terms(_query: str) -> list[str]:
            return ["local"]

        @staticmethod
        def context_pack_paths(root: str, query: str, paths: list[str], *, max_tokens: int, top_k: int) -> dict:
            return {
                "success": True, "root": root, "query": query, "context": "local evidence",
                "evidence": [{"path": "src/local.py", "start_line": 1, "end_line": 1, "text": "local"}],
                "scanned_files": 1,
            }

    class SlowDeterministic:
        @staticmethod
        def related_paths(_root: str, _query: str, *, limit: int) -> list[str]:
            time.sleep(0.03)
            return ["src/local.py"]

    class TimedExternal:
        received_timeout = 0.0

        @classmethod
        def query(cls, _root: str, _query: str, *, backend: str, action: str, limit: int, timeout: float) -> dict:
            cls.received_timeout = timeout
            return {"success": True, "results": []}

    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {
        "search": {"context_backend_timeout_seconds": 0.3, "context_rag_timeout_seconds": 0.3},
        "features": {"rag": False}, "preprocessing": {},
    }
    services.learner = None
    services.repo_tools = FakeRepoTools()
    services.deterministic = SlowDeterministic()
    services.code_index = None
    services.preprocessor = None
    services.external_tools = TimedExternal()
    services.evidence_store = None
    services.rag = None

    result = services._hybrid_context_uncached(
        str(tmp_path), "find local evidence", "tenant", None, 400, quality_first=True
    )

    assert result["retrieval"]["backend_selection"]["decision"] == "optional_backends_selected"
    assert 0.0 < TimedExternal.received_timeout < 0.3

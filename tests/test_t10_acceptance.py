from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub import code_index as code_index_module
from local_ai_hub import deterministic as deterministic_module
from local_ai_hub import repo_tools as repo_tools_module
from local_ai_hub import services as services_module
from local_ai_hub import treesitter_parser
from local_ai_hub.code_index import CodeIndex
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.process_utils import canonical_root
from local_ai_hub.repo_tools import FileTooLargeError, RepositoryTools
from local_ai_hub.services import LocalAIServices
from local_ai_hub.treesitter_parser import is_treesitter_available, parse_treesitter

class _SnapshotReader:
    ignore_dirs: set[str] = set()
    max_file_bytes: int = 2_000_000

    @staticmethod
    def _read_snapshot(
        path: Path,
        *,
        stat: os.stat_result | None = None,
        force: bool = False,
        max_bytes: int | None = None,
    ) -> tuple[str, list[str]]:
        with Path(path).open("rb") as stream:
            source = stream.read() if max_bytes is None else stream.read(max_bytes + 1)
        if max_bytes is not None and len(source) > max_bytes:
            raise FileTooLargeError(f"{path} exceeds {max_bytes} bytes")
        return hashlib.sha256(source).hexdigest(), source.decode("utf-8", errors="replace").splitlines()

def _new_index(tmp_path: Path) -> tuple[CodeIndex, Path]:
    root = tmp_path / "repo"
    root.mkdir()
    index = CodeIndex({"server": {"state_dir": str(tmp_path / "state")}}, _SnapshotReader())
    return index, root

def test_code_index_batch_parser_avoids_shared_parser_queueing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    index, root = _new_index(tmp_path)
    items = []
    for number in range(8):
        relative = f"src/module_{number}.py"
        source = root / relative
        source.parent.mkdir(exist_ok=True)
        source.write_text(f"def caller_{number}(): return shared_target()\n", encoding="utf-8")
        items.append(relative)

    active = 0
    max_active = 0
    lock = threading.Lock()
    parse = index._parse_file_content_report

    def observe_parse(source: str, language: str):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.005)
            return parse(source, language)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(index, "_parse_file_content_report", observe_parse)
    result = index.update_files_batch(str(root), items)

    assert result["success"] is True
    assert max_active == 1

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
    assert "result_support" in result["confidence_basis"]
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


@pytest.mark.parametrize("mutation", ["update_file", "update_files_batch", "prune"])
def test_code_index_query_cache_invalidates_after_index_mutation(tmp_path: Path, mutation: str) -> None:
    index, root = _new_index(tmp_path)
    source = root / "src" / "module.py"
    source.parent.mkdir()
    relative = "src/module.py"
    source.write_text("def ObsoleteNeedle(): pass\n", encoding="utf-8")
    assert index.update_files_batch(str(root), [relative])["success"] is True
    assert index.query(str(root), "ObsoleteNeedle")["symbols"]

    if mutation == "update_file":
        source.write_text("def FreshFunction(): pass\n", encoding="utf-8")
        assert index.update_file(str(root), relative)["success"] is True
    elif mutation == "update_files_batch":
        source.write_text("def FreshFunction(): pass\n", encoding="utf-8")
        assert index.update_files_batch(str(root), [relative])["success"] is True
    else:
        assert index.prune(str(root), [])["pruned"] == 1

    assert index.query(str(root), "ObsoleteNeedle")["symbols"] == []


def test_code_index_query_cache_invalidates_across_instances(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    root = tmp_path / "repo"
    root.mkdir()
    reader = _SnapshotReader()
    reader_index = CodeIndex({"server": {"state_dir": str(state_dir)}}, reader)
    writer_index = CodeIndex({"server": {"state_dir": str(state_dir)}}, reader)
    source = root / "module.py"
    source.write_text("def ObsoleteNeedle(): pass\n", encoding="utf-8")
    assert writer_index.update_file(str(root), "module.py")["success"] is True
    assert reader_index.query(str(root), "ObsoleteNeedle")["symbols"]

    source.write_text("def FreshFunction(): pass\n", encoding="utf-8")
    assert writer_index.update_file(str(root), "module.py")["success"] is True

    assert reader_index.query(str(root), "ObsoleteNeedle")["symbols"] == []


def test_batch_update_uses_bulk_parse_cache_lookup(tmp_path: Path, monkeypatch) -> None:
    writer, original_root = _new_index(tmp_path)
    original = original_root / "module.py"
    original.write_text("def SharedBlobNeedle(): pass\n", encoding="utf-8")
    content_hash, _lines = writer.repo_tools._read_snapshot(original)
    assert writer.update_file(str(original_root), "module.py")["success"] is True

    mirror = tmp_path / "mirror"
    mirror.mkdir()
    (mirror / "module.py").write_text(original.read_text(encoding="utf-8"), encoding="utf-8")
    index = CodeIndex({"server": {"state_dir": str(tmp_path / "state")}}, _SnapshotReader())
    individual_lookups = 0
    original_lookup = index._parse_blob_get_with_report

    def count_individual_lookup(content_hash: str, language: str):
        nonlocal individual_lookups
        individual_lookups += 1
        return original_lookup(content_hash, language)

    monkeypatch.setattr(index, "_parse_blob_get_with_report", count_individual_lookup)
    parse_blob_selects = []
    original_connect = index._connect

    def track_parse_blob_selects():
        connection = original_connect()
        connection.set_trace_callback(
            lambda statement: parse_blob_selects.append(statement)
            if statement.lstrip().upper().startswith("SELECT") and "FROM PARSE_BLOBS" in statement.upper()
            else None
        )
        return connection

    monkeypatch.setattr(index, "_connect", track_parse_blob_selects)
    result = index.update_files_batch(str(mirror), [("module.py", content_hash)])

    assert result["success"] is True
    assert result["files_processed"] == 1
    assert result["parse_blob_hits"] == 1
    assert individual_lookups == 0
    assert len(parse_blob_selects) == 1
    assert index.query(str(mirror), "SharedBlobNeedle")["symbols"]


def test_index_update_replaces_import_and_call_dependencies(tmp_path: Path) -> None:
    index, root = _new_index(tmp_path)
    api = root / "api.py"
    consumer = root / "consumer.py"
    api.write_text("def SharedNeedle(): pass\n", encoding="utf-8")
    consumer.write_text("from api import SharedNeedle\ndef consume():\n    SharedNeedle()\n", encoding="utf-8")
    assert index.update_file(str(root), "api.py")["success"] is True
    assert index.update_file(str(root), "consumer.py")["success"] is True

    before = index.impact(str(root), ["api.py"])
    assert any(item["path"] == "consumer.py" for item in before["likely_dependents"])
    assert index.find_callers(str(root), "SharedNeedle")["callers"]

    consumer.write_text("def consume():\n    unrelatedAction()\n", encoding="utf-8")
    assert index.update_file(str(root), "consumer.py")["success"] is True

    after = index.impact(str(root), ["api.py"])
    assert all(item["path"] != "consumer.py" for item in after["likely_dependents"])
    assert index.find_callers(str(root), "SharedNeedle")["callers"] == []

def test_code_index_reports_syntax_failure_and_parser_fallback_outcomes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not is_treesitter_available("python"):
        pytest.skip("Tree-sitter parser unavailable for Python")
    parse_with_status = treesitter_parser.parse_treesitter_with_status

    def parser_with_java_unavailable(source: str, language: str) -> dict[str, object]:
        if language == "java":
            return {
                "result": None, "status": "unavailable", "parser": "tree_sitter",
                "fallback_reason": "parser_unavailable", "syntax_error_count": 0,
            }
        return parse_with_status(source, language)

    monkeypatch.setattr(treesitter_parser, "parse_treesitter_with_status", parser_with_java_unavailable)
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
            "cpp",
            'class Handler { public: void run() { // phantomCommentCall()\n'
            ' const char* note = "phantomStringCall()"; service.realCall(); } };',
            "realCall",
        ),
        (
            "typescript",
            '/* function phantomFunction() {} phantomBlockCall(); */\n'
            'function handler() { // phantomCommentCall()\n'
            ' const sep = /[/*]/; const note = `phantomTemplateCall()`; return service.loadItems(); }',
            "loadItems",
        ),
        (
            "tsx",
            'const handler = () => { // phantomCommentCall()\n'
            ' const note = "phantomStringCall()"; return service.loadItems(); };\n'
            'const view = <div />;',
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


def test_fallback_parser_masks_regex_literals_for_tsx(
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
    source = "function caller() { if (ready) /fakeCall()/.test(value); realCall(); }"

    _symbols, _refs, edges, _report = index._parse_file_content_report(source, "tsx")
    targets = [str(edge.get("dst", "")) for edge in edges if edge.get("kind") == "calls"]

    assert any(target.endswith("realCall") for target in targets)
    assert not any(target.endswith("fakeCall") for target in targets)


def test_fallback_parser_handles_regex_inside_tsx_template_interpolation(
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
    source = "function caller() { const view = `text ${/fakeCall()/.test(value) ? realCall() : false}`; }"

    _symbols, _refs, edges, _report = index._parse_file_content_report(source, "tsx")
    targets = [str(edge.get("dst", "")) for edge in edges if edge.get("kind") == "calls"]

    assert any(target.endswith("realCall") for target in targets)
    assert not any(target.endswith("fakeCall") for target in targets)


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


def test_code_index_impact_returns_all_dependents_above_legacy_ten_thousand_cap(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "changed.py").write_text("def shared_target():\n    return 1\n", encoding="utf-8")
    index = CodeIndex({"server": {"state_dir": str(tmp_path / "state")}}, _SnapshotReader())
    indexed_source = index.update_file(str(root), "changed.py")
    assert indexed_source["success"] is True

    root_key = canonical_root(str(root))
    dependent_count = 10_001
    with closing(index._connect()) as con:
        con.executemany(
            "INSERT INTO files(root,path,content_hash,language,analyzer_version,updated_at) VALUES(?,?,?,?,?,?)",
            ((root_key, f"src/dependent_{i:05}.py", "fixture", "python", "fixture", 1.0) for i in range(dependent_count)),
        )
        con.executemany(
            "INSERT INTO refs(root,path,name,line,kind) VALUES(?,?,?,?,?)",
            ((root_key, f"src/dependent_{i:05}.py", "shared_target", 1, "call") for i in range(dependent_count)),
        )
        con.commit()

    result = index.impact(str(root), ["changed.py"], max_dependents=dependent_count)

    assert len(result["likely_dependents"]) == dependent_count
    assert result["coverage"]["dependent_candidate_count_exact"] is True
    assert result["coverage"]["dependent_returned_count"] == dependent_count
    assert result["coverage"]["complete"] is True
    assert result["truncated"] is False


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


def test_uninstall_preserves_standalone_codegraph_mcp_entry(tmp_path: Path) -> None:
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
    assert set(servers) == {"codegraph-local", "user-server"}


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


def test_hash_cache_rechecks_bytes_when_stat_identity_is_unchanged(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "module.py"
    original = b"answer = 1\n"
    updated = b"answer = 2\n"
    source.write_bytes(original)
    before = source.stat()
    tools = RepositoryTools({"server": {"state_dir": str(tmp_path / "state")}})
    stable_identity = (before.st_mtime_ns, before.st_size, 17, 23)
    monkeypatch.setattr(tools, "_cache_identity", lambda _path, _stat: (stable_identity, True))

    original_hash, _original_lines = tools._read_snapshot(source)
    source.write_bytes(updated)
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))

    updated_hash, updated_lines = tools._read_snapshot(source)

    assert updated_hash == hashlib.sha256(updated).hexdigest()
    assert updated_hash != original_hash
    assert updated_lines == ["answer = 2"]
    assert tools.snapshot_verified_rehashes == 1


def test_hash_only_revalidation_counts_same_stat_content_change(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "module.py"
    original = b"answer = 1\n"
    updated = b"answer = 2\n"
    source.write_bytes(original)
    before = source.stat()
    tools = RepositoryTools({"server": {"state_dir": str(tmp_path / "state")}})
    stable_identity = (before.st_mtime_ns, before.st_size, 17, 23)
    monkeypatch.setattr(tools, "_cache_identity", lambda _path, _stat: (stable_identity, True))

    original_hash = tools._hash_file_only(source)
    source.write_bytes(updated)
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    updated_hash = tools._hash_file_only(source)

    assert updated_hash != original_hash
    assert tools.snapshot_verified_rehashes == 1


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


def test_batch_reindex_detects_same_stat_rewrite_and_replaces_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "consumer.py"
    original = b"from legacy import old_call\ndef consume(): old_call()\n"
    updated = b"from modern import new_call\ndef consume(): new_call()\n"
    assert len(original) == len(updated)
    source.write_bytes(original)
    before = source.stat()
    config = {"server": {"state_dir": str(tmp_path / "state")}}
    tools = RepositoryTools(config)
    stable_identity = (before.st_mtime_ns, before.st_size, 17, 23)
    monkeypatch.setattr(tools, "_cache_identity", lambda _path, _stat: (stable_identity, True))
    index = CodeIndex(config, tools)

    first_inventory = tools.file_inventory(str(root), include_hashes=True)
    first_items = [(item["path"], item["sha256"]) for item in first_inventory["files"]]
    first = index.update_files_batch(str(root), index.files_needing_reindex(str(root), first_items))
    first_hash = first_items[0][1]
    assert first["success"] is True
    assert index.find_callers(str(root), "old_call")["callers"]

    source.write_bytes(updated)
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    after = source.stat()
    assert after.st_size == before.st_size
    assert after.st_mtime_ns == before.st_mtime_ns
    updated_inventory = tools.file_inventory(str(root), include_hashes=True)
    updated_items = [(item["path"], item["sha256"]) for item in updated_inventory["files"]]
    updated_hash = updated_items[0][1]
    changed_items = index.files_needing_reindex(str(root), updated_items)

    assert updated_hash != first_hash
    assert changed_items == [("consumer.py", updated_hash)]
    second = index.update_files_batch(str(root), changed_items)
    assert second["success"] is True
    assert second["files_processed"] == 1
    assert index.find_callers(str(root), "old_call")["callers"] == []
    assert index.find_callers(str(root), "new_call")["callers"]
    with closing(index._connect()) as con:
        import_targets = {
            str(row[0]) for row in con.execute(
                "SELECT dst FROM edges WHERE root=? AND path=? AND kind='imports'",
                (canonical_root(str(root)), "consumer.py"),
            ).fetchall()
        }
    assert import_targets == {"modern", "modern.new_call"}


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


def test_windows_hash_cold_read_defers_change_time_and_revalidates_before_fast_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "module.py"
    original = b"value = 1\n"
    updated = b"value = 2\n"
    source.write_bytes(original)
    original_stat = source.stat()
    real_path_stat = Path.stat
    tools = RepositoryTools({"server": {"state_dir": str(tmp_path / "state")}})
    change_time = [100]
    change_time_calls: list[Path] = []

    def stable_stat(path: Path, *args, **kwargs):
        if path == source:
            return original_stat
        return real_path_stat(path, *args, **kwargs)

    def fake_change_time(path: Path) -> int:
        change_time_calls.append(path)
        return change_time[0]

    monkeypatch.setattr(repo_tools_module.os, "name", "nt")
    monkeypatch.setattr(Path, "stat", stable_stat)
    monkeypatch.setattr(tools, "_windows_change_time", fake_change_time)

    original_hash = tools._hash_file_only(source)
    assert change_time_calls == []

    source.write_bytes(updated)
    os.utime(source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    change_time[0] = 200
    updated_hash = tools._hash_file_only(source)

    assert updated_hash == hashlib.sha256(updated).hexdigest()
    assert updated_hash != original_hash
    assert change_time_calls == [source]
    assert tools.snapshot_verified_rehashes == 1

    assert tools._hash_file_only(source) == updated_hash
    assert change_time_calls == [source, source]
    assert tools.snapshot_verified_rehashes == 1


def test_windows_snapshot_cold_read_defers_change_time_and_revalidates_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "module.py"
    original = b"def old_name(): pass\n"
    updated = b"def new_name(): pass\n"
    assert len(original) == len(updated)
    source.write_bytes(original)
    original_stat = source.stat()
    real_path_stat = Path.stat
    tools = RepositoryTools({"server": {"state_dir": str(tmp_path / "state")}})
    change_time = [100]
    change_time_calls: list[Path] = []

    def stable_stat(path: Path, *args, **kwargs):
        if path == source:
            return original_stat
        return real_path_stat(path, *args, **kwargs)

    def fake_change_time(path: Path) -> int:
        change_time_calls.append(path)
        return change_time[0]

    monkeypatch.setattr(repo_tools_module.os, "name", "nt")
    monkeypatch.setattr(Path, "stat", stable_stat)
    monkeypatch.setattr(tools, "_windows_change_time", fake_change_time)

    original_hash, original_lines = tools._read_snapshot(source)
    assert original_lines == ["def old_name(): pass"]
    assert change_time_calls == [source]
    assert len(tools._snapshots[str(source)]) == 7

    assert tools._read_snapshot(source) == (original_hash, original_lines)
    assert change_time_calls == [source, source]
    assert tools.snapshot_hits == 1
    assert tools.snapshot_verified_rehashes == 0

    source.write_bytes(updated)
    os.utime(source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    change_time[0] = 200
    updated_hash, updated_lines = tools._read_snapshot(source)

    assert updated_hash == hashlib.sha256(updated).hexdigest()
    assert updated_hash != original_hash
    assert updated_lines == ["def new_name(): pass"]
    assert change_time_calls == [source, source, source]
    assert tools.snapshot_verified_rehashes == 0

    assert tools._read_snapshot(source) == (updated_hash, updated_lines)
    assert change_time_calls == [source, source, source, source]
    assert tools.snapshot_hits == 2


def test_file_inventory_reuses_stat_for_snapshot_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "module.py"
    source.write_text("answer = 42\n", encoding="utf-8")
    tools = RepositoryTools({"server": {"state_dir": str(tmp_path / "state")}})
    original_read = tools._read_snapshot
    original_stat = Path.stat
    supplied_stats: list[os.stat_result | None] = []
    stat_calls: list[Path] = []

    def capture_stat(path: Path, *, stat: os.stat_result | None = None) -> tuple[str, list[str]]:
        supplied_stats.append(stat)
        if stat is None:
            return original_read(path)
        return original_read(path, stat=stat)

    def count_stat(path: Path, *args, **kwargs) -> os.stat_result:
        if path == source:
            stat_calls.append(path)
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(tools, "_read_snapshot", capture_stat)
    monkeypatch.setattr(Path, "stat", count_stat)

    inventory = tools.file_inventory(str(tmp_path), include_hashes=True)

    assert inventory["file_count"] == 1
    assert len(supplied_stats) == 1
    assert supplied_stats[0] is not None
    assert len(stat_calls) == 1


def test_file_inventory_refreshes_stale_stat_before_snapshot_cache_hit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "module.py"
    source.write_text("answer = 42\n", encoding="utf-8")
    tools = RepositoryTools({"server": {"state_dir": str(tmp_path / "state")}})
    monkeypatch.setattr(
        tools,
        "_cache_identity",
        lambda _path, stat: (tools._stat_cache_identity(stat), False),
    )
    original_read = tools._read_snapshot

    def read_with_posix_identity(path: Path, *, stat: os.stat_result | None = None) -> tuple[str, list[str]]:
        with monkeypatch.context() as context:
            context.setattr(repo_tools_module.os, "name", "posix")
            return original_read(path, stat=stat)

    original_hash, _lines = tools._read_snapshot(source)
    stale_stat = source.stat()
    source.write_text("answer = 43\n", encoding="utf-8")
    os.utime(source, ns=(stale_stat.st_atime_ns, stale_stat.st_mtime_ns + 2_000_000_000))
    current_hash = hashlib.sha256(source.read_bytes()).hexdigest()

    monkeypatch.setattr(tools, "_root", lambda _root: tmp_path)
    monkeypatch.setattr(tools, "_read_snapshot", read_with_posix_identity)
    monkeypatch.setattr(tools, "_iter_files_with_stat", lambda _root: iter([(source, stale_stat)]))

    inventory = tools.file_inventory(str(tmp_path), include_hashes=True)

    assert current_hash != original_hash
    assert inventory["files"][0]["sha256"] == current_hash


def test_file_inventory_windows_change_time_rejects_stale_enumeration_stat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "module.py"
    source.write_text("answer = 42\n", encoding="utf-8")
    tools = RepositoryTools({"server": {"state_dir": str(tmp_path / "state")}})
    change_time = [1]
    monkeypatch.setattr(tools, "_windows_change_time", lambda _path: change_time[0])
    original_read = tools._read_snapshot

    def read_with_windows_identity(path: Path, *, stat: os.stat_result | None = None) -> tuple[str, list[str]]:
        with monkeypatch.context() as context:
            context.setattr(repo_tools_module.os, "name", "nt")
            return original_read(path, stat=stat)

    original_hash, _lines = read_with_windows_identity(source)
    stale_stat = source.stat()
    source.write_text("answer = 43\n", encoding="utf-8")
    os.utime(source, ns=(stale_stat.st_atime_ns, stale_stat.st_mtime_ns))
    change_time[0] = 2
    current_hash = hashlib.sha256(source.read_bytes()).hexdigest()

    monkeypatch.setattr(tools, "_root", lambda _root: tmp_path)
    monkeypatch.setattr(tools, "_read_snapshot", read_with_windows_identity)
    monkeypatch.setattr(tools, "_iter_files_with_stat", lambda _root: iter([(source, stale_stat)]))

    inventory = tools.file_inventory(str(tmp_path), include_hashes=True)

    assert current_hash != original_hash
    assert inventory["files"][0]["sha256"] == current_hash


@pytest.mark.skipif(os.name != "nt", reason="Windows ChangeTime API bindings")
def test_windows_change_time_reuses_native_api_bindings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import ctypes

    cache = getattr(repo_tools_module, "_windows_file_api", None)
    if cache is not None:
        cache.cache_clear()
    original_loader = ctypes.WinDLL
    load_count = 0

    def tracked_loader(*args, **kwargs):
        nonlocal load_count
        load_count += 1
        return original_loader(*args, **kwargs)

    monkeypatch.setattr(ctypes, "WinDLL", tracked_loader)
    try:
        for number in range(2):
            source = tmp_path / f"module_{number}.py"
            source.write_text(f"answer = {number}\n", encoding="utf-8")
            assert RepositoryTools._windows_change_time(source) is not None
        assert load_count == 1
    finally:
        if cache is not None:
            cache.cache_clear()


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
        str(tmp_path), "controller routing", workspace="workspace-1", max_tokens=400, quality_first=True
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
        str(tmp_path), "find local evidence", workspace=None, max_tokens=400, quality_first=True
    )

    assert result["retrieval"]["backend_states"]["serena"] == "skipped"
    assert result["retrieval"]["backend_selection"]["decision"] == "deadline_exhausted"
    assert FakeExternal.calls == 0


def test_adaptive_retrieval_passes_remaining_deadline_to_serena(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    clock = {"now": 10.0}

    def advancing_clock() -> float:
        current = clock["now"]
        clock["now"] += 0.01
        return current

    monkeypatch.setattr(services_module.time, "perf_counter", advancing_clock)

    result = services._hybrid_context_uncached(
        str(tmp_path), "find local evidence", workspace=None, max_tokens=400, quality_first=True
    )

    assert result["retrieval"]["backend_selection"]["decision"] == "optional_backends_selected"
    assert 0.0 < TimedExternal.received_timeout < 0.3


@pytest.mark.parametrize(
    ("language", "source", "expected_calls", "literal_call"),
    [
        (
            "typescript",
            "function render(value) {\n"
            '  const label = `literal phantomTemplateCall() ${formatMessage("phantomNestedCall()")}`;\n'
            "  return label;\n"
            "}",
            ("formatMessage",),
            "phantomTemplateCall",
        ),
        (
            "javascript",
            "function render(value) {\n"
            '  const label = `literal phantomTemplateCall() ${formatMessage("phantomNestedCall()")}`;\n'
            "  return label;\n"
            "}",
            ("formatMessage",),
            "phantomTemplateCall",
        ),
        (
            "csharp",
            'class Renderer {\n'
            '    void Render() {\n'
            '        var label = $"literal phantomInterpolatedCall() {FormatMessage("phantomNestedCall()")}";\n'
            '    }\n'
            '}',
            ("FormatMessage",),
            "phantomInterpolatedCall",
        ),
        (
            "csharp",
            'class Renderer {\n'
            '    void Render() {\n'
            '        var label = $@"literal phantomInterpolatedCall() {FormatMessage(value)}";\n'
            '    }\n'
            '}',
            ("FormatMessage",),
            "phantomInterpolatedCall",
        ),
        (
            "csharp",
            'class Renderer {\n'
            '    void Render() {\n'
            '        var label = $"outer {FormatMessage($"inner {BuildValue()}")}";\n'
            '    }\n'
            '}',
            ("FormatMessage", "BuildValue"),
            "phantomInterpolatedCall",
        ),
        (
            "csharp",
            'class Renderer {\n'
            '    void Render() {\n'
            '        var label = $$"""literal {phantomInterpolatedCall()} {{FormatMessage("phantomNestedCall()")}}""";\n'
            '    }\n'
            '}',
            ("FormatMessage",),
            "phantomInterpolatedCall",
        ),
        (
            "csharp",
            'class Renderer {\n'
            '    void Render() {\n'
            '        var label = $$$"""literal {phantomInterpolatedCall()} {{{FormatMessage(value)}}}""";\n'
            '    }\n'
            '}',
            ("FormatMessage",),
            "phantomInterpolatedCall",
        ),
    ],
)
def test_fallback_parser_keeps_interpolated_expression_calls(
    language: str,
    source: str,
    expected_calls: tuple[str, ...],
    literal_call: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
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

    _symbols, _refs, edges, report = index._parse_file_content_report(source, language)
    calls = [str(edge.get("dst", "")) for edge in edges if edge.get("kind") == "calls"]

    assert report["status"] == "fallback"
    assert all(any(call.endswith(expected_call) for call in calls) for expected_call in expected_calls)
    assert not any(call.endswith(literal_call) for call in calls)
    assert not any(call.endswith("phantomNestedCall") for call in calls)


@pytest.mark.parametrize(
    ("language", "filename", "source", "caller", "callee"),
    [
        (
            "csharp",
            "Renderer.cs",
            "class Renderer {\n    void Render() {\n        SaveResult();\n    }\n}",
            "Render",
            "SaveResult",
        ),
        (
            "csharp",
            "Renderer.cs",
            "class Renderer\n{\n    void Render()\n    {\n        SaveResult();\n    }\n}",
            "Render",
            "SaveResult",
        ),
        (
            "csharp",
            "Foo.cs",
            "class Foo {\n    void M(Action Foo) {\n        Foo();\n    }\n}",
            "M",
            "Foo",
        ),
        (
            "typescript",
            "renderer.ts",
            "function render() {\n    saveResult();\n}",
            "render",
            "saveResult",
        ),
    ],
)
def test_fallback_call_edges_keep_enclosing_function_scope(
    language: str,
    filename: str,
    source: str,
    caller: str,
    callee: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        treesitter_parser,
        "parse_treesitter_with_status",
        lambda _source, _language: {
            "result": None, "status": "unavailable", "parser": "tree_sitter",
            "fallback_reason": "parser_unavailable", "syntax_error_count": 0,
        },
    )
    index, root = _new_index(tmp_path)
    (root / filename).write_text(source, encoding="utf-8")

    assert index._lang(filename) == language
    update = index.update_file(str(root), filename)
    result = index.find_callees(str(root), caller)

    assert update["parse_outcome"]["fallback_used"] is True
    assert any(edge["caller"].endswith(caller) and edge["callee"].endswith(callee) for edge in result["callees"])


@pytest.mark.parametrize(
    "source",
    [
        "const project = () => loadData();\nif (ready) {\n    notify();\n}\n",
        "const project = () => loadData(); notify();\n",
        "const project = () => {\n    loadData();\n}\nnotify();\n",
        "const project = () =>\n    loadData();\nnotify();\n",
        "const project = () =>\n    loadData(); notify();\n",
        "const project = () =>\n    loadData()\n        .then(renderProject()); notify();\n",
        "const project = () => {\n    loadData();\n}; notify();\n",
        "function project() { loadData(); } notify();\n",
        "function project() {\n    loadData();\n} notify();\n",
        "function project() {} obj?.notify();\n",
        "function project() { loadData(); const child = () => childLoad(); } notify();\n",
    ],
)
def test_fallback_arrow_scope_does_not_capture_later_top_level_calls(
    source: str, monkeypatch, tmp_path: Path,
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
    _symbols, _refs, edges, report = index._parse_file_content_report(source, "typescript")

    assert report["fallback_used"] is True
    notify_edge = next(edge for edge in edges if edge.get("dst") == "notify")
    assert notify_edge["src"] == "<module>"
    if "loadData()" in source:
        assert any(edge.get("dst") == "loadData" and edge.get("src") == "project" for edge in edges)
    if ".then(" in source:
        assert any(edge.get("dst") == "then" and edge.get("src") == "project" for edge in edges)
        assert any(edge.get("dst") == "renderProject" and edge.get("src") == "project" for edge in edges)


def test_fallback_nested_inline_arrow_gets_own_call_scope(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        treesitter_parser,
        "parse_treesitter_with_status",
        lambda _source, _language: {
            "result": None, "status": "unavailable", "parser": "tree_sitter",
            "fallback_reason": "parser_unavailable", "syntax_error_count": 0,
        },
    )
    index = CodeIndex({"server": {"state_dir": str(tmp_path)}}, repo_tools=None)
    source = "function project() { loadData(); const child = () => childLoad(); }"

    _symbols, _refs, edges, report = index._parse_file_content_report(source, "typescript")

    assert report["fallback_used"] is True
    assert any(edge["src"].endswith("project") and edge["dst"] == "loadData" for edge in edges)
    assert any(edge["src"].endswith("child") and edge["dst"] == "childLoad" for edge in edges)
    assert not any(edge["src"].endswith("project") and edge["dst"] == "childLoad" for edge in edges)


def test_fallback_nested_inline_block_arrow_gets_own_call_scope(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        treesitter_parser,
        "parse_treesitter_with_status",
        lambda _source, _language: {
            "result": None, "status": "unavailable", "parser": "tree_sitter",
            "fallback_reason": "parser_unavailable", "syntax_error_count": 0,
        },
    )
    index = CodeIndex({"server": {"state_dir": str(tmp_path)}}, repo_tools=None)
    source = "function project() { const child = () => {\n    childLoad();\n}; }"

    _symbols, _refs, edges, report = index._parse_file_content_report(source, "typescript")

    assert report["fallback_used"] is True
    assert any(edge["src"].endswith("child") and edge["dst"] == "childLoad" for edge in edges)
    assert not any(edge["src"].endswith("project") and edge["dst"] == "childLoad" for edge in edges)


def test_fallback_arrow_scope_ignores_closing_brace_in_string(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        treesitter_parser,
        "parse_treesitter_with_status",
        lambda _source, _language: {
            "result": None, "status": "unavailable", "parser": "tree_sitter",
            "fallback_reason": "parser_unavailable", "syntax_error_count": 0,
        },
    )
    index = CodeIndex({"server": {"state_dir": str(tmp_path)}}, repo_tools=None)
    source = 'const project = () => {\n    const brace = "}";\n    innerCall();\n};'

    _symbols, _refs, edges, report = index._parse_file_content_report(source, "typescript")

    assert report["fallback_used"] is True
    call = next(edge for edge in edges if edge.get("dst") == "innerCall")
    assert call["src"] == "project"


def test_csharp_multiline_expression_body_keeps_call_in_method(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        treesitter_parser,
        "parse_treesitter_with_status",
        lambda _source, _language: {
            "result": None, "status": "unavailable", "parser": "tree_sitter",
            "fallback_reason": "parser_unavailable", "syntax_error_count": 0,
        },
    )
    index = CodeIndex({"server": {"state_dir": str(tmp_path)}}, repo_tools=None)
    source = "class Example {\n    int M() =>\n        SaveResult();\n}\n"

    symbols, _refs, edges, report = index._parse_file_content_report(source, "csharp")

    assert report["fallback_used"] is True
    method = next(symbol for symbol in symbols if symbol["name"] == "M")
    assert method["end_line"] == 3
    assert any(edge["src"].endswith("M") and edge["dst"] == "SaveResult" for edge in edges)


@pytest.mark.parametrize(
    ("language", "source", "expected_call"),
    [
        ("python", 'def caller():\n    # phantomComment()\n    text = "phantomString()"\n    realCall()\n', "realCall"),
        ("csharp", 'class Handler { void Caller() { // phantomComment()\n /* phantomBlock() */ var text = "phantomString()"; service.RealCall(); } }', "RealCall"),
        ("cpp", 'class Handler { public: void caller() { // phantomComment()\n const char* text = "phantomString()"; service.realCall(); } };', "realCall"),
        ("typescript", 'function caller() { /* phantomComment() */ const text = "phantomString()"; return service.realCall(); }', "realCall"),
        ("tsx", 'function caller() { /* phantomComment() */ const text = "phantomString()"; return service.realCall(); }', "realCall"),
        ("javascript", 'function caller() { /* phantomComment() */ const text = `phantomTemplate()`; return service.realCall(); }', "realCall"),
        ("go", 'package api\nfunc caller() { /* phantomComment() */ note := `phantomRaw()`; service.RealCall() }', "RealCall"),
        ("rust", 'fn caller() { /* phantom_comment() */ let note = r##"phantom_raw()"##; service.real_call(); }', "real_call"),
        ("java", 'class Handler { void caller() { /* phantomComment() */ String text = "phantomString()"; service.realCall(); } }', "realCall"),
    ],
)
def test_treesitter_masks_comments_and_literals_before_call_extraction(
    language: str, source: str, expected_call: str
) -> None:
    if not is_treesitter_available(language):
        pytest.skip(f"Tree-sitter parser unavailable for {language}")

    parsed = parse_treesitter(source, language)

    assert parsed is not None
    _symbols, _refs, edges = parsed
    calls = [str(edge.get("dst", "")) for edge in edges if edge.get("kind") == "calls"]
    assert any(target.endswith(expected_call) for target in calls)
    assert not any("phantom" in target.lower() for target in calls)


@pytest.mark.parametrize(("filename", "language"), [("view.tsx", "tsx"), ("module.cpp", "cpp")])
def test_file_extension_dispatches_matching_treesitter_language(
    filename: str, language: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    index = CodeIndex({"server": {"state_dir": str(tmp_path)}}, repo_tools=None)
    dispatched: list[str] = []

    def unavailable_parser(_source: str, requested_language: str) -> dict[str, object]:
        dispatched.append(requested_language)
        return {
            "result": None,
            "status": "unavailable",
            "parser": "tree_sitter",
            "fallback_reason": "parser_unavailable",
            "syntax_error_count": 0,
        }

    monkeypatch.setattr(treesitter_parser, "parse_treesitter_with_status", unavailable_parser)

    language_for_file = index._language_for_path(filename, None)
    _symbols, _refs, _edges, report = index._parse_file_content_report(
        "function caller() { target(); }", language_for_file
    )

    assert dispatched == [language]
    assert report["fallback_used"] is True


@pytest.mark.parametrize(
    ("language", "filename", "source", "caller", "callee", "dead_symbol", "dependent_filename", "dependent_source"),
    [
        ("python", "runner.py", "def caller():\n    target()\n\ndef target(): pass\n\ndef unused_target(): pass\n", "caller", "target", "unused_target", "consumer.py", "def consumer():\n    caller()\n"),
        ("csharp", "Runner.cs", "class Runner {\n    void Caller() { Target(); }\n    void Target() {}\n    void UnusedTarget() {}\n}", "Caller", "Target", "UnusedTarget", "Consumer.cs", "class Consumer { void Use() { new Runner().Caller(); } }"),
        ("typescript", "runner.ts", "function caller() { target(); }\nfunction target() {}\nfunction unusedTarget() {}", "caller", "target", "unusedTarget", "consumer.ts", "function consumer() { caller(); }"),
        ("tsx", "runner.tsx", "function caller() { target(); return <div />; }\nfunction target() {}\nfunction unusedTarget() {}", "caller", "target", "unusedTarget", "consumer.tsx", "function consumer() { caller(); return <div />; }"),
        ("javascript", "runner.js", "function caller() { target(); }\nfunction target() {}\nfunction unusedTarget() {}", "caller", "target", "unusedTarget", "consumer.js", "function consumer() { caller(); }"),
        ("go", "runner.go", "package main\nfunc caller() { target() }\nfunc target() {}\nfunc unusedTarget() {}", "caller", "target", "unusedTarget", "consumer.go", "package main\nfunc consumer() { caller() }"),
        ("rust", "runner.rs", "fn caller() { target(); }\nfn target() {}\nfn unused_target() {}", "caller", "target", "unused_target", "consumer.rs", "fn consumer() { caller(); }"),
        ("java", "Runner.java", "class Runner {\n    void caller() { target(); }\n    void target() {}\n    void unusedTarget() {}\n}", "caller", "target", "unusedTarget", "Consumer.java", "class Consumer { void use() { new Runner().caller(); } }"),
        ("cpp", "runner.cpp", "class Runner {\n    void caller() { target(); }\n    void target() {}\n    void unusedTarget() {}\n};", "caller", "target", "unusedTarget", "consumer.cpp", "class Consumer { void use() { Runner r; r.caller(); } };"),
        ("php", "runner.php", "<?php\nfunction caller() { target(); }\nfunction target() {}\nfunction unused_target() {}", "caller", "target", "unused_target", "consumer.php", "<?php\nfunction consumer() { caller(); }"),
    ],
)
def test_fallback_call_queries_cover_declared_parser_languages(
    language: str,
    filename: str,
    source: str,
    caller: str,
    callee: str,
    dead_symbol: str,
    dependent_filename: str,
    dependent_source: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        treesitter_parser,
        "parse_treesitter_with_status",
        lambda _source, _language: {
            "result": None, "status": "unavailable", "parser": "tree_sitter",
            "fallback_reason": "parser_unavailable", "syntax_error_count": 0,
        },
    )
    index, root = _new_index(tmp_path)
    (root / filename).write_text(source, encoding="utf-8")
    (root / dependent_filename).write_text(dependent_source, encoding="utf-8")

    update = index.update_file(str(root), filename)
    dependent_update = index.update_file(str(root), dependent_filename)
    callers = index.find_callers(str(root), callee)["callers"]
    callees = index.find_callees(str(root), caller)["callees"]
    impact = index.impact(str(root), [filename])

    assert update["parse_outcome"]["fallback_used"] is True
    assert dependent_update["success"] is True
    assert any(edge["caller"].endswith(caller) and edge["callee"].endswith(callee) for edge in callers)
    assert any(edge["caller"].endswith(caller) and edge["callee"].endswith(callee) for edge in callees)
    symbols = index.find_symbol(str(root), caller)["symbols"]
    assert any(item["name"] == caller for item in symbols)
    dead = index.find_dead_code(str(root))["dead_code"]
    assert any(item["name"] == dead_symbol for item in dead)
    assert not any(item["name"] == callee for item in dead)
    assert any(item["path"] == dependent_filename for item in impact["likely_dependents"])

    consumer_root = tmp_path / f"consumer-{language}"
    consumer_root.mkdir()
    (consumer_root / dependent_filename).write_text(dependent_source, encoding="utf-8")
    assert index.update_file(str(consumer_root), dependent_filename)["success"] is True
    cross_repo_impact = DeterministicEngine(code_index=index).cross_project_impact(
        caller, [str(root), str(consumer_root)],
    )
    assert cross_repo_impact["origin_repo"] == str(root)
    assert str(consumer_root) in cross_repo_impact["impacted_repos"]
    assert cross_repo_impact["cross_boundary_references_count"] == 1


@pytest.mark.parametrize(
    ("manifest", "source_path", "source", "test_path", "test_source", "framework", "unrelated_path", "unrelated_source", "command_fragment"),
    [
        ("pyproject.toml", "src/runner.py", "def run(): target()\n", "tests/test_runner.py", "def test_runner(): run()\n", "pytest", "tests/test_unrelated.py", "def test_unrelated(): pass\n", "pytest tests/test_runner.py"),
        ("Runner.csproj", "src/Runner.cs", "class Runner { void Run() { Target(); } }", "tests/RunnerTests.cs", "class RunnerTests { [Fact] public void RunWorks() { new Runner().Run(); } }", "dotnet", "tests/UnrelatedTests.cs", "class UnrelatedTests { [Fact] public void Other() {} }", "FullyQualifiedName~RunnerTests"),
        ("package.json", "src/runner.js", "export function run() { target(); }", "tests/runner.test.js", "import { run } from '../src/runner'; test('run', () => run());", "npm", "tests/unrelated.test.js", "test('other', () => {});", "tests/runner.test.js"),
        ("go.mod", "src/runner.go", "package runner\nfunc Run() { target() }\n", "tests/runner_test.go", "package runner\nfunc TestRunner(t *testing.T) { Run() }\n", "go", "tests/unrelated_test.go", "package runner\nfunc TestOther(t *testing.T) {}\n", "tests/runner_test.go"),
        ("Cargo.toml", "src/runner.rs", "pub fn run() { target(); }\n", "tests/runner.rs", "#[test]\nfn runner_test() { crate::run(); }\n", "cargo", "tests/unrelated.rs", "#[test]\nfn unrelated_test() {}\n", "runner"),
    ],
)
def test_affected_tests_maps_indexed_callers_for_declared_frameworks(
    tmp_path: Path,
    manifest: str,
    source_path: str,
    source: str,
    test_path: str,
    test_source: str,
    framework: str,
    unrelated_path: str,
    unrelated_source: str,
    command_fragment: str,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / manifest).write_text("", encoding="utf-8")
    config = {"server": {"state_dir": str(tmp_path / "state")}}
    repo_tools = RepositoryTools(config)
    index = CodeIndex(config, repo_tools)
    for rel_path, content in (
        (source_path, source), (test_path, test_source), (unrelated_path, unrelated_source),
    ):
        target = root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        assert index.update_file(str(root), rel_path)["success"] is True

    engine = DeterministicEngine(config, repo_tools=repo_tools, code_index=index)
    result = engine.affected_tests(str(root), changed_paths=[source_path])
    matched = {path.replace("\\", "/") for path in result["test_files"]}

    assert result["success"] is True
    assert result["framework"] == framework
    assert test_path in matched
    assert unrelated_path not in matched
    assert command_fragment in result["suggested_command"]


def test_api_spec_extracts_supported_framework_routes_and_ignores_non_code(tmp_path: Path) -> None:
    root = tmp_path / "api"
    root.mkdir()
    (root / "routes.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n"
        "# @app.delete('/commented-python')\n"
        "example = \"@app.post('/quoted-python')\"\n"
        "@app.get('/python-items')\ndef list_items(): return []\n",
        encoding="utf-8",
    )
    (root / "routes.js").write_text(
        "// app.delete('/commented-js', handler);\n"
        "const example = \"router.put('/quoted-js', handler)\";\n"
        "app.get('/js-items/:id', handler);\n"
        "router.post('/js-items', handler);\n",
        encoding="utf-8",
    )
    (root / "routes.php").write_text(
        "<?php\n// Route::delete('/commented-php', [ItemController::class, 'delete']);\n"
        "$example = \"Route::post('/quoted-php', [ItemController::class, 'post'])\";\n"
        "Route::get('/php-items', [ItemController::class, 'index']);\n"
        "class ItemsController {\n    #[Get('/php-attribute')]\n    public function show() {}\n}\n",
        encoding="utf-8",
    )
    (root / "forms.html").write_text(
        "<!-- <form action='/commented-html' method='GET'> -->\n"
        "<form action='/html-items' method='post'><button>Go</button></form>\n",
        encoding="utf-8",
    )
    next_route = root / "app" / "api" / "health" / "route.ts"
    next_route.parent.mkdir(parents=True)
    next_route.write_text(
        "// export function DELETE() {}\n"
        "export async function GET() { return Response.json({ ok: true }); }\n",
        encoding="utf-8",
    )

    result = DeterministicEngine().extract_api_spec(str(root))
    routes = {(item["method"], item["path"]) for item in result["endpoints"]}

    assert result["success"] is True
    assert routes == {
        ("GET", "/python-items"),
        ("GET", "/js-items/:id"),
        ("POST", "/js-items"),
        ("GET", "/php-items"),
        ("GET", "/php-attribute"),
        ("POST", "/html-items"),
        ("GET", "/health"),
    }


def test_cross_repo_impact_uses_indexed_python_and_typescript_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        treesitter_parser,
        "parse_treesitter_with_status",
        lambda _source, _language: {
            "result": None, "status": "unavailable", "parser": "tree_sitter",
            "fallback_reason": "parser_unavailable", "syntax_error_count": 0,
        },
    )
    config = {"server": {"state_dir": str(tmp_path / "state")}}
    index = CodeIndex(config, _SnapshotReader())
    engine = DeterministicEngine(config, repo_tools=None, code_index=index)
    backend = tmp_path / "backend"
    frontend = tmp_path / "frontend"
    (backend / "src").mkdir(parents=True)
    (frontend / "src").mkdir(parents=True)
    (backend / "src" / "auth.py").write_text(
        "def AuthenticateUser():\n    return True\n", encoding="utf-8",
    )
    (frontend / "src" / "auth_client.ts").write_text(
        "export function login() { return AuthenticateUser(); }\n", encoding="utf-8",
    )
    assert index.update_file(str(backend), "src/auth.py")["success"] is True
    assert index.update_file(str(frontend), "src/auth_client.ts")["success"] is True

    found = engine.cross_repo_symbol_find([str(backend), str(frontend)], "AuthenticateUser")
    impact = engine.cross_project_impact("AuthenticateUser", [str(backend), str(frontend)])

    assert any(item["name"] == "AuthenticateUser" and item["repo"] == str(backend) for item in found["symbols"])
    assert impact["origin_repo"] == str(backend)
    assert str(frontend) in impact["impacted_repos"]
    assert impact["cross_boundary_references_count"] == 1


def test_code_invariants_reports_unsupported_source_and_parse_errors(tmp_path: Path) -> None:
    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})
    root = tmp_path / "repo"
    root.mkdir()
    (root / "broken.py").write_text("def broken(:\n    pass\n", encoding="utf-8")
    (root / "module.ts").write_text("export function run( {\n", encoding="utf-8")

    broken = engine.code_invariants(str(root), path="broken.py")
    unsupported = engine.code_invariants(str(root), path="module.ts")

    assert broken["success"] is False
    assert broken["complete"] is False
    assert broken["parse_errors"][0]["path"] == "broken.py"
    assert unsupported["success"] is False
    assert unsupported["complete"] is False
    assert unsupported["unsupported_files"][0]["path"] == "module.ts"

    outside = root.parent / "outside.py"
    outside.write_text("pass\n", encoding="utf-8")
    outside_result = engine.code_invariants(str(root), path=str(outside))
    assert outside_result["success"] is False
    assert outside_result["complete"] is False
    assert outside_result["error"] == "path_outside_root"


def test_code_invariants_marks_repository_file_cap_as_incomplete(tmp_path: Path) -> None:
    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})
    root = tmp_path / "large-repo"
    root.mkdir()
    for index in range(151):
        (root / f"module_{index}.py").write_text("pass\n", encoding="utf-8")

    result = engine.code_invariants(str(root))

    assert result["files_checked"] == 150
    assert result["truncated"] is True
    assert result["complete"] is False
    assert result["success"] is False


def test_code_invariants_marks_walk_errors_as_incomplete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})
    root = tmp_path / "repo"
    root.mkdir()
    (root / "visible.py").write_text("pass\n", encoding="utf-8")

    def failing_walk(top: str | os.PathLike[str], *, onerror):
        onerror(PermissionError(13, "permission denied", str(root / "blocked")))
        yield str(root), [], ["visible.py"]

    monkeypatch.setattr(deterministic_module.os, "walk", failing_walk)

    result = engine.code_invariants(str(root))

    assert result["success"] is False
    assert result["complete"] is False
    assert Path(result["scan_errors"][0]["path"]).name == "blocked"


def test_code_invariants_reports_file_read_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "unreadable.py"
    source.write_text("pass\n", encoding="utf-8")
    original_read_text = Path.read_text

    def failing_read_text(path: Path, *args, **kwargs) -> str:
        if path == source:
            raise PermissionError(13, "permission denied", str(source))
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", failing_read_text)

    result = engine.code_invariants(str(root), path="unreadable.py")

    assert result["success"] is False
    assert result["complete"] is False
    assert result["read_errors"][0]["path"] == "unreadable.py"


def test_code_invariants_rejects_missing_repository_root(tmp_path: Path) -> None:
    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})

    result = engine.code_invariants(str(tmp_path / "missing-repo"))

    assert result["success"] is False
    assert result["complete"] is False
    assert result["error"] == "root_not_directory"
    assert result["files_checked"] == 0


def test_code_invariants_ignores_archive_and_hidden_dirs(tmp_path: Path) -> None:
    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})
    root = tmp_path / "repo"
    root.mkdir()
    (root / "src").mkdir()
    (root / "src" / "valid.py").write_text("a = 1\n", encoding="utf-8")
    handoff = root / ".handoff" / "overlay"
    handoff.mkdir(parents=True)
    (handoff / "archived.py").write_text("import subprocess\nsubprocess.run(['cmd'])\n", encoding="utf-8")
    cache_dir = root / ".cache"
    cache_dir.mkdir()
    (cache_dir / "cached.py").write_text("invalid syntax :::\n", encoding="utf-8")

    result = engine.code_invariants(str(root))

    assert result["success"] is True
    assert result["complete"] is True
    assert result["files_checked"] == 1
    assert result["violation_count"] == 0


def test_cross_repo_impact_uses_native_parsers_for_python_and_typescript(

    tmp_path: Path,
) -> None:
    if not is_treesitter_available("python") or not is_treesitter_available("typescript"):
        pytest.skip("Tree-sitter parser unavailable for Python or TypeScript")

    config = {"server": {"state_dir": str(tmp_path / "state")}}
    index = CodeIndex(config, _SnapshotReader())
    engine = DeterministicEngine(config, repo_tools=None, code_index=index)
    backend = tmp_path / "backend-native"
    frontend = tmp_path / "frontend-native"
    (backend / "src").mkdir(parents=True)
    (frontend / "src").mkdir(parents=True)
    (backend / "src" / "auth.py").write_text(
        "def AuthenticateUser():\n    return True\n", encoding="utf-8",
    )
    (frontend / "src" / "auth_client.ts").write_text(
        "export function login() { return AuthenticateUser(); }\n", encoding="utf-8",
    )

    backend_update = index.update_file(str(backend), "src/auth.py")
    frontend_update = index.update_file(str(frontend), "src/auth_client.ts")
    impact = engine.cross_project_impact(
        "AuthenticateUser", [str(backend), str(frontend)],
    )

    assert backend_update["parse_outcome"]["parser"] == "python"
    assert frontend_update["parse_outcome"]["parser"] == "typescript"
    assert backend_update["parse_outcome"]["fallback_used"] is False
    assert frontend_update["parse_outcome"]["fallback_used"] is False
    assert impact["origin_repo"] == str(backend)
    assert str(frontend) in impact["impacted_repos"]
    assert impact["cross_boundary_references_count"] == 1

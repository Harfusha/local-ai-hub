from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from local_ai_hub.code_index import CodeIndex
from local_ai_hub.treesitter_parser import is_treesitter_available, parse_treesitter

class _SnapshotReader:
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

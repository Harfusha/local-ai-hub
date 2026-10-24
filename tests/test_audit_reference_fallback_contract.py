"""Fallback references retain caller locations and honest index coverage."""

from __future__ import annotations

import copy
import sqlite3
from types import SimpleNamespace

import pytest

from local_ai_hub.code_index import CodeIndex
from local_ai_hub.external_tools import ExternalCodeIntelligence
from local_ai_hub.repo_tools import RepositoryTools


def _fallback(index, root, *, limit=20):
    service = object.__new__(ExternalCodeIntelligence)
    service.code_index = index
    return service._fallback_code_index(
        str(root), "references", "target", "defs.py", limit=limit,
        reason="serena_unavailable_for_fixture",
    )


def test_real_index_fallback_finds_multiple_callers_instead_of_definition(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    sources = {
        "defs.py": "def target(value):\n    return value\n",
        "calls_one.py": "from defs import target\ndef first():\n    return target(1)\n",
        "calls_two.py": "from defs import target\ndef second():\n    return target(2) + target(3)\n",
    }
    for name, text in sources.items():
        (root / name).write_text(text, encoding="utf-8")
    config = {"server": {"state_dir": str(tmp_path / "index-state")}}
    index = CodeIndex(config, RepositoryTools(config))
    indexed = index.update_files_batch(str(root), list(sources))
    assert indexed["success"] is True, indexed
    raw = index.find_referencing_symbols(str(root), "target")
    result = _fallback(index, root)
    assert result["success"] is True, result
    assert result["references"] == raw["references"]
    locations = {(item["path"], item["line"]) for item in result["references"]}
    assert {("calls_one.py", 3), ("calls_two.py", 3)} <= locations
    assert all(path != "defs.py" for path, _line in locations)
    assert result["matches"] == result["references"]
    assert result["matches_count"] == len(raw["references"])
    assert result["fallback_used"] is True
    assert result["coverage"] == {"complete": False, "scope": "indexed_lexical_references"}
    limited = _fallback(index, root, limit=1)
    assert limited["references"] == raw["references"][:1]
    assert limited["has_more"] is True
    assert limited["coverage"]["complete"] is False


@pytest.mark.parametrize("backend_success", [True, False])
def test_reference_fallback_preserves_backend_outcome_and_partiality(tmp_path, backend_success):
    raw = {
        "success": backend_success, "references": [{"path": "calls.py", "line": 8, "symbol": "target"}],
        "has_more": True, "partial": True, "complete": False,
        "coverage": {"complete": False, "scope": "backend-subset"},
    }
    if not backend_success:
        raw.update(error="index unavailable", terminal=True, retryable=False, status_code=503)
    original = copy.deepcopy(raw)
    calls = []

    def references(*args, **kwargs):
        calls.append((args, kwargs))
        return raw

    def definitions(*_args, **_kwargs):
        pytest.fail("reference fallback attempted a definition lookup")

    result = _fallback(SimpleNamespace(find_referencing_symbols=references, find_symbol=definitions), tmp_path)
    assert result["success"] is backend_success
    assert result["references"] == raw["references"]
    assert result["partial"] is True and result["complete"] is False
    assert result["has_more"] is True and result["coverage"]["complete"] is False
    if not backend_success:
        for name in ("error", "terminal", "retryable", "status_code"):
            assert result[name] == raw[name]
    assert calls == [((str(tmp_path), "target"), {})]
    assert raw == original


@pytest.mark.parametrize("malformed", [None, [], {"success": True, "references": "not-a-list"}])
def test_malformed_reference_backend_cannot_become_success(tmp_path, malformed):
    result = _fallback(SimpleNamespace(find_referencing_symbols=lambda *_args: malformed), tmp_path)
    assert result["success"] is False
    assert "code_index_error:ValueError" in result["degraded_reason"]
    assert result.get("references", []) == []


def test_reference_index_database_error_remains_explicit(tmp_path):
    def broken(*_args):
        raise sqlite3.OperationalError("fixture reference index read failure")

    result = _fallback(SimpleNamespace(find_referencing_symbols=broken), tmp_path)
    assert result["success"] is False
    assert result["error"] == "fixture reference index read failure"
    assert "code_index_error:OperationalError" in result["degraded_reason"]
    assert result.get("references", []) == []

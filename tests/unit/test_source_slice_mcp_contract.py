"""Deferred registered-MCP regressions; no live Hub/model dependencies."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub import source_slice
from local_ai_hub.source_slice import MAX_SOURCE_BYTES, read_source_slice


def _wire(monkeypatch, tmp_path, tool, arguments):
    from local_ai_hub import mcp_server
    from local_ai_hub.features import FeatureSet

    monkeypatch.setattr(mcp_server, "_workspace", str(tmp_path))
    monkeypatch.setattr(mcp_server, "FEATURES", FeatureSet({}))
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda *args, **kwargs: None)
    monkeypatch.setattr(mcp_server.CONTEXT_LEDGER, "record", lambda **kwargs: None)
    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda *args, **kwargs: mcp_server.OperationalModeSnapshot("active", 0, None))
    result = asyncio.run(mcp_server.mcp.call_tool(tool, arguments))
    contents, structured = result if isinstance(result, tuple) else (result, None)
    payload = json.loads(contents[0].text)
    wire = {"content": [{"type": "text", "text": contents[0].text}]}
    if structured is not None:
        wire.update(structuredContent=structured, isError=False)
    return payload, wire


@pytest.mark.parametrize("absolute", [False, True])
def test_registered_source_reads_five_exact_lines_with_provenance(tmp_path, monkeypatch, absolute):
    from local_ai_hub.token_accounting import json_tokens

    source = tmp_path / "sample.py"
    data = "".join(f"line_{index}\n" for index in range(1, 11)).encode()
    source.write_bytes(data)
    payload, wire = _wire(monkeypatch, tmp_path, "local_ai_artifact", {
        "action": "source", "path": str(source) if absolute else "sample.py",
        "line_start": 3, "line_end": 7, "max_response_tokens": 1800,
    })
    assert payload["success"] is True, payload
    assert payload["text"] == "".join(f"line_{index}\n" for index in range(3, 8))
    assert payload["file_sha256"] == hashlib.sha256(data).hexdigest()
    assert (payload["line_start"], payload["line_end"]) == (3, 7)
    assert payload["complete"] is True
    assert json_tokens(wire) <= 1800


def test_registered_source_rejects_outside_workspace(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("sentinel\n", encoding="utf-8")
    payload, _ = _wire(monkeypatch, root, "local_ai_artifact", {
        "action": "source", "path": str(outside), "line_start": 1, "line_end": 1,
    })
    assert payload["success"] is False
    assert payload["terminal"] is True and payload["retryable"] is False
    assert outside.read_text(encoding="utf-8") == "sentinel\n"


def test_source_never_claims_trimmed_transport_text_is_exact(tmp_path, monkeypatch):
    source = tmp_path / "wide.py"
    source.write_text("x" * 10000 + "\n", encoding="utf-8")
    payload, wire = _wire(monkeypatch, tmp_path, "local_ai_artifact", {
        "action": "source", "path": "wide.py", "line_start": 1, "line_end": 1,
        "max_chars": 12000, "max_response_tokens": 512,
    })
    from local_ai_hub.token_accounting import json_tokens
    assert json_tokens(wire) <= 512
    assert payload["success"] is False or payload["text"] == "x" * 10000 + "\n"


def test_source_file_and_line_bounds_are_explicit(tmp_path):
    source = tmp_path / "large.py"
    source.write_bytes(b"#" * (MAX_SOURCE_BYTES + 1))
    assert read_source_slice(str(tmp_path), "large.py")["success"] is False
    assert read_source_slice(str(tmp_path), "large.py", line_start=1, line_end=201)["success"] is False


def test_source_accepts_stable_file_when_path_and_handle_ctime_differ(tmp_path, monkeypatch):
    source = tmp_path / "sample.py"
    source.write_text("unchanged\n", encoding="utf-8")
    real_fstat = os.fstat

    def handle_stat(fd):
        observed = real_fstat(fd)
        values = {name: getattr(observed, name) for name in dir(observed) if name.startswith("st_")}
        values["st_ctime_ns"] += 1_000_000
        return SimpleNamespace(**values)

    monkeypatch.setattr(source_slice.os, "fstat", handle_stat)
    result = read_source_slice(str(tmp_path), "sample.py")
    assert result["success"] is True, result
    assert result["text"] == "unchanged\n"


def test_source_rejects_path_identity_change_during_read(tmp_path, monkeypatch):
    source = tmp_path / "sample.py"
    source.write_text("unchanged\n", encoding="utf-8")
    real_stat = Path.stat
    source_stat_calls = 0

    def changed_path_stat(path, *, follow_symlinks=True):
        nonlocal source_stat_calls
        observed = real_stat(path, follow_symlinks=follow_symlinks)
        if path == source:
            source_stat_calls += 1
            if source_stat_calls == 3:
                values = {name: getattr(observed, name) for name in dir(observed) if name.startswith("st_")}
                values["st_mtime_ns"] += 1
                return SimpleNamespace(**values)
        return observed

    monkeypatch.setattr(Path, "stat", changed_path_stat)
    result = read_source_slice(str(tmp_path), "sample.py")
    assert result["success"] is False
    assert "changed while reading" in result["error"]


def test_source_symlink_escape_is_rejected(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("outside\n", encoding="utf-8")
    link = root / "link.py"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("host does not permit test symlinks")
    assert read_source_slice(str(root), str(link))["success"] is False


def test_code_index_null_boolean_returns_typed_field_diagnostic(tmp_path, monkeypatch):
    from local_ai_hub import mcp_server
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda *args, **kwargs: {
        "success": True, "symbols": [], "stale": None, "request_id": "req_fixture",
    })
    payload, _ = _wire(monkeypatch, tmp_path, "local_ai_repo", {
        "action": "code_index", "root": str(tmp_path), "query": "Example", "limit": 3,
    })
    assert payload["success"] is False
    assert payload["terminal"] is True and payload["retryable"] is False
    assert "result.stale" in payload["error"]
    assert payload["request_id"] == "req_fixture"

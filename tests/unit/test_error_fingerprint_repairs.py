import sqlite3
from unittest.mock import create_autospec

import pytest

from local_ai_hub.code_index import CodeIndex
from local_ai_hub.external_tools import ExternalCodeIntelligence, MCPSoftTimeoutError
from local_ai_hub.telemetry import TelemetryStore


@pytest.mark.parametrize("index_success", [True, False])
@pytest.mark.parametrize("action", ["search", "find_symbol"])
def test_serena_search_timeout_uses_real_index_api(tmp_path, monkeypatch, index_success, action):
    monkeypatch.setattr(ExternalCodeIntelligence, "_startup_preflight", lambda self: None)
    index = create_autospec(CodeIndex, instance=True, spec_set=True)
    index.query.return_value = {
        "success": index_success,
        "symbols": [{"name": "example", "path": "example.py", "line": 1}] if index_success else [],
        **({} if index_success else {"error": "index unavailable", "retryable": False}),
    }
    index.find_symbol.return_value = index.query.return_value
    telemetry = create_autospec(TelemetryStore, instance=True)
    external = ExternalCodeIntelligence({
        "server": {"state_dir": str(tmp_path / "state")},
        "code_intelligence": {"enabled": True, "serena_enabled": True},
    }, code_index=index, telemetry=telemetry)
    root = str(tmp_path.resolve())
    external._serena = "serena"
    monkeypatch.setattr(external, "_serena_session", lambda _root: (_ for _ in ()).throw(MCPSoftTimeoutError("timeout")))
    try:
        result = external.query_serena(root, action, query="example", limit=7)
        if action == "search":
            index.query.assert_called_once_with(root, "example", limit=7)
        else:
            index.find_symbol.assert_called_once_with(root, "example", relative_path=None, limit=7, substring_matching=True)
        assert result["success"] is index_success
        assert result["fallback_used"] is True
        assert result["matches"] == index.query.return_value["symbols"]
        assert telemetry.record_error.call_args.kwargs["recovered"] is index_success
        if not index_success:
            assert result["error"] == "index unavailable"
    finally:
        external.close()


@pytest.mark.parametrize(("error_type", "expected"), [
    ("SchedulerTimeoutError", "model request timed out"),
    ("OperationalError", "database operation failed"),
    ("MCPSoftTimeoutError", "operation timed out"),
])
def test_safe_diagnostic_uses_explicit_error_class(tmp_path, monkeypatch, error_type, expected):
    store = TelemetryStore(tmp_path, enabled=False)
    store.enabled = True
    captured = []
    monkeypatch.setattr(store, "_enqueue", lambda kind, payload: captured.append((kind, payload)))
    monkeypatch.setattr(store, "record", lambda **kwargs: True)
    store.record_error("ollama", "delegate:review:model_attempt", "private prompt and source", error_type_override=error_type)
    payload = next(payload for kind, payload in captured if kind == "error")
    assert payload["safe_message"] == f"{error_type}: {expected}"
    assert "private" not in str(payload)


@pytest.mark.parametrize(("error", "expected"), [
    (sqlite3.OperationalError("database is locked; private source"), "OperationalError: database busy or locked"),
    (sqlite3.IntegrityError("private source constraint"), "IntegrityError: database integrity constraint failed"),
])
def test_database_diagnostics_keep_classification_without_raw_text(error, expected):
    from local_ai_hub.telemetry import _safe_error_message

    assert _safe_error_message(error) == expected

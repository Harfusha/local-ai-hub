from types import SimpleNamespace

from local_ai_hub import http_server, mcp_server


def _activate_repo(monkeypatch):
    from local_ai_hub.operational_mode import OperationalModeSnapshot

    monkeypatch.setattr(mcp_server.FEATURES, "repo", True)
    snapshot = OperationalModeSnapshot("active", 1, None)
    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda _state_dir: snapshot)


def _invoke_http_secret_scan(payload, scanner, monkeypatch):
    app = SimpleNamespace(
        recovery=None,
        services=SimpleNamespace(secret_scan=scanner),
        debug_traces=None,
        logger=SimpleNamespace(error=lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(http_server, "select_http_routes", lambda *_args: {"post_repo_secret_scan_1"})
    monkeypatch.setattr(http_server, "select_post_handler", lambda _route_ids: None)

    handler = object.__new__(http_server.Handler)
    handler.path = "/api/repo/secret_scan"
    handler.headers = {"Content-Type": "application/json"}
    handler._require_authorized = lambda: True
    # These tests exercise route payload handling after repository identity
    # binding. Root authorization has its own coverage and must not be bypassed
    # in production.
    handler._bind_repository_root_payload = lambda _payload: True
    handler._begin_trace = lambda _path: None
    handler._read_json = lambda: payload
    handler._validate_payload = lambda _path, _payload: None
    handler._claim_recovery = lambda *_args: True
    handler._finish_debug_trace = lambda *_args, **_kwargs: None
    handler._close_trace_context = lambda: None
    responses = []
    handler._send = lambda status, body: responses.append((status, body))
    handler.do_POST()
    return responses


def test_http_registered_secret_scan_passes_raw_depth_to_scanner(monkeypatch):
    calls = []

    def scanner(root, path, *, scan_git_history, commit_depth):
        calls.append((root, path, scan_git_history, commit_depth))
        return {"success": True, "status_code": 200}

    responses = _invoke_http_secret_scan(
        {"root": ".", "path": None, "scan_git_history": True, "commit_depth": 7},
        scanner,
        monkeypatch,
    )

    assert calls == [(".", None, True, 7)]
    assert responses[0] == (200, {"success": True, "status_code": 200})


def test_http_registered_secret_scan_passes_boolean_depth_to_scanner_error(monkeypatch):
    calls = []

    def scanner(root, path, *, scan_git_history, commit_depth):
        calls.append((root, path, scan_git_history, commit_depth))
        return {
            "success": False,
            "error": "commit_depth must be an integer from 1 to 100",
            "error_code": "invalid_commit_depth",
            "scan_complete": False,
            "clean": False,
            "scanned_git_history": False,
            "git_history_status": "invalid_commit_depth",
            "status_code": 400,
            "terminal": True,
            "retryable": False,
        }

    responses = _invoke_http_secret_scan(
        {"root": ".", "path": None, "scan_git_history": True, "commit_depth": True},
        scanner,
        monkeypatch,
    )

    assert calls == [(".", None, True, True)]
    assert responses[0][0] == 400
    assert responses[0][1]["error_code"] == "invalid_commit_depth"
    assert responses[0][1]["terminal"] is True
    assert responses[0][1]["retryable"] is False


def test_http_registered_secret_scan_rejects_non_boolean_history_flag(monkeypatch):
    calls = []
    responses = _invoke_http_secret_scan(
        {"root": ".", "scan_git_history": "false"},
        lambda *args, **kwargs: calls.append((args, kwargs)),
        monkeypatch,
    )

    assert calls == []
    assert responses[0][0] == 400
    assert responses[0][1]["terminal"] is True
    assert responses[0][1]["retryable"] is False


def test_http_registered_secret_scan_rejects_legacy_git_history_field(monkeypatch):
    calls = []
    responses = _invoke_http_secret_scan(
        {"root": ".", "git_history": True},
        lambda *args, **kwargs: calls.append((args, kwargs)),
        monkeypatch,
    )

    assert calls == []
    assert responses[0][0] == 400
    assert responses[0][1]["terminal"] is True
    assert responses[0][1]["retryable"] is False


def test_registered_mcp_secret_scan_allows_whole_history_and_literal_path_filter(monkeypatch):
    _activate_repo(monkeypatch)
    calls = []

    def post(url, payload, **kwargs):
        calls.append((url, payload, kwargs))
        return {"success": True, "scan_complete": True, "clean": True}

    monkeypatch.setattr(mcp_server.CLIENT, "post", post)

    mcp_server.local_ai_repo(action="secret_scan", root="/repo", staged=True)
    mcp_server.local_ai_repo(action="secret_scan", root="/repo", path="config.env", staged=True)

    scan_calls = [call for call in calls if call[0] == "/api/repo/secret_scan"]
    assert [(call[0], call[1]["path"], call[1]["scan_git_history"]) for call in scan_calls] == [
        ("/api/repo/secret_scan", None, True),
        ("/api/repo/secret_scan", "config.env", True),
    ]


def test_registered_mcp_secret_scan_requires_path_field_for_filters_and_validates_toggle(monkeypatch):
    _activate_repo(monkeypatch)
    calls = []
    monkeypatch.setattr(
        mcp_server.CLIENT,
        "post",
        lambda url, payload, **kwargs: calls.append((url, payload)) or {"success": True},
    )

    query_alias = mcp_server.local_ai_repo(action="secret_scan", root="/repo", query="config.env")
    task_alias = mcp_server.local_ai_repo(action="secret_scan", root="/repo", task="config.env")
    mcp_server.local_ai_repo(action="secret_scan", root="/repo", path="config.env")
    invalid = mcp_server.local_ai_repo(action="secret_scan", root="/repo", staged="false")

    scan_calls = [call for call in calls if call[0] == "/api/repo/secret_scan"]
    assert scan_calls[0][1]["path"] == "config.env"
    assert scan_calls[0][1]["scan_git_history"] is False
    assert len(scan_calls) == 1
    assert query_alias["status_code"] == 400
    assert task_alias["status_code"] == 400
    assert invalid["status_code"] == 400
    assert invalid["terminal"] is True
    assert invalid["retryable"] is False


def test_registered_mcp_secret_scan_does_not_treat_filename_substrings_as_controls(monkeypatch):
    _activate_repo(monkeypatch)
    calls = []
    monkeypatch.setattr(
        mcp_server.CLIENT,
        "post",
        lambda url, payload, **kwargs: calls.append((url, payload)) or {"success": True},
    )

    for filename in ("digital.env", "history.env"):
        mcp_server.local_ai_repo(action="secret_scan", root="/repo", path=filename)
    whole_repo_history = mcp_server.local_ai_repo(action="secret_scan", root="/repo", staged=True)

    scan_calls = [payload for url, payload in calls if url == "/api/repo/secret_scan"]
    assert [(call["path"], call["scan_git_history"]) for call in scan_calls] == [
        ("digital.env", False), ("history.env", False), (None, True),
    ]
    assert whole_repo_history["success"] is True


def test_registered_mcp_secret_scan_rejects_falsey_explicit_inputs(monkeypatch):
    _activate_repo(monkeypatch)
    calls = []
    monkeypatch.setattr(
        mcp_server.CLIENT,
        "post",
        lambda url, payload, **kwargs: calls.append((url, payload)) or {"success": True},
    )

    for field, value in (
        ("path", ""),
        ("path", "   "),
        ("path", False),
        ("query", ""),
        ("task", ""),
    ):
        result = mcp_server.local_ai_repo(
            action="secret_scan", root="/repo", **{field: value}
        )
        assert result["status_code"] == 400
        assert result["terminal"] is True
        assert result["retryable"] is False

    assert not any(url == "/api/repo/secret_scan" for url, _payload in calls)

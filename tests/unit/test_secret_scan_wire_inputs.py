from types import SimpleNamespace

from local_ai_hub import http_server, mcp_server


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
    handler._begin_trace = lambda _path: None
    handler._read_json = lambda: payload
    handler._validate_payload = lambda _path, _payload: None
    handler._tenant = lambda: "test"
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
        return {
            "success": False, "status_code": 400, "terminal": True, "retryable": False,
            "error_code": "invalid_commit_depth",
        }

    responses = _invoke_http_secret_scan(
        {"root": ".", "path": None, "scan_git_history": True, "commit_depth": True},
        scanner,
        monkeypatch,
    )

    assert calls == [(".", None, True, True)]
    assert responses[0][0] == 400
    assert responses[0][1]["error_code"] == "invalid_commit_depth"


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


def test_registered_mcp_secret_scan_requires_staged_toggle_and_explicit_path(monkeypatch):
    calls = []

    def post(url, payload, **kwargs):
        calls.append((url, payload, kwargs))
        return {"success": True, "scan_complete": True, "clean": True}

    monkeypatch.setattr(mcp_server.CLIENT, "post", post)

    mcp_server.local_ai_repo(
        action="secret_scan", root="/repo", path="config.env", query="git history", staged=True,
    )

    assert calls[0][0] == "/api/repo/secret_scan"
    assert calls[0][1]["scan_git_history"] is True
    assert calls[0][1]["path"] == "config.env"


def test_registered_mcp_secret_scan_preserves_query_filename_and_validates_toggle(monkeypatch):
    calls = []
    monkeypatch.setattr(
        mcp_server.CLIENT,
        "post",
        lambda url, payload, **kwargs: calls.append((url, payload)) or {"success": True},
    )

    mcp_server.local_ai_repo(action="secret_scan", root="/repo", query="config.env")
    invalid = mcp_server.local_ai_repo(action="secret_scan", root="/repo", staged="false")
    missing_path = mcp_server.local_ai_repo(action="secret_scan", root="/repo", staged=True)

    assert calls[0][1]["path"] == "config.env"
    assert calls[0][1]["scan_git_history"] is False
    assert len(calls) == 1
    assert invalid["status_code"] == 400
    assert invalid["terminal"] is True
    assert invalid["retryable"] is False
    assert missing_path["status_code"] == 400


def test_registered_mcp_secret_scan_does_not_treat_filename_substrings_as_controls(monkeypatch):
    calls = []
    monkeypatch.setattr(
        mcp_server.CLIENT,
        "post",
        lambda url, payload, **kwargs: calls.append(payload) or {"success": True},
    )

    for filename in ("digital.env", "history.env"):
        mcp_server.local_ai_repo(action="secret_scan", root="/repo", query=filename)
    mcp_server.local_ai_repo(
        action="secret_scan", root="/repo", path="config.env", query="git history", staged=True,
    )

    assert [(call["path"], call["scan_git_history"]) for call in calls] == [
        ("digital.env", False), ("history.env", False), ("config.env", True),
    ]

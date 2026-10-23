from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request

from local_ai_hub import http_server
from local_ai_hub.app import LocalAIApp


def test_telemetry_report_invalid_days_does_not_echo_private_input(tmp_path):
    state_dir = tmp_path / "state"
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join([
            "[server]", 'bind = "127.0.0.1"', "port = 11498", f'state_dir = "{state_dir.as_posix()}"',
            "[debug_traces]", "enabled = true",
        ]),
        encoding="utf-8",
    )
    app = LocalAIApp(str(config_path))
    previous_app = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    private_value = "PROMPT-PRIVATE token=TOKEN-PRIVATE /private/project/config.json"

    def request_invalid(path: str, query_name: str, expected_error: str):
        query = urllib.parse.urlencode({query_name: private_value})
        url = f"http://127.0.0.1:{server.server_address[1]}{path}?{query}"
        try:
            urllib.request.urlopen(url)
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8")), expected_error
        raise AssertionError("invalid query must be rejected")

    def request_valid(path: str, query: dict[str, int]):
        encoded = urllib.parse.urlencode(query)
        url = f"http://127.0.0.1:{server.server_address[1]}{path}?{encoded}"
        response = urllib.request.urlopen(url)
        return response.status, json.loads(response.read().decode("utf-8"))

    try:
        metrics_ok_status, metrics_ok_payload = request_valid("/api/metrics", {"days": 1})
        audit_ok_status, audit_ok_payload = request_valid("/api/audit/tail", {"limit": 1})
        status, payload, expected = request_invalid("/api/telemetry/report", "days", "days must be an integer")
        metrics_status, metrics_payload, metrics_expected = request_invalid("/api/metrics", "days", "days must be an integer")
        audit_status, audit_payload, audit_expected = request_invalid("/api/audit/tail", "limit", "limit must be an integer")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
        http_server.APP = previous_app
        app.close()

    assert status == 400
    assert metrics_ok_status == 200
    assert metrics_ok_payload["success"] is True
    assert audit_ok_status == 200
    assert audit_ok_payload["success"] is True
    assert payload["error"] == expected
    assert payload["terminal"] is True
    assert payload["retryable"] is False
    assert metrics_status == 400
    assert metrics_payload["error"] == metrics_expected
    assert metrics_payload["terminal"] is True
    assert metrics_payload["retryable"] is False
    assert audit_status == 400
    assert audit_payload["error"] == audit_expected
    assert audit_payload["terminal"] is True
    assert audit_payload["retryable"] is False
    serialized = json.dumps(payload)
    for response in (payload, metrics_payload, audit_payload):
        serialized = json.dumps(response)
        for private in ("PROMPT-PRIVATE", "TOKEN-PRIVATE", "/private/project"):
            assert private not in serialized

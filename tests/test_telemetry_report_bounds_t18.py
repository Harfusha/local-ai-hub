from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

from local_ai_hub.app import LocalAIApp
from local_ai_hub.json_utils import dumps as json_dumps
from local_ai_hub import http_server
import local_ai_hub.telemetry as telemetry_module
from local_ai_hub.telemetry import (
    _MAX_TELEMETRY_REPORT_BYTES,
    _bound_telemetry_report,
    _decode_error_page_cursor,
    _encode_error_page_cursor,
    TelemetryStore,
)


def test_telemetry_report_error_rows_are_paginated(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True)
    try:
        for index in range(5):
            store.record_error("inference", f"generate-{index}", ValueError("invalid argument"))
        assert store.flush(5)

        first = store.report(recent_errors=2, error_offset=0, _flush=False)
        second = store.report(recent_errors=2, error_offset=2, _flush=False)
        last = store.report(recent_errors=2, error_offset=4, _flush=False)
    finally:
        store.close()

    assert [len(page["error_fingerprints"]) for page in (first, second, last)] == [2, 2, 1]
    assert first["error_fingerprints_page"] == {"offset": 0, "limit": 2, "total": 5, "next_offset": 2}
    assert second["error_fingerprints_page"]["next_offset"] == 4
    assert last["error_fingerprints_page"]["next_offset"] is None


def test_telemetry_error_cursor_survives_rank_changes_between_pages(monkeypatch, tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True)
    try:
        for index in range(5):
            for _ in range(index + 1):
                store.record_error("component", f"operation-{index}", ValueError("same safe class"))
        assert store.flush(5)

        first = store.report(recent_errors=2, error_cursor="", _flush=False)
        first_keys = {(row["fingerprint"], row["error_type"], row["component"], row["operation"])
                      for row in first["error_fingerprints"]}
        assert first["error_fingerprints_page"]["next_cursor"]
        for row in first["error_fingerprints"]:
            for _ in range(8):
                store.record_error(row["component"], row["operation"], ValueError("new ranking"))
        store.record_error("component", "new-operation", RuntimeError("new group"))
        assert store.flush(5)
        snapshot_cutoff = first["error_fingerprints_page"]["snapshot_cutoff"]
        monkeypatch.setattr(store, "_scope_cutoff", lambda _days, scope: (snapshot_cutoff + 100_000, scope))

        second = store.report(
            recent_errors=2, error_cursor=first["error_fingerprints_page"]["next_cursor"], _flush=False
        )
        third = store.report(
            recent_errors=2, error_cursor=second["error_fingerprints_page"]["next_cursor"], _flush=False
        )
        all_rows = first["error_fingerprints"] + second["error_fingerprints"] + third["error_fingerprints"]
        all_keys = [(row["fingerprint"], row["error_type"], row["component"], row["operation"]) for row in all_rows]
    finally:
        store.close()

    assert len(all_keys) == 5
    assert len(set(all_keys)) == 5
    assert first_keys.isdisjoint(set(all_keys[2:]))
    assert all(row["operation"] != "new-operation" for row in all_rows)


def test_telemetry_report_http_route_accepts_error_page_parameters(tmp_path):
    state_dir = tmp_path / "state"
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join([
            "[server]", 'bind = "127.0.0.1"', "port = 11498", f'state_dir = "{state_dir.as_posix()}"',
        ]),
        encoding="utf-8",
    )
    app = LocalAIApp(str(config_path))
    for index in range(5):
        app.telemetry.record_error("inference", f"generate-{index}", ValueError("invalid argument"))
    previous_app = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/api/telemetry/report?error_limit=2&error_offset=2"
        with urllib.request.urlopen(url) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["success"] is True
        assert len(payload["report"]["error_fingerprints"]) == 2
        assert payload["report"]["error_fingerprints_page"]["offset"] == 2
        assert payload["report"]["error_fingerprints_page"]["total"] == 5

        bounded_url = f"http://127.0.0.1:{server.server_address[1]}/api/telemetry/report?error_limit=1000000000&error_offset=-10"
        with urllib.request.urlopen(bounded_url) as response:
            bounded_body = response.read()
            bounded_payload = json.loads(bounded_body.decode("utf-8"))
        page = bounded_payload["report"]["error_fingerprints_page"]
        assert page["limit"] == 100
        assert page["offset"] == 0
        assert len(bounded_payload["report"]["error_fingerprints"]) <= page["limit"]
        assert len(bounded_body) <= 256 * 1024

        cursor_url = f"http://127.0.0.1:{server.server_address[1]}/api/telemetry/report?error_limit=2&error_cursor="
        with urllib.request.urlopen(cursor_url) as response:
            cursor_payload = json.loads(response.read().decode("utf-8"))
        cursor_page = cursor_payload["report"]["error_fingerprints_page"]
        assert cursor_page["cursor"] == ""
        assert cursor_page["next_cursor"]
        next_url = cursor_url + cursor_page["next_cursor"]
        with urllib.request.urlopen(next_url) as response:
            next_payload = json.loads(response.read().decode("utf-8"))
        first_keys = {row["fingerprint"] for row in cursor_payload["report"]["error_fingerprints"]}
        next_keys = {row["fingerprint"] for row in next_payload["report"]["error_fingerprints"]}
        assert first_keys.isdisjoint(next_keys)

        try:
            urllib.request.urlopen(next_url + "&error_offset=0")
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
        else:
            raise AssertionError("cursor plus explicit offset must be rejected")

        try:
            urllib.request.urlopen(cursor_url + "not-a-valid-cursor!")
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
        else:
            raise AssertionError("malformed cursor must be rejected")
    finally:
        server.shutdown()
        server.server_close()
        http_server.APP = previous_app
        app.close()


def test_telemetry_report_response_stays_within_byte_budget():
    report = _bound_telemetry_report({
        "generated_at": "now",
        "window_days": 30,
        "scope": "window",
        "by_agent": [{"agent": f"agent-{index}", "label": "x" * 500} for index in range(1000)],
    })

    assert len(json_dumps(report).encode("utf-8")) <= _MAX_TELEMETRY_REPORT_BYTES
    assert report["response_truncated"] is True
    assert "by_agent" in report["response_truncated_fields"]
    assert report["by_agent"]


def test_report_budget_truncation_advances_cursor_after_retained_rows(monkeypatch):
    rows = [
        {
            "fingerprint": f"fingerprint-{index}",
            "error_type": "ValueError",
            "component": "inference",
            "operation": f"operation-{index}",
            "count": index + 1,
        }
        for index in range(8)
    ]
    original_row_count = len(rows)
    seed_cursor = _encode_error_page_cursor(17, 123.0, ("seed", "ValueError", "inference", "seed"))
    report = {
        "generated_at": "now",
        "window_days": 30,
        "scope": "window",
        "error_fingerprints": rows,
        "error_fingerprints_page": {
            "offset": 0,
            "limit": len(rows),
            "total": len(rows),
            "cursor": "",
            "snapshot_id": 17,
            "snapshot_cutoff": 123.0,
            "next_cursor": seed_cursor,
        },
    }
    one_row_report = {**report, "error_fingerprints": [rows[0]]}
    byte_budget = len(json_dumps(one_row_report).encode("utf-8")) + 256
    monkeypatch.setattr(telemetry_module, "_MAX_TELEMETRY_REPORT_BYTES", byte_budget)

    bounded = _bound_telemetry_report(report)
    kept = bounded["error_fingerprints"]
    page = bounded["error_fingerprints_page"]

    assert 0 < len(kept) < original_row_count
    assert page["next_offset"] is None
    assert page["has_more"] is True
    assert page["next_cursor"] != seed_cursor
    assert _decode_error_page_cursor(page["next_cursor"]) == (
        17,
        123.0,
        kept[-1]["fingerprint"],
        kept[-1]["error_type"],
        kept[-1]["component"],
        kept[-1]["operation"],
    )

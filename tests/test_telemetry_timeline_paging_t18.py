from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest

from local_ai_hub import http_server
from local_ai_hub.telemetry import TelemetryStore


def _record_operations(store: TelemetryStore) -> None:
    for index in range(5):
        store.record_http(action=f"operation_{index}", success=True)
    # Wait for persistence, independent of host scheduling and checkpoint latency.
    assert store.flush(10)


def test_telemetry_timeline_page_returns_recent_rows_before_cursor(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True, flush_interval_seconds=0.01)
    try:
        _record_operations(store)
        recent = store.get_timeline_page(limit=2)
        older = store.get_timeline_page(limit=2, before_id=recent["next_cursor"])
    finally:
        store.close()

    assert [row["action"] for row in recent["timeline"]] == [
        "operation_3",
        "operation_4",
    ]
    assert recent["has_more"] is True
    assert [row["action"] for row in older["timeline"]] == [
        "operation_1",
        "operation_2",
    ]


@pytest.mark.parametrize("before_id", [2**63 - 1, 2**63, 2**100])
def test_telemetry_timeline_page_clamps_before_id(tmp_path, before_id):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True)
    try:
        assert store.get_timeline_page(before_id=before_id)["timeline"] == []
    finally:
        store.close()


def test_http_timeline_get_and_post_page_before_cursor(tmp_path, monkeypatch, request):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True, flush_interval_seconds=0.01)
    request.addfinalizer(store.close)
    _record_operations(store)
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(
            config={"debug_traces": {"enabled": True}},
            logger=logging.getLogger(__name__),
            telemetry=store,
            recovery=SimpleNamespace(
                begin=lambda *_args, **_kwargs: {"claimed": True},
                finish=lambda *_args, **_kwargs: None,
            ),
        ),
    )
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args, **_kwargs: None)

    class TestHandler(http_server.Handler):
        def _require_authorized(self) -> bool:
            return True

    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), TestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}/api/telemetry/timeline"

    def get_page(query: str) -> dict:
        with urllib.request.urlopen(f"{base_url}?{query}", timeout=10) as response:
            assert response.status == 200
            return json.loads(response.read().decode("utf-8"))

    def post_page(payload: dict) -> dict:
        request = urllib.request.Request(
            base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Connection": "close"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                assert response.status == 200
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise AssertionError(f"POST failed with {exc.code}: {exc.read().decode('utf-8')}") from exc

    try:
        get_recent = get_page("limit=2")
        get_cursor = get_recent["next_cursor"]
        get_older = get_page(f"limit=2&before_id={get_cursor}")
        post_recent = post_page({"limit": 2})
        post_cursor = post_recent["next_cursor"]
        post_older = post_page({"limit": 2, "before_id": post_cursor})
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)

    assert get_recent["success"] is True
    assert get_recent["has_more"] is True
    assert [row["action"] for row in get_recent["timeline"]] == [
        "operation_3",
        "operation_4",
    ]
    assert get_cursor == get_recent["timeline"][0]["id"]
    assert [row["action"] for row in get_older["timeline"]] == [
        "operation_1",
        "operation_2",
    ]

    assert post_recent["success"] is True
    assert post_recent["has_more"] is True
    assert [row["action"] for row in post_recent["timeline"]] == [
        "operation_3",
        "operation_4",
    ]
    assert post_cursor == post_recent["timeline"][0]["id"]
    assert [row["action"] for row in post_older["timeline"]] == [
        "operation_1",
        "operation_2",
    ]

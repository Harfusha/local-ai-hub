from __future__ import annotations

from types import SimpleNamespace

from local_ai_hub import http_server
from local_ai_hub.telemetry import TelemetryStore


def test_telemetry_report_route_returns_first_next_and_last_error_pages(
    tmp_path, monkeypatch
) -> None:
    store = TelemetryStore(tmp_path / "telemetry", enabled=True)
    try:
        for index in range(5):
            store.record_error(
                "inference", f"generate-{index}", ValueError("invalid argument")
            )
        assert store.flush(1)
        monkeypatch.setattr(
            http_server,
            "APP",
            SimpleNamespace(
                config={"server": {"state_dir": str(tmp_path / "state")}},
                telemetry=store,
            ),
        )
        responses = []

        class Handler:
            headers = {"X-LocalAI-Client": "dashboard"}

            def _require_authorized(self):
                return True

            def _begin_trace(self, _path):
                return None

            def _send(self, status, payload):
                responses.append((status, payload))

        pages = []
        for offset in (0, 2, 4):
            handler = Handler()
            handler.path = (
                f"/api/telemetry/report?days=30&recent_errors=2&error_offset={offset}"
            )
            http_server.Handler.do_GET(handler)
            pages.append(responses[-1])
    finally:
        store.close()

    assert [status for status, _payload in pages] == [200, 200, 200]
    reports = [payload["report"] for _status, payload in pages]
    assert [report["error_fingerprints_page"]["offset"] for report in reports] == [
        0,
        2,
        4,
    ]
    assert [len(report["error_fingerprints"]) for report in reports] == [2, 2, 1]
    assert [report["error_fingerprints_page"]["next_offset"] for report in reports] == [
        2,
        4,
        None,
    ]


def test_telemetry_report_route_rejects_non_integer_page_values(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(
            config={"server": {"state_dir": str(tmp_path / "state")}},
            telemetry=SimpleNamespace(report=lambda *_args, **_kwargs: None),
        ),
    )
    responses = []

    class Handler:
        headers = {"X-LocalAI-Client": "dashboard"}
        path = "/api/telemetry/report?error_offset=invalid"

        def _require_authorized(self):
            return True

        def _begin_trace(self, _path):
            return None

        def _send(self, status, payload):
            responses.append((status, payload))

    http_server.Handler.do_GET(Handler())

    assert responses[0][0] == 400
    assert "error_offset" in responses[0][1]["error"]

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
        assert store.flush(10)
        monkeypatch.setattr(
            http_server,
            "APP",
            SimpleNamespace(
                config={"server": {"state_dir": str(tmp_path / "state")}},
                telemetry=store,
            ),
        )
        responses = []

        class Handler(http_server.Handler):
            headers = {"X-LocalAI-Client": "dashboard"}

            def _require_authorized(self):
                return True

            def _begin_trace(self, _path):
                return None

            def _send(self, status, payload):
                responses.append((status, payload))

        pages = []
        cursor = ""
        for _ in range(3):
            handler = object.__new__(Handler)
            handler.path = (
                f"/api/telemetry/report?days=30&recent_errors=2&error_cursor={cursor}"
            )
            http_server.Handler.do_GET(handler)
            pages.append(responses[-1])
            cursor = responses[-1][1]["report"]["error_fingerprints_page"]["next_cursor"] or ""
    finally:
        store.close()

    assert [status for status, _payload in pages] == [200, 200, 200]
    reports = [payload["report"] for _status, payload in pages]
    assert [len(report["error_fingerprints"]) for report in reports] == [2, 2, 1]
    assert [report["error_fingerprints_page"]["has_more"] for report in reports] == [True, True, False]
    keys = [row["fingerprint"] for report in reports for row in report["error_fingerprints"]]
    assert len(keys) == len(set(keys)) == 5


def test_telemetry_report_route_rejects_retired_offset_paging(
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

    class Handler(http_server.Handler):
        headers = {"X-LocalAI-Client": "dashboard"}
        path = "/api/telemetry/report?error_offset=0"

        def _require_authorized(self):
            return True

        def _begin_trace(self, _path):
            return None

        def _send(self, status, payload):
            responses.append((status, payload))

    handler = object.__new__(Handler)
    http_server.Handler.do_GET(handler)

    assert responses[0][0] == 400
    assert "error_cursor" in responses[0][1]["error"]

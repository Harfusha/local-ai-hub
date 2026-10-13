import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub import http_server
from local_ai_hub.http_server import _response_phase_latency
from local_ai_hub.http_server import Handler
from local_ai_hub.telemetry import TelemetryStore


def test_response_phase_latency_preserves_measured_phase_breakdown():
    source_root = Path(__file__).resolve().parents[2] / "src"
    assert Path(http_server.__file__).resolve().is_relative_to(source_root.resolve())

    actual = _response_phase_latency({
        "latency": {
            "queue_wait_ms": 2.5,
            "service_ms": 14.0,
            "db_wait_ms": 3.25,
            "exec_ms": 8.5,
            "serialization_ms": 1.75,
        }
    })

    assert actual == {
        "queue_wait_ms": 2.5,
        "service_ms": 14.0,
        "db_wait_ms": 3.25,
        "exec_ms": 8.5,
        "serialization_ms": 1.75,
    }


def test_response_phase_latency_omits_unmeasured_phases():
    actual = _response_phase_latency({"latency": {
        "queue_wait_ms": 1.5, "service_ms": 4.0,
        "db_wait_ms": True, "exec_ms": float("inf"), "serialization_ms": float("nan"),
    }})

    assert actual == {"queue_wait_ms": 1.5, "service_ms": 4.0}


def test_http_handler_records_measured_execution_and_serialization_on_success_and_error(monkeypatch, tmp_path):
    source_root = Path(__file__).resolve().parents[2] / "src"
    assert Path(http_server.__file__).resolve().is_relative_to(source_root.resolve())
    store = TelemetryStore(tmp_path / "http-telemetry", enabled=True)
    app = SimpleNamespace(
        config={"observability": {"exclude_http_paths": []}},
        telemetry=store,
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server, "MONITOR_PATHS", set())
    statuses = []
    class Clock:
        tick = 0

        def __call__(self):
            self.tick += 1
            return self.tick / 1000.0

    monkeypatch.setattr(http_server.time, "perf_counter", Clock())

    def request(path):
        handler = object.__new__(Handler)
        handler.path = path
        handler.command = "GET"
        handler.headers = {}
        handler.wfile = io.BytesIO()
        handler.send_response = lambda status: statuses.append(status)
        handler.send_header = lambda name, value: None
        handler.end_headers = lambda: None
        handler._finish_debug_trace = lambda status, data: None
        handler._request_started = http_server.time.perf_counter()
        Handler.do_GET(handler)

    try:
        request("/health")
        request("/missing")

        assert statuses == [200, 401]
        assert store.flush(5)
        events = store.live()["events"]
        assert [event["status_code"] for event in events] == [200, 401]
        for event in events:
            assert event["exec_ms"] == pytest.approx(1.0)
            assert event["exec_measured"] == 1
            assert event["serialization_ms"] == pytest.approx(1.0)
            assert event["serialization_measured"] == 1
            assert event["db_wait_ms"] == 0.0
            assert event["db_wait_measured"] == 0

        def fail_serialization(data):
            raise RuntimeError("serialization failed")

        monkeypatch.setattr(http_server, "_json_bytes", fail_serialization)
        with pytest.raises(RuntimeError, match="serialization failed"):
            request("/health")
        assert store.flush(5)
        assert len(store.live()["events"]) == 2
        assert statuses == [200, 401]
    finally:
        store.close()

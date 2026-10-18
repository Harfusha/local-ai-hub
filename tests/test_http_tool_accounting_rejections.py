from local_ai_hub import http_server
from local_ai_hub.telemetry import TelemetryStore


def test_tool_accounting_reports_aggregate_rejections_without_exception_details(monkeypatch):
    class Telemetry:
        def record_tool_accounting(self, event):
            if event["kind"] == "invalid":
                raise ValueError("sensitive prompt text")
            if event["kind"] == "failed":
                raise RuntimeError("private source text")
            if event["kind"] == "queue_full":
                return False

    class App:
        config = {}
        telemetry = Telemetry()

        class Recovery:
            @staticmethod
            def fingerprint_payload(_payload):
                return "test-fingerprint"

            @staticmethod
            def begin(*_args, **_kwargs):
                return {"claimed": True, "state": "running", "response": None}

            @staticmethod
            def finish(*_args, **_kwargs):
                return None

        recovery = Recovery()

    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/telemetry/tool-accounting"
    handler._telemetry_finished = False
    handler.headers = {"Content-Type": "application/json"}
    handler._begin_trace = lambda path: None
    handler._require_authorized = lambda: True
    handler._read_json = lambda: {
        "events": [
            {"kind": "accepted"},
            {"kind": "queue_full", "tool": "get_telemetry"},
            {"kind": "invalid"},
            {"kind": "failed"},
        ]
    }
    handler._validate_payload = lambda path, payload: None
    responses = []
    handler._send = lambda status, data: responses.append((status, data))
    monkeypatch.setattr(http_server, "APP", App())
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args, **_kwargs: None)

    handler.do_POST()

    assert responses == [
        (
            200,
            {
                "success": True,
                "accepted": 1,
                "rejected": 3,
                "rejection_reasons": {"invalid_event": 1, "queue_full": 1, "record_failed": 1},
            },
        )
    ]
    assert "sensitive prompt text" not in str(responses)
    assert "private source text" not in str(responses)
    assert handler._telemetry_finished is True


def test_suppressed_self_accounting_event_is_not_reported_as_accepted(monkeypatch):
    telemetry = object.__new__(TelemetryStore)
    telemetry.record = lambda **event: True
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/telemetry/tool-accounting"
    handler.headers = {"Content-Type": "application/json"}
    handler._begin_trace = lambda path: None
    handler._require_authorized = lambda: True
    handler._read_json = lambda: {
        "events": [{"tool": "local_ai_telemetry", "agent_tool_request_tokens_est": 20}]
    }
    handler._validate_payload = lambda path, payload: None
    responses = []
    handler._send = lambda status, data: responses.append((status, data))
    monkeypatch.setattr(http_server, "APP", type("App", (), {"telemetry": telemetry})())

    handler.do_POST()

    assert responses == [(
        200,
        {
            "success": True,
            "accepted": 0,
            "rejected": 1,
            "rejection_reasons": {"self_accounting": 1},
        },
    )]


def test_queue_rejected_tool_accounting_is_not_reported_as_accepted(monkeypatch):
    telemetry = object.__new__(TelemetryStore)
    telemetry.record = lambda **event: False
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/telemetry/tool-accounting"
    handler.headers = {"Content-Type": "application/json"}
    handler._begin_trace = lambda path: None
    handler._require_authorized = lambda: True
    handler._read_json = lambda: {
        "events": [{"tool": "get_telemetry", "agent_tool_request_tokens_est": 20}]
    }
    handler._validate_payload = lambda path, payload: None
    responses = []
    handler._send = lambda status, data: responses.append((status, data))
    monkeypatch.setattr(http_server, "APP", type("App", (), {"telemetry": telemetry})())

    handler.do_POST()

    assert responses == [(
        200,
        {
            "success": True,
            "accepted": 0,
            "rejected": 1,
            "rejection_reasons": {"queue_full": 1},
        },
    )]


def test_disabled_tool_accounting_reports_telemetry_disabled(monkeypatch):
    telemetry = type("Telemetry", (), {"enabled": False, "record_tool_accounting": lambda self, event: False})()
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/telemetry/tool-accounting"
    handler.headers = {"Content-Type": "application/json"}
    handler._begin_trace = lambda path: None
    handler._require_authorized = lambda: True
    handler._read_json = lambda: {"events": [{"tool": "get_telemetry", "agent_tool_request_tokens_est": 20}]}
    handler._validate_payload = lambda path, payload: None
    responses = []
    handler._send = lambda status, data: responses.append((status, data))
    monkeypatch.setattr(http_server, "APP", type("App", (), {"telemetry": telemetry})())

    handler.do_POST()

    assert responses == [(
        200,
        {
            "success": True,
            "accepted": 0,
            "rejected": 1,
            "rejection_reasons": {"telemetry_disabled": 1},
        },
    )]


def test_tool_accounting_records_owner_global_events_without_tenant_metadata(monkeypatch):
    recorded = []

    class Telemetry:
        def record_tool_accounting(self, event):
            recorded.append(event)
            return True

    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/telemetry/tool-accounting"
    handler.headers = {"Content-Type": "application/json"}
    handler._begin_trace = lambda path: None
    handler._require_authorized = lambda: True
    handler._read_json = lambda: {
        "events": [
            {"tool": "implicit"},
        ]
    }
    handler._validate_payload = lambda path, payload: None
    responses = []
    handler._send = lambda status, data: responses.append((status, data))
    monkeypatch.setattr(http_server, "APP", type("App", (), {"telemetry": Telemetry()})())

    handler.do_POST()

    assert responses == [(
        200,
        {
            "success": True,
            "accepted": 1,
            "rejected": 0,
            "rejection_reasons": {},
        },
    )]
    assert all("tenant" not in event for event in recorded)

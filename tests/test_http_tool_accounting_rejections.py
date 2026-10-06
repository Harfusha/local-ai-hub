from local_ai_hub import http_server


def test_tool_accounting_reports_aggregate_rejections_without_exception_details(monkeypatch):
    class Telemetry:
        def record_tool_accounting(self, event):
            if event["kind"] == "invalid":
                raise ValueError("sensitive prompt text")
            if event["kind"] == "failed":
                raise RuntimeError("private source text")

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
        "events": [{"kind": "accepted"}, {"kind": "invalid"}, {"kind": "failed"}]
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
                "rejected": 2,
                "rejection_reasons": {"invalid_event": 1, "record_failed": 1},
            },
        )
    ]
    assert "sensitive prompt text" not in str(responses)
    assert "private source text" not in str(responses)
    assert handler._telemetry_finished is True

from __future__ import annotations

from local_ai_hub.http_server import Handler, LocalAIHTTPServer


class _RejectSocket:
    def __init__(self):
        self.payload = bytearray()
        self.closed = False

    def sendall(self, data: bytes) -> None:
        self.payload.extend(data)

    def shutdown(self, _how: int) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class _Telemetry:
    def __init__(self):
        self.events: list[dict] = []

    def record_http(self, **event):
        self.events.append(event)


def test_admission_rejection_has_consistent_retry_metadata_and_telemetry(monkeypatch):
    import local_ai_hub.http_server as http_server

    telemetry = _Telemetry()
    monkeypatch.setattr(http_server, "APP", type("App", (), {"telemetry": telemetry})())
    server = LocalAIHTTPServer(("127.0.0.1", 0), Handler, max_handlers=4, overload_wait_seconds=0)
    try:
        for _ in range(4):
            assert server._handler_slots.acquire(blocking=False)
        request = _RejectSocket()
        server.process_request(request, ("127.0.0.1", 1))
        assert Handler.protocol_version == "HTTP/1.1"
        assert b"Retry-After: 1" in bytes(request.payload)
        assert b'"retry_after_seconds":1' in bytes(request.payload)
        assert telemetry.events == [{
            "action": "admission", "duration_ms": 0.0, "success": False,
            "status_code": 503, "error_type": "overload", "retry_count": 0,
        }]
    finally:
        for _ in range(4):
            try:
                server._handler_slots.release()
            except ValueError:
                break
        server.server_close()


def test_host_and_origin_validation(monkeypatch):
    import local_ai_hub.http_server as http_server

    app_mock = type("App", (), {
        "config": {
            "server": {"bind": "127.0.0.1", "client_host": "127.0.0.1"},
            "security": {"allow_remote": False, "allowed_hosts": [], "allowed_origins": []},
        }
    })()
    monkeypatch.setattr(http_server, "APP", app_mock)

    sent = []
    handler = type("MockHandler", (), {
        "headers": {"Host": "127.0.0.1:11435", "Origin": "http://127.0.0.1:11435"},
        "_send": lambda self, status, data: sent.append((status, data)),
    })()

    # Valid loopback Host and Origin
    assert Handler._validate_host_and_origin(handler) is True
    assert not sent

    # Malicious Host (DNS rebinding)
    handler.headers = {"Host": "attacker.com:11435"}
    assert Handler._validate_host_and_origin(handler) is False
    assert sent[-1][0] == 403
    assert "invalid Host header" in sent[-1][1]["error"]

    # Malicious Origin (Cross-origin browser request)
    handler.headers = {"Host": "127.0.0.1:11435", "Origin": "http://evil-site.com"}
    assert Handler._validate_host_and_origin(handler) is False
    assert sent[-1][0] == 403
    assert "cross-origin requests are not allowed" in sent[-1][1]["error"]


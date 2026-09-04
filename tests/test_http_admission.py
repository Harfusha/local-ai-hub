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

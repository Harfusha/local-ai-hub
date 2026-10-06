from __future__ import annotations

from local_ai_hub import http_server


def test_maintenance_get_routes_are_read_only(monkeypatch) -> None:
    calls = []

    class Services:
        def optimize_databases(self):
            calls.append("optimize_databases")

        def purge_stale_cache(self, days):
            calls.append(("purge_stale_cache", days))

        def resolve_all_errors(self):
            calls.append("resolve_all_errors")

    monkeypatch.setattr(http_server, "APP", type("App", (), {"services": Services()})())

    for path in (
        "/api/maintenance/optimize_db",
        "/api/maintenance/purge_cache?days=0",
        "/api/maintenance/resolve_errors",
    ):
        handler = http_server.Handler.__new__(http_server.Handler)
        handler.path = path
        handler._begin_trace = lambda _path: None
        handler._require_authorized = lambda: True
        handler.responses = []
        handler._send = lambda status, data: handler.responses.append((status, data))

        handler.do_GET()

        assert handler.responses == [(405, {"success": False, "error": "method not allowed", "allow": "POST"})]

    assert calls == []

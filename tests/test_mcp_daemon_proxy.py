from __future__ import annotations


def test_stdio_builder_uses_daemon_client_and_preserves_request_identity(monkeypatch) -> None:
    from local_ai_hub import mcp_server

    class ForbiddenInProcessTransport:
        def __init__(self, **_kwargs):
            raise AssertionError("stdio MCP must use the shared daemon HTTP transport")

    monkeypatch.setattr(mcp_server, "InProcessTransport", ForbiddenInProcessTransport)
    client = mcp_server._build_mcp_client("tenant-stdio", None)
    observed: dict[str, object] = {}

    def pooled_open(method, path, _body, headers, _timeout):
        observed.update(method=method, path=path, headers=dict(headers))
        return b'{"success":true}'

    monkeypatch.setattr(client._client, "_pooled_open", pooled_open)
    path = "/api/repo/topology?root=C%3A%2Frepo"
    result = client.get(path, timeout=0.4)

    assert client.auto_start is True
    assert result == {"success": True}
    assert observed["method"] == "GET"
    assert observed["path"] == path
    headers = observed["headers"]
    assert headers["X-LocalAI-Tenant"] == "tenant-stdio"
    assert headers["X-LocalAI-Request-ID"].startswith("req_")


def test_accounting_reporter_close_is_safe_without_owned_client() -> None:
    from local_ai_hub import mcp_server

    reporter = mcp_server._ProtocolAccountingReporter()
    reporter.close()

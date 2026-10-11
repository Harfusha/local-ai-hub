from local_ai_hub import mcp_server


def test_protocol_accounting_queue_binds_client_at_record_time(monkeypatch) -> None:
    reporter = mcp_server._ProtocolAccountingReporter()
    monkeypatch.setattr(reporter, "_ensure_worker", lambda: None)
    client = object()
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    event = {"operation": "repo"}

    reporter.record(event)

    assert reporter._queue.get_nowait() == (event, client)

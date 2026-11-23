import asyncio
import json

import pytest

from local_ai_hub import mcp_server
from local_ai_hub.operation_contracts import operation_tool_output_schema, validate_operation_output


@pytest.mark.parametrize("payload", [{"probe": "ok"}, [], False, 0, None, "text"])
def test_wait_event_preserves_json_message(monkeypatch, payload):
    monkeypatch.setattr(mcp_server.CLIENT, "coord", lambda *args, **kwargs: {
        "success": True, "message": payload, "event": {"payload": payload},
    })
    result = mcp_server.local_ai_coord(action="wait_for_event", root="/repo", topic="test")
    assert result["success"] is True, result
    assert json.dumps(result["message"], sort_keys=True) == json.dumps(payload, sort_keys=True)
    assert validate_operation_output("local_ai_coord", "wait_for_event", result) is None


def test_wait_output_schema_accepts_json_without_relaxing_other_actions():
    coord = operation_tool_output_schema("local_ai_coord")
    assert coord["properties"]["message"] == {}
    assert validate_operation_output("local_ai_coord", "semaphore_status", {"message": {}})
    assert validate_operation_output("local_ai_repo", "search", {"message": {}})


def test_wait_event_wire_preserves_authored_diagnostic_keys(monkeypatch):
    payload = {"debug": {"raw": []}, "telemetry": None, "_lah_custom": False}
    monkeypatch.setattr(mcp_server.CLIENT, "coord", lambda *args, **kwargs: {
        "success": True, "message": payload, "event": {"payload": payload},
    })
    content, structured = asyncio.run(mcp_server.mcp.call_tool(
        "local_ai_coord", {"action": "wait_for_event", "root": "/repo", "topic": "test"},
    ))
    assert structured["success"] is True, structured
    assert structured["message"] == payload
    assert structured["event"]["payload"] == payload
    assert json.loads(content[0].text)["message"] == payload


def test_wait_event_budget_does_not_return_partial_message(monkeypatch):
    payload = {"large": "abc123" * 4000}
    monkeypatch.setattr(mcp_server.CLIENT, "coord", lambda *args, **kwargs: {
        "success": True, "message": payload, "event": {"payload": payload},
    })
    _, structured = asyncio.run(mcp_server.mcp.call_tool(
        "local_ai_coord", {"action": "wait_for_event", "root": "/repo", "topic": "test", "max_response_tokens": 256},
    ))
    assert structured.get("success") is False, structured


def test_wait_event_loopback_mcp_delivery(tmp_path, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from local_ai_hub import http_server
    from local_ai_hub.agent_events import SwarmPubSub
    from local_ai_hub.app import LocalAIApp
    from local_ai_hub.client import HubClient

    monkeypatch.setattr(SwarmPubSub, "_instance", None)
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    config = tmp_path / "hub-test.toml"
    config.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = {server.server_address[1]}\n'
        f'state_dir = "{(tmp_path / "state").as_posix()}"\n'
        f'[agent_state]\nenabled = true\n[security]\nallowed_roots = ["{tmp_path.as_posix()}"]\n',
        encoding="utf-8",
    )
    app = LocalAIApp(str(config))
    monkeypatch.setattr(http_server, "APP", app)
    bus = SwarmPubSub.get_default(state_store=app.agent_state)
    original_subscribe = bus.subscribe
    ready = threading.Event()

    def subscribe(topic, maxsize=100):
        result = original_subscribe(topic, maxsize)
        ready.set()
        return result

    monkeypatch.setattr(bus, "subscribe", subscribe)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    client = HubClient(config_path=str(config), auto_start=False)
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server.FEATURES, "agent_os", True)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_: None)
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda _event: None)
    payload = {"token": None, "debug": {"raw": []}, "telemetry": False}
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(lambda: asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", {
                "action": "wait_for_event", "root": str(tmp_path), "topic": "integration",
                "timeout": 5, "filter": {"token": None},
            })))
            assert ready.wait(3), "waiter did not register"
            first = client.coord(action="pubsub_publish", root=str(tmp_path), topic="integration", message={}, publisher="test")
            assert first["success"] is True
            second = client.coord(action="pubsub_publish", root=str(tmp_path), topic="integration", message=payload, publisher="test")
            assert second["success"] is True
            contents, result = waiting.result(timeout=6)
        assert result["success"] is True, result
        assert result["message"] == payload
        assert result["event"]["payload"] == payload
        assert result["event"]["message"] == payload
        assert json.loads(contents[0].text)["message"] == payload
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=3)
        app.close()

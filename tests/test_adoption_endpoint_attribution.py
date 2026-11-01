from local_ai_hub import mcp_server
from local_ai_hub.endpoint_stats import EndpointStatsStore


def test_bypass_signal_is_not_counted_as_target_tool_call(monkeypatch):
    class Collector:
        def __init__(self):
            self.events = []

        def record(self, *args, **kwargs):
            self.events.append((args, kwargs))

        def record_call(self, **kwargs):
            self.events.append(kwargs)

    adoption, endpoints = Collector(), Collector()
    monkeypatch.setattr(mcp_server, "ADOPTION_METRICS", adoption)
    monkeypatch.setattr(mcp_server, "ENDPOINT_STATS", endpoints)
    mcp_server._record_adoption("local_ai_status", {
        "adoption_signal": "bypassed", "target_tool": "local_ai_task", "target_action": "review",
    }, {"success": True}, 1)

    assert adoption.events[0][0][0:2] == ("local_ai_task", "review")
    assert endpoints.events[0]["item_name"] == "local_ai_status"
    assert endpoints.events[0]["success"] is True


def test_event_identity_deduplicates_across_store_instances(tmp_path):
    first = EndpointStatsStore(tmp_path)
    second = EndpointStatsStore(tmp_path)
    event = dict(item_type="mcp", item_name="local_ai_task:review", duration_ms=11,
                 success=True, root=str(tmp_path), event_id="call-1")
    first.record_call(**event)
    second.record_call(**event)
    second.record_call(**{**event, "event_id": "call-2", "success": False})
    items = first.get_stats(root=str(tmp_path))["items"]
    row = next(item for item in items if item["name"] == "local_ai_task:review")
    assert (row["calls"], row["success_calls"], row["fail_calls"]) == (2, 1, 1)


def test_concurrent_recorders_count_one_event(tmp_path):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    stores = [EndpointStatsStore(tmp_path), EndpointStatsStore(tmp_path)]
    barrier = threading.Barrier(2)

    def record(store):
        barrier.wait(timeout=5)
        store.record_call(item_type="mcp", item_name="local_ai_task:review", duration_ms=1,
                          root=str(tmp_path), event_id="concurrent-call")

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(record, stores))
    items = stores[0].get_stats(root=str(tmp_path))["items"]
    row = next(item for item in items if item["name"] == "local_ai_task:review")
    assert row["calls"] == 1


def test_accounting_event_retains_actual_call_identity(monkeypatch, tmp_path):
    events = []
    monkeypatch.setattr(mcp_server, "_ACCOUNTING_REPORTER", type("Reporter", (), {"record": lambda self, event: events.append(event)})())
    monkeypatch.setattr(mcp_server, "CONTEXT_LEDGER", type("Ledger", (), {"record": lambda self, **kwargs: None, "adaptive_profile": lambda self, profile: profile})())
    mcp_server._record_tool_accounting(
        tool_name="local_ai_task", arguments={"action": "review", "root": str(tmp_path), "task": "private prompt marker"},
        response={"success": True, "text": "private output marker"}, measured={}, metadata={}, event_id="call-1",
        duration_ms=12, call_success=True,
    )
    assert events[0]["event_id"] == "call-1"
    assert events[0]["operation"] == "review"
    assert events[0]["root"] == str(tmp_path)
    assert events[0]["success"] is True
    assert "private prompt marker" not in str(events[0])
    assert "private output marker" not in str(events[0])


def test_raised_tool_exception_reports_same_failed_call_identity(monkeypatch, tmp_path):
    import pytest

    direct, reported = [], []
    monkeypatch.setattr(mcp_server, "_record_adoption", lambda *args, **kwargs: direct.append(kwargs))
    monkeypatch.setattr(mcp_server, "_ACCOUNTING_REPORTER", type("Reporter", (), {"record": lambda self, event: reported.append(event)})())
    monkeypatch.setattr(mcp_server, "CONTEXT_LEDGER", type("Ledger", (), {"record": lambda self, **kwargs: None})())
    monkeypatch.setattr(mcp_server, "configured_state_dir", lambda *args, **kwargs: tmp_path)
    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda path: object())
    monkeypatch.setattr(mcp_server, "_classify_mcp_operation", lambda *args: ("task", False))
    monkeypatch.setattr(mcp_server, "operational_mode_gate_error", lambda *args, **kwargs: None)
    monkeypatch.setattr(mcp_server, "detailed_diagnostics_enabled", lambda cfg: True)

    @mcp_server._instrumented_tool()
    def local_ai_task(root, action):
        raise RuntimeError("failed")

    with pytest.raises(RuntimeError):
        local_ai_task(str(tmp_path), "review")
    assert reported[0]["success"] is False
    assert reported[0]["event_id"] == direct[0]["event_id"]


def test_successful_tool_preserves_identity_until_deferred_wire_accounting(monkeypatch, tmp_path):
    direct = []
    monkeypatch.setattr(mcp_server, "_record_adoption", lambda *args, **kwargs: direct.append(kwargs))
    monkeypatch.setattr(mcp_server, "configured_state_dir", lambda *args, **kwargs: tmp_path)
    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda path: object())
    monkeypatch.setattr(mcp_server, "_classify_mcp_operation", lambda *args: ("task", False))
    monkeypatch.setattr(mcp_server, "operational_mode_gate_error", lambda *args, **kwargs: None)
    monkeypatch.setattr(mcp_server, "detailed_diagnostics_enabled", lambda cfg: True)
    monkeypatch.setattr(mcp_server, "_agent_output", lambda value, *args: value)
    monkeypatch.setattr(mcp_server, "validate_operation_output", lambda *args: None)

    @mcp_server._instrumented_tool()
    def local_ai_task(root, action):
        return {"success": True}

    pending = []
    token = mcp_server._PENDING_MCP_ACCOUNTING.set(pending)
    try:
        assert local_ai_task(str(tmp_path), "review")["success"] is True
    finally:
        mcp_server._PENDING_MCP_ACCOUNTING.reset(token)
    assert pending[0]["event_id"] == direct[0]["event_id"]
    assert pending[0]["call_success"] is True


def test_invalid_mcp_action_is_recorded_as_failed_attempt(monkeypatch):
    import asyncio
    reported = []
    monkeypatch.setattr(mcp_server, "_ACCOUNTING_REPORTER", type("Reporter", (), {"record": lambda self, event: reported.append(event)})())
    monkeypatch.setattr(mcp_server, "CONTEXT_LEDGER", type("Ledger", (), {"record": lambda self, **kwargs: None, "adaptive_profile": lambda self, profile: profile})())
    asyncio.run(mcp_server.mcp.call_tool("local_ai_task", {"action": "not_an_action"}))
    assert len(reported) == 1
    assert reported[0]["operation"] == "not_an_action"
    assert reported[0]["success"] is False
    assert reported[0]["event_id"]


def test_direct_and_http_accounting_share_one_endpoint_event(tmp_path, monkeypatch):
    import json
    import threading
    import urllib.request
    from local_ai_hub import http_server
    from local_ai_hub.app import LocalAIApp

    state = tmp_path / "state"
    config = tmp_path / "config.toml"
    config.write_text(f'[server]\nbind = "127.0.0.1"\nport = 11498\nstate_dir = "{state.as_posix()}"\n', encoding="utf-8")
    app = LocalAIApp(str(config))
    previous = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        event = {"tool": "local_ai_task", "operation": "review", "root": str(tmp_path),
                 "event_id": "event-1", "duration_ms": 15, "success": True}
        app.endpoint_stats.record_call(item_type="mcp", item_name="local_ai_task:review",
                                       root=str(tmp_path), duration_ms=15, event_id="event-1")
        failed = {**event, "event_id": "event-2", "success": False}
        data = json.dumps({"events": [event, failed]}).encode()
        request = urllib.request.Request(f"http://127.0.0.1:{server.server_address[1]}/api/telemetry/tool-accounting",
                                         data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=5) as response:
            assert json.loads(response.read())["accepted"] == 2
        unattributed = json.dumps({"events": [{"tool": "local_ai_repo", "success": True}]}).encode()
        request = urllib.request.Request(f"http://127.0.0.1:{server.server_address[1]}/api/telemetry/tool-accounting",
                                         data=unattributed, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=5) as response:
            assert json.loads(response.read())["accepted"] == 1
        items = app.endpoint_stats.get_stats(root=str(tmp_path))["items"]
        row = next(item for item in items if item["name"] == "local_ai_task:review")
        assert (row["calls"], row["success_calls"], row["fail_calls"]) == (2, 1, 1)
        assert not any(item["name"] == "local_ai_repo" and item["calls"] for item in items)
    finally:
        server.shutdown()
        server.server_close()
        http_server.APP = previous
        app.close()


def test_actual_mcp_call_and_http_report_count_once_without_inference(tmp_path, monkeypatch):
    import asyncio
    import threading
    from types import SimpleNamespace
    from local_ai_hub import http_server
    from local_ai_hub.app import LocalAIApp
    from local_ai_hub.client import HubClient
    from test_work_orchestrator import init_repo

    root = init_repo(tmp_path)
    state = tmp_path / "state"
    config = tmp_path / "config.toml"
    config.write_text(f'[server]\nbind = "127.0.0.1"\nport = 11498\nstate_dir = "{state.as_posix()}"\n'
                      f'[security]\nallowed_roots = ["{root.as_posix()}"]\n'
                      '[ollama]\nenabled = false\n[observability]\nenabled = true\n', encoding="utf-8")
    app = LocalAIApp(str(config))
    previous = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client_config = tmp_path / "client.toml"
    client_config.write_text(f'[server]\nbind = "127.0.0.1"\nport = {server.server_address[1]}\n'
                             f'state_dir = "{state.as_posix()}"\n', encoding="utf-8")
    client = mcp_server._MCPHubClientAdapter(HubClient(config_path=str(client_config), auto_start=False))
    delivered = threading.Event()

    class ObservedClient:
        def __getattr__(self, name):
            return getattr(client, name)
        def post(self, path, payload, **kwargs):
            result = client.post(path, payload, **kwargs)
            if path == "/api/telemetry/tool-accounting" and result.get("accepted"):
                delivered.set()
            return result

    reporter = mcp_server._ProtocolAccountingReporter()
    monkeypatch.setattr(mcp_server, "CLIENT", ObservedClient())
    monkeypatch.setattr(mcp_server, "CFG", app.config)
    monkeypatch.setattr(mcp_server, "ENDPOINT_STATS", app.endpoint_stats)
    monkeypatch.setattr(mcp_server, "_ACCOUNTING_REPORTER", reporter)
    monkeypatch.setattr(mcp_server, "ADOPTION_METRICS", SimpleNamespace(record=lambda *a, **k: None))
    monkeypatch.setattr(mcp_server, "CONTEXT_LEDGER", SimpleNamespace(record=lambda **k: None,
                                                                        adaptive_profile=lambda p: p))
    for method in ("request", "request_stream", "request_interruptible"):
        monkeypatch.setattr(app.runtime, method, lambda *a, **k: (_ for _ in ()).throw(AssertionError("unexpected inference")))
    try:
        response = asyncio.run(mcp_server.mcp.call_tool("local_ai_repo", {
            "action": "git_status", "root": str(root), "max_response_tokens": 1600,
        }))
        assert response[1]["success"] is True, response
        assert delivered.wait(5), ("accounting HTTP report was not accepted", reporter._queue.qsize(),
                                   app.endpoint_stats.get_stats(root=str(root))["items"])
        items = app.endpoint_stats.get_stats(root=str(root))["items"]
        row = next(item for item in items if item["name"] == "local_ai_repo:git_status")
        assert (row["calls"], row["success_calls"], row["fail_calls"]) == (1, 1, 0)
    finally:
        reporter.close()
        server.shutdown()
        server.server_close()
        http_server.APP = previous
        app.close()

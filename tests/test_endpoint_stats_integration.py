from __future__ import annotations

import time
from pathlib import Path

from local_ai_hub.endpoint_stats import EndpointStatsStore, get_registered_surface_catalog


def test_endpoint_and_mcp_stats_integration(tmp_path: Path):
    state_dir = tmp_path / "state"
    store = EndpointStatsStore(state_dir)
    root = str(tmp_path / "demo-proj")

    # Simulate HTTP endpoints recording
    endpoints = ["/api/search", "/api/models", "/api/chat", "/health"]
    for i, ep in enumerate(endpoints):
        for call_idx in range(i + 1):
            succ = (call_idx % 2 == 0) or ep == "/health"
            dur = 15.0 * (call_idx + 1)
            store.record_call(item_type="endpoint", item_name=ep, duration_ms=dur, success=succ, root=root)

    # Simulate MCP tool recording
    mcp_tools = ["local_ai_status", "local_ai_repo:context", "local_ai_coord:task_create"]
    for tool in mcp_tools:
        store.record_call(item_type="mcp", item_name=tool, duration_ms=120.0, success=True, root=root)

    stats = store.get_stats(root=root)
    assert stats["success"] is True
    assert stats["is_global"] is False
    assert stats["root"].endswith(":demo-proj")

    items_map = {it["name"]: it for it in stats["items"]}
    assert items_map["/health"]["calls"] == 4
    assert items_map["/health"]["success_rate"] == 100.0
    assert items_map["/api/search"]["calls"] == 1
    assert items_map["local_ai_status"]["calls"] == 1
    assert items_map["local_ai_repo:context"]["calls"] == 1
    assert items_map["local_ai_coord:task_create"]["calls"] == 1

    # Verify uncalled registered items show 0 calls
    catalog = get_registered_surface_catalog()
    assert len(catalog) > 10
    uncalled = [it for it in stats["items"] if it["calls"] == 0]
    assert len(uncalled) > 0
    for u in uncalled:
        assert u["status"] == "unused"
        assert u["p50_ms"] == 0.0
        assert u["success_rate"] is None


def test_http_endpoint_stats_selector_and_reset_isolate_same_named_roots(tmp_path, monkeypatch):
    import json
    import threading
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen

    from local_ai_hub import http_server
    from local_ai_hub.app import LocalAIApp

    config = tmp_path / "isolated.toml"
    config.write_text("[local_ai_hub]\nconfig_schema_version = 1\n[server]\nstate_dir = " + json.dumps(str(tmp_path / "state"))
        + "\nauto_start_ollama = false\n[ollama]\nenabled = false\n[smart_ollama]\nenabled = false"
        + "\n[observability]\nenabled = false\n[background_gpu]\nenabled = false"
        + "\n[preprocessing]\nenabled = false\n", encoding="utf-8")
    app = LocalAIApp(str(config))
    app.endpoint_stats = EndpointStatsStore(tmp_path / "endpoint-state")
    monkeypatch.setattr(http_server, "APP", app)
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    root1, root2 = str(tmp_path / "a" / "shared"), str(tmp_path / "b" / "shared")
    try:
        for root in (root1, root2):
            app.endpoint_stats.record_call(item_type="mcp", item_name="test:isolated", duration_ms=2, root=root)
        def get(root):
            with urlopen(base + "/api/telemetry/endpoint-stats?" + urlencode({"root": root, "unused": "0"}), timeout=5) as response:
                return json.load(response)
        first = get(root1)
        second = get(root2)
        assert first.get("success") is True and "root" in first, first
        assert first["root"] != second["root"]
        assert get(first["root"])["items"][0]["calls"] == 1
        request = Request(base + "/api/telemetry/endpoint-stats/reset", data=json.dumps({"root": first["root"]}).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=5) as response:
            assert json.load(response)["success"] is True
        assert get(root1)["items"] == []
        assert get(root2)["items"][0]["calls"] == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        app.close()




def test_distinct_exact_project_filters_over_http(tmp_path, monkeypatch):
    import json
    import threading
    import urllib.parse
    import urllib.request
    from local_ai_hub import http_server
    from local_ai_hub.app import LocalAIApp

    config = tmp_path / "isolated.toml"
    config.write_text("[local_ai_hub]\nconfig_schema_version = 1\n[server]\nstate_dir = " + json.dumps(str(tmp_path / "state"))
        + "\nauto_start_ollama = false\n[ollama]\nenabled = false\n[smart_ollama]\nenabled = false"
        + "\n[observability]\nenabled = false\n[background_gpu]\nenabled = false"
        + "\n[preprocessing]\nenabled = false\n", encoding="utf-8")
    app = LocalAIApp(str(config))
    app.endpoint_stats = EndpointStatsStore(tmp_path / "endpoint-state")
    for folder, calls in (("a", 1), ("b", 2)):
        root = tmp_path / folder / "shared"
        root.mkdir(parents=True)
        for _ in range(calls):
            app.endpoint_stats.record_call(item_type="mcp", item_name="test:visual", duration_ms=1, root=str(root))
    monkeypatch.setattr(http_server, "APP", app)
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for folder, count in (("a", 1), ("b", 2)):
            query = urllib.parse.urlencode({"root": str(tmp_path / folder / "shared")})
            with urllib.request.urlopen(f"http://127.0.0.1:{server.server_address[1]}/api/endpoint-stats?{query}", timeout=10) as response:
                payload = json.load(response)
            # The exact-root contract must not merge identically named projects.
            def rows(value):
                if isinstance(value, dict):
                    if value.get("item_name", value.get("name")) == "test:visual":
                        yield value
                    for child in value.values():
                        yield from rows(child)
                elif isinstance(value, list):
                    for child in value:
                        yield from rows(child)
            matching = list(rows(payload))
            assert matching, payload
            assert all(row.get("calls", row.get("count", row.get("total_calls"))) == count for row in matching), matching
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        app.close()

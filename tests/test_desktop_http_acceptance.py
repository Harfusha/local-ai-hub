"""Real local HTTP + actual desktop IPC subprocess; no external models or production state."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading

from local_ai_hub import http_server
from local_ai_hub.app import LocalAIApp
from local_ai_hub.endpoint_stats import EndpointStatsStore

ROOT = Path(__file__).resolve().parents[1]


def test_desktop_bridge_roundtrip_and_scoped_reset(tmp_path, monkeypatch):
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    app = None
    thread = None
    config = tmp_path / "isolated.toml"
    roots = [tmp_path / "a" / "shared", tmp_path / "b" / "shared"]
    for root in roots:
        root.mkdir(parents=True)
    config.write_text(
        "[local_ai_hub]\nconfig_schema_version = 1\n[server]\n"
        + "port = " + str(server.server_address[1]) + "\n"
        + "state_dir = " + json.dumps(str(tmp_path / "state"))
        + "\nauto_start_ollama = false\n[ollama]\nenabled = false\n[smart_ollama]\nenabled = false"
        + "\n[observability]\nenabled = false\n[background_gpu]\nenabled = false"
        + "\n[preprocessing]\nenabled = false\n",
        encoding="utf-8",
    )

    def call(op, **args):
        env = os.environ.copy()
        env["LOCAL_AI_CONFIG"] = str(config)
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/desktop.py"), "--bridge", "--config", str(config)],
            input=json.dumps({"op": op, "args": args}), capture_output=True,
            text=True, encoding="utf-8", timeout=40, env=env, cwd=ROOT, check=True,
        )
        return json.loads(result.stdout)

    try:
        app = LocalAIApp(str(config))
        app.endpoint_stats = EndpointStatsStore(tmp_path / "endpoint-state")
        monkeypatch.setattr(http_server, "APP", app)
        for root in roots:
            app.endpoint_stats.record_call(item_type="mcp", item_name="test:isolated", duration_ms=2, root=str(root))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        probe = call("probe")
        assert probe["ok"] and probe["result"]["online"] is True, probe
        first = call("read", view="Endpoint analytics", root=str(roots[0]))
        second = call("read", view="Endpoint analytics", root=str(roots[1]))
        assert first["ok"] and second["ok"], (first, second)
        assert first["result"]["root"] != second["result"]["root"]
        def recorded(response):
            return sum(item["calls"] for item in response["result"]["items"]
                       if item["name"] == "test:isolated" and item["type"] == "mcp")
        assert recorded(first) == 1
        assert recorded(second) == 1
        rejected = call("endpoint_reset", root=str(roots[0]))
        assert rejected["ok"] is False
        reset = call("endpoint_reset", root=str(roots[0]), confirmed=True)
        assert reset["ok"] and reset["result"]["reset"] is True, reset
        first = call("read", view="Endpoint analytics", root=str(roots[0]))
        second = call("read", view="Endpoint analytics", root=str(roots[1]))
        assert first["ok"] and second["ok"], (first, second)
        assert recorded(first) == 0
        assert recorded(second) == 1
    finally:
        if thread is not None:
            server.shutdown()
            thread.join(timeout=3)
        server.server_close()
        if app is not None:
            app.close()
    # The adapter is no longer connected; a read must not launch a new service.
    # The existing client is auto_start=False, verified by the unit contract too.
    result = call("probe")
    assert result["ok"] and result["result"]["online"] is False
    result = call("read", view="Endpoint analytics", root=str(roots[0]))
    assert result["ok"] is False

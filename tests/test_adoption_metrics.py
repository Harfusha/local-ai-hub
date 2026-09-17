from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import inspect
from pathlib import Path
import subprocess
import threading
import urllib.request

import pytest

from local_ai_hub.adoption_metrics import AdoptionMetricsStore


def test_records_bucketed_daily_outcomes_and_reasons(tmp_path):
    store = AdoptionMetricsStore(tmp_path, retention_days=14)
    now = datetime(2026, 9, 17, 10, tzinfo=timezone.utc)

    store.record("local_ai_repo", "search", "repository", "used", duration_ms=18, output_size=80, now=now)
    store.record("local_ai_repo", "search", "repository", "blocked", fallback_reason="policy", duration_ms=310, output_size=1100, now=now)
    store.record("local_ai_command", "run", "validation", "failed", fallback_reason="timeout", now=now)
    store.record_explicit_bypass("local_ai_repo", "search", "repository", reason="explicit_client_signal", now=now)

    report = store.report(days=7, now=now)
    today = report["daily"][-1]
    assert today["used"] == 1
    assert today["blocked"] == 1
    assert today["failed"] == 1
    assert today["bypassed"] == 1
    assert report["blocked_reasons"] == [{"reason": "policy", "count": 1}]
    assert report["terminal_failures"] == [{"reason": "timeout", "count": 1}]
    assert report["latency_buckets"] == [{"bucket": "0-50ms", "count": 1}, {"bucket": "251-500ms", "count": 1}]
    assert report["output_size_buckets"] == [{"bucket": "0-255B", "count": 1}, {"bucket": "1-4KiB", "count": 1}]


def test_rejects_sensitive_or_path_bearing_input(tmp_path):
    store = AdoptionMetricsStore(tmp_path)

    with pytest.raises(ValueError, match="safe normalized"):
        store.record("local_ai_repo", "search", "C:/Users/Adam/project", "used")
    with pytest.raises(ValueError, match="safe normalized"):
        store.record("local_ai_repo", "search", "prompt", "used", prompt="secret")
    with pytest.raises(ValueError, match="safe fallback"):
        store.record("local_ai_repo", "search", "repository", "blocked", fallback_reason="token=secret")


def test_retention_and_dormant_actions(tmp_path):
    store = AdoptionMetricsStore(tmp_path, retention_days=2)
    now = datetime(2026, 9, 17, tzinfo=timezone.utc)
    store.record("local_ai_repo", "search", "repository", "used", now=now - timedelta(days=4))
    store.record("local_ai_repo", "context", "repository", "used", now=now - timedelta(days=3))
    store.record("local_ai_repo", "search", "repository", "used", now=now)

    report = store.report(days=2, now=now)
    assert report["totals"]["used"] == 1
    assert report["dormant_actions"] == ["local_ai_repo:context"]


def test_http_adoption_endpoint_returns_aggregates_only(tmp_path):
    from local_ai_hub import http_server
    from local_ai_hub.app import LocalAIApp

    state_dir = tmp_path / "state"
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'[server]\nbind = "127.0.0.1"\nport = 11498\nstate_dir = "{state_dir.as_posix()}"\n', encoding="utf-8")
    app = LocalAIApp(str(cfg))
    app.services.adoption_metrics.record("local_ai_repo", "search", "repository", "used")
    previous = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{server.server_address[1]}/api/adoption") as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["success"] is True
        assert payload["adoption"]["totals"]["used"] == 1
        assert "events" not in json.dumps(payload).lower()
    finally:
        server.shutdown(); server.server_close(); http_server.APP = previous; app.close()


def test_dashboard_renders_adoption_response_body():
    from local_ai_hub import dashboard

    script = r'''
const html=require('fs').readFileSync(process.argv[1],'utf8');
const boxes={}; global.$=(id)=>boxes[id]||(boxes[id]={textContent:'',children:[],replaceChildren(){this.children=[]},append(...items){this.children.push(...items)}});
global.document={createElement:(tag)=>({tag,textContent:'',children:[],append(...items){this.children.push(...items)}})};
global.apiToken=''; global.prompt=()=>'';
global.nativeFetch=async()=>new Response(JSON.stringify({available:true,adoption:{totals:{used:3,bypassed:2,blocked:1,failed:4},action_adoption:[{tool:'local_ai_repo',action:'search',outcome:'used',count:3}],dormant_actions:['local_ai_repo:context'],blocked_reasons:[],terminal_failures:[],latency_buckets:[],output_size_buckets:[]}}));
const api=html.slice(html.indexOf('async function apiFetch'),html.indexOf('const rows='));
const adoption=html.slice(html.indexOf('function renderAdoption'),html.indexOf('function render(s)'));
eval(api); eval(adoption);
(async()=>{await refreshAdoption();const row=boxes.adoptionActions.children[0];if(boxes.adoptionUsed.textContent!=='3 / 2'||boxes.adoptionBlocked.textContent!=='1 / 4'||String(boxes.adoptionDormant.textContent)!=='1'||!row||row.children[0].textContent!=='local_ai_repo'||row.children[1].textContent!=='search')process.exit(1)})();
'''
    result = subprocess.run(["node", "-e", script, str(Path(dashboard.__file__))], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_mcp_explicit_bypass_report_uses_target_without_inference(tmp_path, monkeypatch):
    from local_ai_hub import mcp_server

    store = AdoptionMetricsStore(tmp_path)
    monkeypatch.setattr(mcp_server, "ADOPTION_METRICS", store)
    monkeypatch.setattr(mcp_server.CLIENT, "get", lambda *_args, **_kwargs: {"success": True})
    monkeypatch.setattr(mcp_server.FEATURES, "status", True)

    mcp_server.local_ai_status(adoption_signal="bypassed", target_tool="local_ai_repo", target_action="search")
    mcp_server.local_ai_status()
    invalid = mcp_server.local_ai_status(adoption_signal="bypassed", target_tool="C:/unsafe", target_action="search")
    unavailable_action = mcp_server.local_ai_status(adoption_signal="bypassed", target_tool="local_ai_repo", target_action="not_real")
    report = store.report(days=1)
    assert "adoption_signal" in inspect.signature(mcp_server.local_ai_status).parameters
    assert "target_tool" in inspect.signature(mcp_server.local_ai_status).parameters
    assert invalid["success"] is False
    assert unavailable_action["success"] is False
    assert report["totals"]["bypassed"] == 1
    assert sum(report["totals"].values()) == 4
    assert {"tool": "local_ai_repo", "action": "search", "outcome": "bypassed", "count": 1} in report["action_adoption"]

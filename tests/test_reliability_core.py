from __future__ import annotations

import io
import inspect
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from html.parser import HTMLParser
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub import __version__
from local_ai_hub.app import LocalAIApp
from local_ai_hub.cache import SQLiteCache
from local_ai_hub.commands import CommandBroker
from local_ai_hub.config import ConfigError, load_config
from local_ai_hub.external_tools import ExternalCodeIntelligence
from local_ai_hub.semantic_cache import SemanticGenerationCache

ROOT = Path(__file__).resolve().parents[1]


def _config(tmp_path: Path, extra: str = "") -> Path:
    path = tmp_path / "config.toml"
    path.write_text(
        f'''[server]\nbind="127.0.0.1"\nport=11435\nstate_dir="{(tmp_path / 'state').as_posix()}"\nauto_start_ollama=false\nmax_request_body_bytes=4096\n\n[hardware]\nprofile="cpu"\nauto_tune=false\n\n[prewarm]\nenabled=false\n\n[preprocessing]\nenabled=false\n\n[resilience]\nwatchdog_enabled=false\n\n[code_intelligence]\nenabled=false\n\n[background_gpu]\nenabled=false\n\n[observability]\nenabled=false\n\n{extra}\n''',
        encoding="utf-8",
    )
    return path


def test_invalid_explicit_config_fails_fast(tmp_path: Path):
    bad = tmp_path / "bad.toml"
    bad.write_text("[server\nport=99999", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(bad)
    with pytest.raises(ConfigError):
        load_config(tmp_path / "missing.toml")


def test_config_validates_transport_limits(tmp_path: Path):
    bad = tmp_path / "bad.toml"
    bad.write_text('[server]\nport=70000\n[hardware]\nprofile="cpu"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="server.port"):
        load_config(bad)




def test_runtime_config_sidecar_preserves_primary_config(tmp_path: Path):
    from local_ai_hub.config import save_runtime_overrides
    cfg = _config(tmp_path)
    original = cfg.read_text(encoding="utf-8")
    target = save_runtime_overrides(cfg, {"hardware": {"profile": "low"}, "preprocessing": {"enabled": True}})
    assert cfg.read_text(encoding="utf-8") == original
    assert target.name == "config.runtime.toml"
    merged = load_config(cfg)
    assert merged["hardware"]["profile"] == "low"
    assert merged["preprocessing"]["enabled"] is True
    save_runtime_overrides(cfg, {}, reset=True)
    assert not target.exists()


def test_mcp_resolve_imports_defaults_to_auto():
    source = (ROOT / "src" / "local_ai_hub" / "mcp_server.py").read_text(encoding="utf-8")
    assert 'language: str = "auto"' in source
    assert '"language": language or "auto"' in source


def test_sqlite_cache_updates_lru_metadata_and_drops_bad_json(tmp_path: Path):
    cache = SQLiteCache(tmp_path / "cache.sqlite3", "x", ttl_seconds=60, max_entries=10)
    cache.set("a", {"value": 1})
    assert cache.get("a") == {"value": 1}
    with closing(sqlite3.connect(cache.path)) as con:
        row = con.execute("SELECT hits,accessed_at,created_at FROM cache_entries WHERE namespace=? AND cache_key='a'", (cache.namespace,)).fetchone()
        assert row and row[0] == 1 and row[1] >= row[2]
        con.execute("INSERT OR REPLACE INTO cache_entries(namespace,cache_key,value_json,created_at,accessed_at,hits) VALUES(?, 'bad', '{', 1, 1, 0)", (cache.namespace,))
        con.commit()
    assert cache.get("bad") is None
    with closing(sqlite3.connect(cache.path)) as con:
        assert con.execute("SELECT COUNT(*) FROM cache_entries WHERE cache_key='bad'").fetchone()[0] == 0


class _Artifacts:
    def put(self, *args, **kwargs):
        return {"artifact_id": "x"}


class _RepoState:
    def fingerprint(self, cwd: str):
        return {"fingerprint": "f", "kind": "test"}


def test_command_policy_is_fail_closed_for_arbitrary_scripts(tmp_path: Path):
    cfg = load_config(_config(tmp_path))
    broker = CommandBroker(cfg, _Artifacts(), _RepoState())
    assert broker.classify("npm test")["allowed"] is True
    assert broker.classify("npm run build")["class"] == "build"
    assert broker.classify("npm run deploy")["allowed"] is False
    assert broker.classify("npm install")["class"] == "mutating"
    assert broker.classify("make test")["allowed"] is True
    assert broker.classify("make clean")["allowed"] is False
    assert broker.classify("cargo fmt")["allowed"] is False
    assert broker.classify("cargo fmt -- --check")["class"] == "validation"
    assert broker.classify("go mod tidy")["allowed"] is False


class _FakeClient:
    instances: list["_FakeClient"] = []
    def __init__(self, command, **kwargs):
        self.closed = False
        self.cwd = kwargs.get("cwd")
        self.__class__.instances.append(self)
    def close(self): self.closed = True
    def reset(self): self.closed = True
    def call_tool(self, name, args, timeout=None): return {"success": True, "result": {"name": name}}


def test_external_sessions_are_bounded_lru(monkeypatch, tmp_path: Path):
    import local_ai_hub.external_tools as mod
    _FakeClient.instances = []
    monkeypatch.setattr(mod, "MCPStdioClient", _FakeClient)
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "code_intelligence": {
            "enabled": True, "serena_enabled": False, "codegraph_enabled": True,
            "codegraph_command": sys.executable, "max_sessions_per_backend": 1, "session_idle_ttl_seconds": 3600,
        },
    }
    ext = ExternalCodeIntelligence(cfg)
    roots = [tmp_path / "a", tmp_path / "b"]
    for root in roots: root.mkdir()
    ext.query_codegraph(str(roots[0]), "search", "x")
    first = _FakeClient.instances[0]
    ext.query_codegraph(str(roots[1]), "search", "x")
    assert len(ext._codegraph_sessions) == 1
    assert first.closed is True
    assert ext.status()["session_policy"]["max_per_backend"] == 1
    reset = ext.reset_sessions("all")
    assert reset["success"] is True and reset["removed"]["codegraph"] == 1


def test_semantic_cache_blob_decode_has_stdlib_fallback():
    import struct
    raw = struct.pack("<3f", 1.25, -2.0, 3.5)
    assert SemanticGenerationCache._decode_vector(raw) == pytest.approx([1.25, -2.0, 3.5])


def test_code_index_query_and_multilanguage_import_resolution(tmp_path: Path):
    app = LocalAIApp(str(_config(tmp_path)))
    repo = tmp_path / "repo"; (repo / "pkg").mkdir(parents=True); (repo / "src").mkdir()
    (repo / "pkg" / "alpha.py").write_text("class AlphaService:\n    pass\n", encoding="utf-8")
    (repo / "src" / "Beta.cs").write_text("namespace Demo.Tools\n{\n    public class BetaService {}\n}\n", encoding="utf-8")
    (repo / "src" / "gamma.ts").write_text("export class GammaService {}\n", encoding="utf-8")
    try:
        for rel in ("pkg/alpha.py", "src/Beta.cs", "src/gamma.ts"):
            app.code_index.update_file(str(repo), rel)
        out = app.services.code_query(str(repo), "AlphaService", 10)
        assert out["success"] is True
        assert any(x["name"] == "AlphaService" for x in out["symbols"])
        imports = app.deterministic.resolve_imports(str(repo), ["AlphaService", "BetaService", "GammaService"], "auto")
        assert imports["success"] is True
        statements = "\n".join(imports["import_statements"])
        assert "from pkg.alpha import AlphaService" in statements
        assert "using Demo.Tools;" in statements
        assert "GammaService" in statements and "src/gamma" in statements
    finally:
        app.close()


def test_code_index_parser_uses_linear_brace_metadata_for_nested_blocks():
    from local_ai_hub.code_index import CodeIndex

    lines = ["function outer() {"]
    lines.extend(f"  function inner_{i}() {{ return {i}; }}" for i in range(320))
    lines.append("}")
    pairs, next_open = CodeIndex._brace_metadata(lines)

    assert pairs[0] == len(lines) - 1
    assert next_open[0] == 0


def test_bundle_roundtrip_current_schema_and_binary_embedding(tmp_path: Path):
    app = LocalAIApp(str(_config(tmp_path)))
    repo = tmp_path / "repo"; repo.mkdir()
    root = str(repo.resolve()).replace("\\", "/")
    workspace = app.rag.workspace_id(root)
    scope = app.rag._scope_key("__preprocess__")
    try:
        with closing(app.deterministic._connect()) as con:
            con.execute("INSERT INTO files(root,path,content_hash,language,is_test,updated_at) VALUES(?,?,?,?,?,?)", (root,"a.py","h","python",0,time.time()))
            con.execute("INSERT INTO facts(root,path,kind,name,value,line,extra_json) VALUES(?,?,?,?,?,?,?)", (root,"a.py","route","x","/x",1,'{"method":"GET"}'))
            con.execute("INSERT INTO dependencies(root,source,name,version,scope) VALUES(?,?,?,?,?)", (root,"pyproject.toml","pytest","9","dev"))
            con.execute("INSERT INTO scripts(root,source,name,command,purpose) VALUES(?,?,?,?,?)", (root,"pyproject.toml","test","pytest","validation"))
            con.commit()
        blob = sqlite3.Binary(b"\x00\x00\x80?\x00\x00\x00@")
        with closing(app.rag._connect()) as con:
            con.execute("INSERT INTO files(tenant,workspace,path,mtime_ns,size,content_hash) VALUES(?,?,?,?,?,?)", (scope,workspace,"a.py",1,10,"h"))
            con.execute("INSERT INTO chunks(tenant,workspace,path,chunk_no,content_hash,text,embedding) VALUES(?,?,?,?,?,?,?)", (scope,workspace,"a.py",0,"h","hello",blob))
            con.commit()
        archive = app.export_bundle(root)
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            payload = json.loads(zf.read("bundle.json"))
        assert payload["version"] == __version__ and payload["tables_sha256"]
        with closing(app.deterministic._connect()) as con:
            for table in ("files","facts","dependencies","scripts"):
                con.execute(f"DELETE FROM {table} WHERE root=?", (root,))
            con.commit()
        with closing(app.rag._connect()) as con:
            con.execute("DELETE FROM chunks WHERE tenant=? AND workspace=?", (scope,workspace)); con.commit()
        restored = app.import_bundle(archive, root)
        assert restored["success"] is True and restored["version"] == __version__
        with closing(app.deterministic._connect()) as con:
            assert con.execute("SELECT COUNT(*) FROM facts WHERE root=?", (root,)).fetchone()[0] == 1
        with closing(app.rag._connect()) as con:
            raw = con.execute("SELECT embedding FROM chunks WHERE tenant=? AND workspace=?", (scope,workspace)).fetchone()[0]
        assert bytes(raw) == bytes(blob)
    finally:
        app.close()


def test_bundle_rejects_extra_members_and_bad_integrity(tmp_path: Path):
    app = LocalAIApp(str(_config(tmp_path)))
    repo = tmp_path / "repo"; repo.mkdir()
    try:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("bundle.json", "{}")
            zf.writestr("../evil", "x")
        assert app.import_bundle(buf.getvalue(), str(repo))["success"] is False
        tables = {}
        payload = {"format":"local-ai-hub-project-bundle","version":__version__,"root":str(repo),"tables":tables,"tables_sha256":"bad"}
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf: zf.writestr("bundle.json", json.dumps(payload))
        assert "integrity" in app.import_bundle(buf.getvalue(), str(repo))["error"]
    finally:
        app.close()


class _IdParser(HTMLParser):
    def __init__(self): super().__init__(); self.ids=[]
    def handle_starttag(self, tag, attrs):
        for k,v in attrs:
            if k == "id": self.ids.append(v)


def test_dashboard_has_unique_ids_and_valid_javascript(tmp_path: Path):
    from local_ai_hub.dashboard import DASHBOARD_HTML
    parser = _IdParser(); parser.feed(DASHBOARD_HTML)
    assert len(parser.ids) == len(set(parser.ids))
    assert 'id="reliabilityValue"' in DASHBOARD_HTML
    assert 'id="handledRequests"' in DASHBOARD_HTML
    assert 'id="tokensSaved"' in DASHBOARD_HTML
    assert 'id="dollarsSaved"' in DASHBOARD_HTML
    assert "estimated_savings_usd" in DASHBOARD_HTML
    assert 'Content-Type\':\'application/zip' in DASHBOARD_HTML
    assert 'FormData()' not in DASHBOARD_HTML
    assert 'id="config" class="page"' in DASHBOARD_HTML
    assert "Recent API requests" in DASHBOARD_HTML
    assert "recent_http" in DASHBOARD_HTML
    assert "badge-waiting" in DASHBOARD_HTML
    assert "statusPollInFlight" in DASHBOARD_HTML
    assert "progress_age_seconds" in DASHBOARD_HTML
    assert "id=\"sloScope\"" in DASHBOARD_HTML
    assert "scope='+sloScope" in DASHBOARD_HTML
    assert "Since restart" in DASHBOARD_HTML
    assert "probeHealth" in DASHBOARD_HTML
    assert "Agent debug traces" in DASHBOARD_HTML
    assert "/api/debug-traces" in DASHBOARD_HTML
    assert "traceDisplayModel" in DASHBOARD_HTML
    assert "renderHumanModal" in DASHBOARD_HTML
    assert "Raw JSON" in DASHBOARD_HTML
    assert "human-grid" in DASHBOARD_HTML
    assert "trace-timeline" in DASHBOARD_HTML
    assert "toggleTraceStep" in DASHBOARD_HTML
    assert "Request trace" in DASHBOARD_HTML
    assert "trace-tabs" in DASHBOARD_HTML
    assert "data-trace-view" in DASHBOARD_HTML
    assert "Tool result" in DASHBOARD_HTML
    assert "traceInspector" in DASHBOARD_HTML
    assert "traceSidebarList" in DASHBOARD_HTML
    assert "setupWorkLayout" in DASHBOARD_HTML
    assert "work-kpis" in DASHBOARD_HTML
    assert "work-panel-1" in DASHBOARD_HTML
    assert "workSchedulerRow" in DASHBOARD_HTML
    assert "workSearch" in DASHBOARD_HTML
    assert "workState" in DASHBOARD_HTML
    assert "workVisible" in DASHBOARD_HTML
    assert "Agent trace history" in DASHBOARD_HTML
    assert "dedicated authenticated trace page" in Path("docs/DASHBOARD.md").read_text(encoding="utf-8")
    from local_ai_hub.preprocess import ProjectPreprocessor
    assert "batch in progress" in inspect.getsource(ProjectPreprocessor.status)
    assert 'id="controlMenu"' in DASHBOARD_HTML
    assert 'id="projectSearch"' in DASHBOARD_HTML
    assert 'id="projectFilter"' in DASHBOARD_HTML
    assert 'id="projectSort"' in DASHBOARD_HTML
    assert "13 Pipeline Phases:" not in DASHBOARD_HTML
    assert "Graphics accelerator" not in DASHBOARD_HTML
    assert "<th>Pipeline Phase &amp; Stepper</th>" not in DASHBOARD_HTML
    assert "<th>Index Readiness</th>" not in DASHBOARD_HTML
    assert '/api/config/update' in DASHBOARD_HTML
    assert 'id="agentOsState">0 active · 0 total tasks · 0 memories</span>' in DASHBOARD_HTML
    assert 'id="prepState">0 registered projects · global running</span>' in DASHBOARD_HTML
    assert 'id="projectSummary">0 of 0 projects</span>' in DASHBOARD_HTML
    assert 'id="commandState">0 running</span>' in DASHBOARD_HTML
    js = DASHBOARD_HTML.split("<script>",1)[1].split("</script>",1)[0]
    js_file = tmp_path / "dashboard.js"; js_file.write_text(js, encoding="utf-8")
    if subprocess.run(["node", "--version"], capture_output=True).returncode == 0:
        cp = subprocess.run(["node", "--check", str(js_file)], capture_output=True, text=True)
        assert cp.returncode == 0, cp.stderr


def test_live_trace_retryable_detail_errors_do_not_open_terminal_modal():
    from local_ai_hub.dashboard import DASHBOARD_HTML

    assert "if(d.retryable){" in DASHBOARD_HTML
    assert "retrying…" in DASHBOARD_HTML


def test_live_trace_rerender_preserves_nested_scroll_positions():
    from local_ai_hub.dashboard import DASHBOARD_HTML

    assert "captureTraceScrollPositions" in DASHBOARD_HTML
    assert "restoreTraceScrollPositions" in DASHBOARD_HTML


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); return sock.getsockname()[1]


def _request(url: str, *, method="GET", body: bytes | None=None, headers=None):
    req=urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, {}, b""



def test_hub_client_can_probe_without_autostart(tmp_path: Path):
    from local_ai_hub.client import HubClient
    port = _free_port()
    cfg = tmp_path / "client.toml"
    cfg.write_text(
        f'''[server]
bind="127.0.0.1"
port={port}
state_dir="{(tmp_path / "state").as_posix()}"
auto_start_ollama=false
[hardware]
profile="cpu"
auto_tune=false
[prewarm]
enabled=false
''',
        encoding="utf-8",
    )
    client = HubClient(tenant="probe", config_path=str(cfg), auto_start=False)

    def forbidden():
        raise AssertionError("ensure_server must not be called for non-starting probes")

    client.ensure_server = forbidden  # type: ignore[method-assign]
    result = client.get("/api/status", timeout=0.2)
    assert result.get("success") is False

def test_http_auth_json_limits_security_headers_and_binary_bundle(tmp_path: Path):
    port = _free_port(); state = tmp_path / "state"; repo = tmp_path / "repo"; repo.mkdir()
    cfg = tmp_path / "server.toml"
    cfg.write_text(f'''[server]\nbind="127.0.0.1"\nport={port}\nstate_dir="{state.as_posix()}"\nauto_start_ollama=false\nmax_request_body_bytes=1024\n[security]\napi_token="0123456789abcdef"\n[hardware]\nprofile="cpu"\nauto_tune=false\n[prewarm]\nenabled=false\n[preprocessing]\nenabled=false\n[resilience]\nwatchdog_enabled=false\n[code_intelligence]\nenabled=false\n[background_gpu]\nenabled=false\n[observability]\nenabled=false\n''', encoding="utf-8")
    env=os.environ.copy(); env["PYTHONPATH"]=str(ROOT/"src")+(os.pathsep+env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    proc=subprocess.Popen([sys.executable,"-m","local_ai_hub","--config",str(cfg)],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    base=f"http://127.0.0.1:{port}"; auth={"X-LocalAI-Token":"0123456789abcdef"}
    try:
        deadline=time.time()+12
        while time.time()<deadline:
            if proc.poll() is not None: break
            status,_,_= _request(base+"/dashboard")
            if status==200: break
            time.sleep(.1)
        status,headers,html=_request(base+"/dashboard")
        assert status==200 and b"Local AI Hub" in html
        assert headers.get("X-Content-Type-Options") == "nosniff"
        assert _request(base+"/api/status")[0] == 401
        assert _request(base+"/api/status", headers=auth)[0] == 200
        status, _, live_body = _request(base+"/api/live/status", headers=auth)
        live_status = json.loads(live_body)
        assert status == 200 and isinstance(live_status.get("observability"), dict)
        assert "active_requests" in live_status["observability"]
        assert "recent_http" in live_status["observability"]
        status, _, _ = _request(base+"/api/command", method="POST", body=json.dumps({"action":"classify","command":"pytest -q"}).encode(), headers={**auth,"Content-Type":"application/json"})
        assert status == 200
        status, _, body = _request(base+"/api/debug-traces?limit=10", headers=auth)
        traces = json.loads(body)
        assert status == 200 and traces["success"] is True and traces["items"]
        trace_id = traces["items"][0]["trace_id"]
        status, _, body = _request(base+"/api/debug-traces/"+trace_id, headers=auth)
        detail = json.loads(body)
        assert status == 200 and detail["success"] is True
        assert "request" in detail["session"] and "events" in detail
        cfg_body=json.dumps({"action":"update","settings":{"hardware.profile":"low","preprocessing.enabled":False}}).encode()
        status,_,body=_request(base+"/api/config/update",method="POST",body=cfg_body,headers={**auth,"Content-Type":"application/json"})
        assert status==200 and json.loads(body)["restart_required"] is True
        assert (tmp_path / "config.runtime.toml").is_file()
        status,_,body=_request(base+"/api/command",method="POST",body=b"{",headers={**auth,"Content-Type":"application/json"})
        assert status==400 and b"invalid JSON" in body
        status,_,_= _request(base+"/api/command",method="POST",body=b"x"*2048,headers={**auth,"Content-Type":"application/json"})
        assert status==413
        import hashlib
        tables={}; canonical=json.dumps(tables,sort_keys=True,separators=(",",":")).encode()
        payload={"format":"local-ai-hub-project-bundle","version":__version__,"root":str(repo),"tables":tables,"tables_sha256":hashlib.sha256(canonical).hexdigest()}
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED) as zf: zf.writestr("bundle.json",json.dumps(payload,separators=(",",":")))
        url=base+"/api/bundle/import?target_root="+urllib.parse.quote(str(repo))
        status,_,body=_request(url,method="POST",body=buf.getvalue(),headers={**auth,"Content-Type":"application/zip"})
        assert status==200, body
        assert json.loads(body)["success"] is True

        # Broad public deterministic contract: every cheap repository/operator endpoint
        # must remain usable without Ollama or external Serena/CodeGraph processes.
        (repo / "main.py").write_text("class SampleService:\n    pass\n", encoding="utf-8")
        (repo / "pyproject.toml").write_text('[project]\nname="smoke"\nversion="0.1"\n', encoding="utf-8")
        def jpost(path, payload):
            raw=json.dumps(payload).encode()
            return _request(base+path,method="POST",body=raw,headers={**auth,"Content-Type":"application/json"})
        calls=[
            ("/api/repo/profile", {"root":str(repo)}),
            ("/api/repo/map", {"root":str(repo),"max_symbols":20}),
            ("/api/repo/code-index", {"root":str(repo),"query":"SampleService","limit":10}),
            ("/api/repo/deterministic", {"root":str(repo),"query":"project dependencies","limit":10}),
            ("/api/search", {"root":str(repo),"query":"SampleService","top_k":5}),
            ("/api/context/pack", {"root":str(repo),"query":"SampleService","max_tokens":512}),
            ("/api/code/ast_outline", {"root":str(repo),"path":"main.py"}),
            ("/api/test_matrix", {"root":str(repo)}),
            ("/api/security_audit", {"root":str(repo),"limit":10}),
            ("/api/resolve_imports", {"root":str(repo),"symbols":["SampleService"],"language":"auto"}),
            ("/api/command", {"action":"classify","command":"pytest -q"}),
            ("/api/preprocess", {"action":"status","root":str(repo)}),
        ]
        for path,payload in calls:
            st,_,response=jpost(path,payload)
            assert st < 500, (path, st, response[:500])
            assert response, path
        for path in ("/api/capabilities", "/api/hardware/system", "/api/config", "/api/logs/tail?lines=5"):
            st,_,response=_request(base+path,headers=auth)
            assert st < 500 and response, (path,st,response[:500])
    finally:
        if proc.poll() is None:
            proc.terminate()
            try: proc.wait(timeout=5)
            except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=2)
        for stream in (proc.stdout, proc.stderr):
            if stream:
                stream.close()

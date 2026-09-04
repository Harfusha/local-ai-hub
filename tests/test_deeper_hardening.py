from __future__ import annotations

import json
import subprocess
from contextlib import closing

import pytest

from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.http_server import Handler, RequestBodyError
from local_ai_hub.rag import RAGStore
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.services import LocalAIServices
from local_ai_hub.telemetry import TelemetryStore


def _config(tmp_path):
    return {
        "server": {"state_dir": str(tmp_path)},
        "features": {"rag": True},
        "dependency_audit": {"osv_enabled": True, "osv_timeout_seconds": 1, "osv_cache_ttl_seconds": 60},
    }


def test_osv_audit_caches_live_result(tmp_path, monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def read(self): return json.dumps({"results": [{"vulns": []}]}).encode()

    engine = DeterministicEngine(_config(tmp_path), None, None)
    root = tmp_path / "repo"
    root.mkdir()
    with closing(engine._connect()) as con:
        con.execute("INSERT INTO dependencies(root,source,name,version,scope) VALUES(?,?,?,?,?)", (str(root.resolve()), "requirements.txt", "requests", "2.31.0", ""))
        con.commit()
    calls = 0
    def urlopen(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return Response()
    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    engine.audit_dependencies(str(root))
    engine.audit_dependencies(str(root))

    assert calls == 1


def test_git_blob_map_is_reused_for_second_batch(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text("value = 1\n", encoding="utf-8")
    for command in (["git", "init"], ["git", "add", "a.py"]):
        subprocess.run(command, cwd=root, check=True, capture_output=True)
    calls = 0
    real_run = subprocess.run
    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real_run(*args, **kwargs)
    monkeypatch.setattr("local_ai_hub.repo_tools.subprocess.run", counted)
    tools = RepositoryTools(_config(tmp_path))

    tools.git_blob_hashes(str(root), ["a.py"])
    tools.git_blob_hashes(str(root), ["a.py"])

    assert calls == 2


def test_dashboard_csp_uses_nonce_not_unsafe_inline_script():
    headers = {}
    handler = Handler.__new__(Handler)
    handler.send_header = lambda key, value: headers.__setitem__(key, value)

    Handler._common_headers(handler, html=True, nonce="test-nonce")

    policy = headers["Content-Security-Policy"]
    assert "script-src 'nonce-test-nonce'" in policy
    assert "script-src 'self' 'unsafe-inline'" not in policy


def test_api_schema_rejects_excessive_embedding_items():
    assert hasattr(Handler, "_validate_payload")
    with pytest.raises(RequestBodyError):
        Handler._validate_payload("/v1/embed", {"texts": ["x"] * 257})


def test_rag_cosine_rejects_mismatched_dimensions():
    assert RAGStore._cosine([1.0], [1.0, 2.0]) == 0.0


def test_telemetry_removes_secret_values(tmp_path):
    event = TelemetryStore._clean_event({"tenant": "Bearer secret-token", "action": "POST /v1?api_key=secret-token"})

    assert "secret-token" not in json.dumps(event)


def test_telemetry_recent_http_history_is_persistent(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry-state", enabled=True, flush_interval_seconds=0.01)
    try:
        store.record_http(action="/v1/delegate", request_id="req-1", agent="test", tenant="tenant", status_code=200, duration_ms=12.5)
        store.flush(1.0)
        recent = store.recent_http(10)
    finally:
        store.close()

    assert recent[0]["action"] == "/v1/delegate"
    assert recent[0]["request_id"] == "req-1"
    assert recent[0]["status_code"] == 200


@pytest.mark.parametrize("patch", [
    "--- a/../../outside\n+++ b/a.py\n@@ -1 +1 @@\n-a\n+b\n",
    "--- a/a.py\n+++ b/a.py\n@@ malformed\n-a\n+b\n",
    "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-a\n+b\n\n--- b/../../outside\n",
])
def test_patch_parser_rejects_fuzzed_path_and_hunk(patch):
    result = LocalAIServices.validate_patch(None, {"patch": patch}, "test")

    assert result["success"] is False

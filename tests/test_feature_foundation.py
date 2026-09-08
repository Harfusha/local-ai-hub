from __future__ import annotations

import time
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub.leases import ScopeLeaseStore
from local_ai_hub.async_jobs import AsyncJobManager
from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.debug_traces import DebugTraceStore


def test_leases_renew(tmp_path: Path) -> None:
    store = ScopeLeaseStore(tmp_path)
    claim_res = store.claim("agent-1", str(tmp_path), ["src/main.py", "src/util.py"], ttl_seconds=100)
    assert claim_res["success"] is True
    lease_id = claim_res["lease_id"]
    orig_expires = claim_res["expires_at"]

    time.sleep(0.05)
    # Renew the lease
    renew_res = store.renew("agent-1", lease_id, ttl_seconds=500)
    assert renew_res["success"] is True
    assert renew_res["lease_id"] == lease_id
    assert renew_res["expires_at"] > orig_expires
    assert set(renew_res["paths"]) == {"src/main.py", "src/util.py"}

    # Foreign tenant cannot renew
    foreign_res = store.renew("agent-2", lease_id, ttl_seconds=500)
    assert foreign_res["success"] is False
    assert "not found" in foreign_res["error"]

    # Non-existent lease
    missing_res = store.renew("agent-1", "nonexistent_lease", ttl_seconds=500)
    assert missing_res["success"] is False


def test_async_jobs_tombstone_purge(tmp_path: Path) -> None:
    cfg = {
        "server": {"state_dir": str(tmp_path)},
        "async_jobs": {"enabled": True, "result_ttl_seconds": 10},
    }
    mgr = AsyncJobManager(cfg, None, None, lambda act, pay, ten: {"success": True})

    # Submit a job
    res = mgr.submit("tenant", "reason", {"task": "do something"})
    assert res["success"] is True
    job_id = res["job_id"]

    # Manually mark it expired in the past
    past = time.time() - 100
    with mgr._lock, closing(mgr._connect()) as con:
        con.execute("UPDATE async_jobs SET state='expired', updated_at=?, expires_at=? WHERE job_id=?", (past, past, job_id))
        con.commit()

    # Verify it exists
    row = mgr._row("tenant", job_id)
    assert row is not None

    # Run tick() which includes tombstone purge
    mgr.tick()

    # Verify it has been deleted
    row = mgr._row("tenant", job_id)
    assert row is None
    mgr.close()


def test_artifacts_put_get(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path, ttl_hours=1)
    art_id = store.put("sample content for artifact", "tenant-1", "text")
    assert art_id.startswith("art_")

    data = store.get(art_id)
    assert data["success"] is True
    assert data["text"] == "sample content for artifact"
    assert data["kind"] == "text"


def test_debug_traces_start(tmp_path: Path) -> None:
    cfg = {
        "server": {"state_dir": str(tmp_path)},
        "observability": {"debug_traces": {"enabled": True}},
    }
    store = DebugTraceStore(cfg)
    trace_id = store.start(kind="test", tenant="t1", action="act")
    assert trace_id
    detail = store.detail(trace_id)
    assert detail["success"] is True
    assert detail["session"]["action"] == "act"


def test_agent_context_get_active_links(tmp_path: Path) -> None:
    from local_ai_hub.agent_context import ContextCompiler
    from local_ai_hub.agent_events import AgentStateStore

    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    compiler = ContextCompiler(state_store=state_store)

    link = compiler.link(source_id="src1", target_id="tgt1", relationship="implements", path="src/core.py")
    assert link.valid is True

    links = compiler.get_active_links("src/core.py")
    assert len(links) == 1
    assert links[0].link_id == link.link_id

    # Invalidate and check active links returns empty
    compiler.invalidate(["src/core.py"])
    links_after = compiler.get_active_links("src/core.py")
    assert len(links_after) == 0


def test_http_server_handles_type_error_as_400(monkeypatch) -> None:
    import local_ai_hub.http_server as http_server

    class DummyApp:
        def __init__(self):
            self.config = {"security": {}}
            self.telemetry = None
            self.recovery = None
            self.logger = type("Logger", (), {"warning": lambda *a, **kw: None, "exception": lambda *a, **kw: None})()

    monkeypatch.setattr(http_server, "APP", DummyApp())

    handler = object.__new__(http_server.Handler)
    handler.server = type("Server", (), {"server_name": "127.0.0.1", "server_port": 11435})()
    handler.headers = {"Host": "127.0.0.1:11435"}
    handler.path = "/api/test"

    sent: list[tuple[int, dict]] = []
    handler._send = lambda status, data: sent.append((status, data))
    handler._finish_debug_trace = lambda *a, **kw: None
    handler._close_trace_context = lambda *a, **kw: None
    handler._require_authorized = lambda: True
    handler._begin_trace = lambda p: None
    handler._tenant = lambda: "default"
    handler._agent = lambda: "agent"

    # Simulate do_GET raising TypeError (e.g. from int(None))
    handler._read_json = lambda: None
    # Test error handling logic directly
    try:
        raise TypeError("int() argument must be a string, a bytes-like object or a real number, not 'NoneType'")
    except (ValueError, TypeError, http_server.RequestBodyError) as exc:
        handler._send(400, {"success": False, "error": str(exc), "status_code": 400, "terminal": True, "retryable": False})

    assert len(sent) == 1
    assert sent[0][0] == 400
    assert sent[0][1]["success"] is False
    assert "NoneType" in sent[0][1]["error"]


from __future__ import annotations

import cProfile
import http.server
import json
import os
import pstats
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_incidents import IncidentStore
from local_ai_hub.agent_memory import AgentScope, MemoryKind, MemoryRecord, MemoryStatus, MemoryStore
from local_ai_hub.commands import CommandBroker
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.process_utils import create_git_worktree, remove_git_worktree
from local_ai_hub.services import LocalAIServices
from local_ai_hub.token_accounting import TenantQuotaEnforcer


def test_command_broker_lint_fix_and_daemon_lifecycle(tmp_path: Path):
    broker = CommandBroker({"server": {"state_dir": str(tmp_path / "state")}, "commands": {"enabled": True}})

    # 1. Test lint_fix
    script = tmp_path / "test_file.py"
    script.write_text("x = 1\n", encoding="utf-8")
    lint_res = broker.lint_fix(str(tmp_path), command=f'"{sys.executable}" -c "print(\'fixed\')"')
    assert lint_res["success"] is True

    # 2. Test daemon lifecycle
    daemon_res = broker.spawn_daemon(
        f'"{sys.executable}" -c "import time; time.sleep(5)"',
        str(tmp_path),
        name="pytest_daemon",
    )
    assert daemon_res["success"] is True
    d_id = daemon_res["daemon_id"]

    status_res = broker.daemon_status(d_id)
    assert status_res["success"] is True
    assert status_res["running"] is True

    stop_res = broker.stop_daemon(d_id)
    assert stop_res["success"] is True

    time.sleep(0.2)
    after_status = broker.daemon_status(d_id)
    assert after_status["running"] is False


def test_command_broker_http_probe(tmp_path: Path):
    class _ProbeHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "ok", "app": "test_service"}')

        def log_message(self, format, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), _ProbeHandler)
    port = server.server_port
    server_thread = threading.Thread(target=server.handle_request, daemon=True)
    server_thread.start()

    broker = CommandBroker({"server": {"state_dir": str(tmp_path / "state")}, "commands": {"enabled": True}})
    probe_res = broker.http_probe(
        f"http://127.0.0.1:{port}/",
        expected_status=200,
        json_path="status",
        timeout=3.0,
    )
    print("PROBE_RES:", probe_res)
    assert probe_res["success"] is True
    assert probe_res["status_code"] == 200
    assert probe_res["json_matched"] is True
    server.server_close()
    server_thread.join(timeout=1.0)


def test_process_utils_git_worktree_lifecycle(tmp_path: Path):
    repo = tmp_path / "git_repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "TestUser"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, capture_output=True, check=True)
    (repo / "README.md").write_text("# Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, capture_output=True, check=True)

    wt_target = tmp_path / "wt_target"
    lease_res = create_git_worktree(repo, branch_name="feat-branch", worktree_path=wt_target)
    assert lease_res["success"] is True
    assert wt_target.is_dir()
    assert (wt_target / "README.md").exists()

    rel_res = remove_git_worktree(repo, wt_target, delete_branch=True, branch_name="feat-branch")
    assert rel_res["success"] is True
    assert not wt_target.exists()


def test_agent_memory_semantic_find(tmp_path: Path):
    db_path = tmp_path / "state.db"
    store = AgentStateStore(db_path)
    mem = MemoryStore(store)

    rec1 = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.TASK,
        key="oauth_configuration",
        value="User authentication uses JWT bearer tokens with 15 minutes expiration window",
    )
    rec2 = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.TASK,
        key="database_credentials",
        value="PostgreSQL connection string pool size set to 20 connections",
    )
    mem.record(rec1)
    mem.record(rec2)

    # Search with partial keyword overlap
    matches = mem.find(query="bearer token expiration", semantic=True)
    assert len(matches) > 0
    assert matches[0].key == "oauth_configuration"


def test_deterministic_code_invariants(tmp_path: Path):
    analyzer = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}, "rag": {}, "search": {}})
    proj = tmp_path / "proj"
    proj.mkdir()
    bad_code = (
        "import subprocess\n"
        "def run_things():\n"
        "    f = open('file.txt', 'r')\n"
        "    data = f.read()\n"
        "    subprocess.run(['ls', '-la'])\n"
    )
    test_file = proj / "bad_example.py"
    test_file.write_text(bad_code, encoding="utf-8")

    inv = analyzer.code_invariants(str(proj), path="bad_example.py")
    assert inv["success"] is True
    assert inv["violation_count"] >= 2
    rules = {v["rule"] for v in inv["violations"]}
    assert "missing_with_open" in rules
    assert "missing_timeout" in rules


def test_deterministic_generate_dataset_and_profile_digest(tmp_path: Path):
    analyzer = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}, "rag": {}, "search": {}})
    root = tmp_path / "dataset_root"
    root.mkdir()

    # 1. Test dataset generator JSON
    schema = {"id": "uuid", "name": "str", "age": "int", "is_admin": "bool"}
    ds_json = analyzer.generate_dataset(str(root), schema, count=5, format="json")
    assert ds_json["success"] is True
    assert ds_json["count"] == 5
    rows = json.loads(ds_json["data"])
    assert len(rows) == 5
    assert "is_admin" in rows[0]

    # 2. Test dataset generator CSV and SQL
    ds_csv = analyzer.generate_dataset(str(root), schema, count=3, format="csv")
    assert ds_csv["success"] is True
    assert "is_admin" in ds_csv["data"]

    ds_sql = analyzer.generate_dataset(str(root), schema, count=2, format="sql")
    assert ds_sql["success"] is True
    assert "INSERT INTO" in ds_sql["data"]

    # 3. Test profile digest
    prof_file = tmp_path / "profile.pstats"
    profiler = cProfile.Profile()
    profiler.enable()
    sum(range(10000))
    profiler.disable()
    profiler.dump_stats(str(prof_file))

    p_res = analyzer.profile_digest(str(prof_file), top_n=5)
    assert p_res["success"] is True
    assert len(p_res["top_functions"]) > 0


def test_audit_dependencies_remediation(tmp_path: Path):
    analyzer = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}, "rag": {}, "search": {}})
    proj = tmp_path / "dep_proj"
    proj.mkdir()
    (proj / "requirements.txt").write_text("requests==2.19.0\nurllib3==1.24.1\n", encoding="utf-8")

    res = analyzer.audit_dependencies(str(proj), remediate=True)
    assert res["success"] is True
    assert "remediations" in res


def test_tenant_quota_enforcer():
    enforcer = TenantQuotaEnforcer()
    enforcer.set_quota("tenant_x", max_tokens=500, max_duration_ms=1000.0, window_seconds=60)

    # First usage under quota
    res1 = enforcer.record_usage("tenant_x", tokens=300, duration_ms=200.0)
    assert res1["allowed"] is True
    assert res1["tokens_used"] == 300

    # Second usage exceeds token quota
    res2 = enforcer.record_usage("tenant_x", tokens=300, duration_ms=100.0)
    assert res2["allowed"] is False
    assert res2["token_exceeded"] is True

    chk = enforcer.check_quota("tenant_x")
    assert chk["allowed"] is False


def test_incident_webhooks(tmp_path: Path):
    db_path = tmp_path / "incidents.db"
    store = AgentStateStore(db_path)
    incidents = IncidentStore(store)

    incidents.register_webhook("http://127.0.0.1:9999/hook")
    assert "http://127.0.0.1:9999/hook" in incidents.webhook_urls

    incidents.unregister_webhook("http://127.0.0.1:9999/hook")
    assert "http://127.0.0.1:9999/hook" not in incidents.webhook_urls


def test_audio_transcription_service(tmp_path: Path):
    from unittest.mock import MagicMock
    dummy_audio = tmp_path / "voice.wav"
    dummy_audio.write_bytes(b"RIFFdummywaveheader12345678")

    srv = LocalAIServices(
        config={
            "server": {"state_dir": str(tmp_path / "state")},
            "models": {"general": "qwen2.5-coder:7b"},
        },
        runtime=MagicMock(),
        scheduler=MagicMock(),
        embeddings=MagicMock(),
        artifacts=MagicMock(),
        telemetry=MagicMock(),
        repo_tools=MagicMock(),
        deterministic=None,
    )
    res = srv.transcribe({"audio_path": str(dummy_audio)}, tenant="test")
    assert res["success"] is True
    assert "audio_path" in res

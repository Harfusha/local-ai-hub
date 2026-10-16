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
from unittest import mock
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_incidents import IncidentStore
from local_ai_hub.agent_memory import AgentScope, MemoryKind, MemoryRecord, MemoryStatus, MemoryStore
from local_ai_hub.commands import CommandBroker
from fencing_lease_support import FakeFencingLeaseStore, install_test_work_attempt_fence
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.process_utils import create_git_worktree, remove_git_worktree
from local_ai_hub.services import LocalAIServices
from local_ai_hub.token_accounting import TenantQuotaEnforcer


def test_command_broker_lint_fix_and_rejects_unsafe_daemon_command(tmp_path: Path, monkeypatch):
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    script = tmp_path / "test_file.py"
    script.write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "test_file.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "initial"], cwd=tmp_path, check=True)
    repo_root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=tmp_path, capture_output=True,
        text=True, check=True,
    ).stdout.strip()
    branch = subprocess.run(
        ["git", "symbolic-ref", "--quiet", "--short", "HEAD"], cwd=tmp_path,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    task_id = "task-lifecycle"

    class TaskStore:
        def get(self, requested_task_id: str):
            if requested_task_id != task_id:
                return None
            return SimpleNamespace(
                task_id=task_id,
                checkpoint=SimpleNamespace(state_data={
                    "worktree": {
                        "success": True, "worktree_path": str(tmp_path),
                        "repo_root": repo_root, "branch": branch,
                    }
                }),
            )

    class AllowedPolicy:
        def authorize(self, *_args, **_kwargs):
            return SimpleNamespace(
                allowed=True, reason="test grant",
                to_dict=lambda: {"allowed": True, "reason": "test grant"},
            )

        def get_budget(self, _task_id):
            return SimpleNamespace(is_exhausted=lambda: False)

        def consume(self, *_args, **_kwargs):
            return None

    broker = CommandBroker({
        "server": {"state_dir": str(tmp_path / "state")},
        "commands": {"enabled": True},
    })
    broker.set_task_store(TaskStore())
    install_test_work_attempt_fence(broker, FakeFencingLeaseStore())
    broker.set_policy_engine(AllowedPolicy())
    monkeypatch.setattr(broker, "_transaction_docker_ready", lambda: (True, ""))

    def execute(argv, cwd, timeout, *_args, **_kwargs):
        completed = subprocess.run(
            argv, cwd=cwd, shell=True, capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTEST_ADDOPTS": "-p no:cacheprovider"},
        )
        return {
            "success": completed.returncode == 0, "exit_code": completed.returncode,
            "stdout": completed.stdout, "stderr": completed.stderr, "duration_ms": 1,
        }

    monkeypatch.setattr(broker, "_execute", execute)

    # 1. Test lint_fix
    lint_res = broker.lint_fix(
        str(tmp_path), command=f'"{sys.executable}" -c "print(\'fixed\')"',
        task_id=task_id, paths=["test_file.py"],
    )
    assert lint_res["success"] is True

    # 2. Deny opaque inline code at the daemon policy boundary.
    daemon_res = broker.spawn_daemon(
        f'"{sys.executable}" -c "import decimal; x = decimal.Decimal(1)"',
        str(tmp_path),
        name="pytest_daemon",
        task_id=task_id,
    )
    assert daemon_res["success"] is False, daemon_res
    assert "unknown side effects" in str(daemon_res.get("error", ""))


def test_daemon_status_closes_log_after_natural_exit():
    broker = CommandBroker({"commands": {"enabled": True}})
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    log_fh = mock.MagicMock()
    broker._daemons["dead"] = {
        "daemon_id": "dead",
        "process": process,
        "pid": process.pid,
        "name": "dead",
        "command": "pass",
        "cwd": ".",
        "log_path": "unused.log",
        "log_fh": log_fh,
        "started_at": time.time(),
    }
    process.wait(timeout=2)

    result = broker.daemon_status("dead")

    assert result["success"] is True
    assert result["running"] is False
    log_fh.close.assert_called_once_with()


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

    broker = CommandBroker({
        "server": {"state_dir": str(tmp_path / "state")},
        "commands": {"enabled": True},
        "network": {"allow_private_hosts": ["127.0.0.1"]},
    })
    probe_res = broker.http_probe(
        f"http://127.0.0.1:{port}/",
        expected_status=200,
        json_path="status",
        timeout=3.0,
    )
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

    rel_res = remove_git_worktree(
        repo,
        wt_target,
        delete_branch=True,
        branch_name="feat-branch",
        worktree_id=lease_res["worktree_id"],
    )
    assert rel_res["success"] is True
    assert not wt_target.exists()


def test_agent_memory_semantic_find(tmp_path: Path):
    db_path = tmp_path / "state.db"
    store = AgentStateStore(db_path)
    mem = MemoryStore(store)

    rec1 = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.REPOSITORY,
        scope_id="repo-memory-search",
        key="oauth_configuration",
        value="User authentication uses JWT bearer tokens with 15 minutes expiration window",
        provenance={"root": str(tmp_path), "repository_id": "repo-memory-search", "tenant": "tenant-a"},
    )
    rec2 = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.REPOSITORY,
        scope_id="repo-memory-search",
        key="database_credentials",
        value="PostgreSQL connection string pool size set to 20 connections",
        provenance={"root": str(tmp_path), "repository_id": "repo-memory-search", "tenant": "tenant-a"},
    )
    mem.record(rec1)
    mem.record(rec2)

    # Search with partial keyword overlap
    matches = mem.find(
        query="bearer token expiration",
        scope=AgentScope.REPOSITORY,
        scope_id="repo-memory-search",
        root=str(tmp_path),
        repository_id="repo-memory-search",
        tenant="tenant-a",
        semantic=True,
    )
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


def test_deterministic_code_invariants_ignore_os_open_and_popen(tmp_path: Path):
    analyzer = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}, "rag": {}, "search": {}})
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "bounded.py").write_text(
        "import os\n"
        "import subprocess\n"
        "def run():\n"
        "    fd = os.open('file.txt', os.O_CREAT | os.O_WRONLY)\n"
        "    os.close(fd)\n"
        "    process = subprocess.Popen(['echo', 'ok'])\n"
        "    process.wait(timeout=2)\n",
        encoding="utf-8",
    )

    result = analyzer.code_invariants(str(proj), path="bounded.py")

    assert result["success"] is True
    assert not any(item["rule"] == "missing_with_open" for item in result["violations"])
    assert not any(item["rule"] == "missing_timeout" for item in result["violations"])


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


def test_audio_transcription_service_without_whisper_is_not_false_success(tmp_path: Path, monkeypatch):
    from unittest.mock import MagicMock
    from types import SimpleNamespace

    dummy_audio = tmp_path / "voice.wav"
    dummy_audio.write_bytes(b"RIFFdummywaveheader12345678")
    monkeypatch.setattr("local_ai_hub.services.shutil.which", lambda _name: None)

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
    assert res["success"] is False
    assert res["reason"] == "cli_missing"
    assert res["degraded"] is True
    assert not res.get("text")


def test_audio_transcription_service(tmp_path: Path, monkeypatch):
    from unittest.mock import MagicMock
    from types import SimpleNamespace
    import wave
    from local_ai_hub.whisper_policy import WhisperModelPolicy

    dummy_audio = tmp_path / "voice.wav"
    with wave.open(str(dummy_audio), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x00\x00" * 160)
    checkpoint = tmp_path / "base.pt"
    checkpoint.write_bytes(b"unit checkpoint")
    monkeypatch.setattr(
        "local_ai_hub.whisper_policy.prepare_whisper_model",
        lambda *_args, **_kwargs: WhisperModelPolicy(
            ok=True, model="base", model_dir=str(tmp_path), cached_model=str(checkpoint),
        ),
    )
    monkeypatch.setattr("local_ai_hub.services.shutil.which", lambda _name: "whisper")
    monkeypatch.setattr(
        "local_ai_hub.process_utils.run_hidden",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout='{"text":"transcribed audio"}',
            stderr="",
        ),
    )

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
    assert res["text"] == "transcribed audio"

from __future__ import annotations

import json
from pathlib import Path
import threading
import urllib.request

from local_ai_hub.commands import CommandBroker
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_verification import VerificationStore, VerificationReceipt
from local_ai_hub.agent_memory import MemoryStore, MemoryRecord
from local_ai_hub.agent_tasks import TaskStore, GoalContract
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.app import LocalAIApp
from local_ai_hub import http_server


def test_command_validator_classifies_doctor_and_selftest(tmp_path: Path):
    class _Artifacts:
        def put(self, *_args, **_kwargs):
            return "art-1"

    class _RepoState:
        def fingerprint(self, _cwd):
            return {"fingerprint": "hash1"}

    state_dir = tmp_path / "broker_state"
    state_dir.mkdir(parents=True, exist_ok=True)

    broker = CommandBroker(
        {
            "server": {"state_dir": str(state_dir)},
            "commands": {"enabled": True, "allow_read": True, "allow_validation": True},
        },
        _Artifacts(),
        _RepoState(),
    )
    
    doc_res = broker.classify("python tools/doctor.py")
    assert doc_res["allowed"] is True
    assert doc_res["class"] == "validation"

    self_res = broker.classify("python tools/selftest.py")
    assert self_res["allowed"] is True
    assert self_res["class"] == "validation"


def test_command_broker_auto_registers_verification_receipt(tmp_path: Path):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_store = AgentStateStore(state_dir / "agent_state.sqlite3", enabled=True)
    task_store = TaskStore(state_store)
    v_store = VerificationStore(state_store, task_store=task_store)

    task = task_store.create(
        GoalContract(goal="Pass tests", acceptance_criteria=["Tests must pass"]),
        ScopeContext(task_id="task-test-1"),
        task_id="task-test-1",
    )

    class _Artifacts:
        def put(self, *_args, **_kwargs):
            return "art-1"

    class _RepoState:
        def fingerprint(self, _cwd):
            return {"fingerprint": "hash1"}

    broker = CommandBroker(
        {
            "server": {"state_dir": str(state_dir)},
            "commands": {"enabled": True, "allow_read": True, "allow_validation": True},
        },
        _Artifacts(),
        _RepoState(),
    )
    broker.set_verification_store(v_store)

    # Run a passing python test command with task_id
    res = broker.run(
        "python -m compileall tests",
        str(tmp_path),
        "tenant",
        task_id="task-test-1",
        criterion="Tests must pass",
    )

    assert res["exit_code"] == 0
    assert "verification_receipt" in res
    receipt_dict = res["verification_receipt"]
    assert receipt_dict["task_id"] == "task-test-1"
    assert receipt_dict["criterion"] == "Tests must pass"
    assert receipt_dict["passed"] is True

    # Check store has receipt
    comp = v_store.completion("task-test-1")
    assert len(comp.receipts) == 1
    assert comp.receipts[0].task_id == "task-test-1"
    assert comp.complete is True


def test_memory_store_query_search(tmp_path: Path):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_store = AgentStateStore(state_dir / "agent_state.sqlite3", enabled=True)
    mem_store = MemoryStore(state_store)

    mem_store.record(MemoryRecord.create(key="backend_config", value="Serena runs on port 9000", kind="config", scope="repo"))
    mem_store.record(MemoryRecord.create(key="db_port", value="Port 5432 is postgres", kind="fact", scope="repo"))
    mem_store.record(MemoryRecord.create(key="auth_token_pattern", value="JWT tokens use RS256", kind="finding", scope="repo"))

    # Search query in value
    res1 = mem_store.find(query="port")
    assert len(res1) == 2
    keys = {r.key for r in res1}
    assert keys == {"backend_config", "db_port"}

    # Search query in key
    res2 = mem_store.find(query="auth")
    assert len(res2) == 1
    assert res2[0].key == "auth_token_pattern"


def test_http_server_flat_payload_fallbacks(tmp_path: Path):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(f"""
[server]
bind = "127.0.0.1"
port = 11498
state_dir = "{state_dir.as_posix()}"

[agent_state]
enabled = true
""", encoding="utf-8")

    app = LocalAIApp(str(cfg_path))
    old_app = http_server.APP
    http_server.APP = app

    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def post_json(endpoint: str, data: dict) -> dict:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{endpoint}",
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))

    try:
        # 1. Flat task_create
        r1 = post_json("/v1/agent-state/tasks", {"action": "create", "task_id": "flat-1", "goal": "Fix everything"})
        assert r1["success"] is True
        assert r1["task"]["task_id"] == "flat-1"

        # 2. Flat task_checkpoint
        r2 = post_json("/v1/agent-state/tasks", {"action": "checkpoint", "task_id": "flat-1", "phase": "validation", "next_action": "run_tests"})
        assert r2["success"] is True
        assert r2["task"]["checkpoint"]["phase"] == "validation"

        # 3. Flat memory_record
        r3 = post_json("/v1/agent-state/memory", {"action": "record", "key": "flat_k", "value": "flat_v", "kind": "finding"})
        assert r3["success"] is True
        assert r3["record"]["key"] == "flat_k"

        # 4. Memory find with query
        r4 = post_json("/v1/agent-state/memory", {"action": "find", "query": "flat_v"})
        assert r4["success"] is True
        assert len(r4["records"]) == 1
    finally:
        server.shutdown()
        server.server_close()
        http_server.APP = old_app
        app.close()


def test_hubctl_agent_state_and_cleanup(monkeypatch, capsys):
    import sys
    from tools import hubctl

    class DummyClient:
        def status(self, detail="brief"):
            return {"success": True, "detail": detail, "enabled": True}

        def post(self, path, payload):
            return {"success": True, "path": path, "cleaned": 5}

    monkeypatch.setattr(hubctl, "client", lambda: DummyClient())

    # Test agent-state
    monkeypatch.setattr(sys, "argv", ["hubctl.py", "agent-state"])
    ret1 = hubctl.main()
    assert ret1 == 0
    out1 = capsys.readouterr().out
    assert '"detail": "agent_state"' in out1

    # Test cleanup
    monkeypatch.setattr(sys, "argv", ["hubctl.py", "cleanup"])
    ret2 = hubctl.main()
    assert ret2 == 0
    out2 = capsys.readouterr().out
    assert '"cleaned": 5' in out2


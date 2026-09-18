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

    hubctl_status = broker.classify("python tools/hubctl.py status")
    assert hubctl_status["allowed"] is True
    assert hubctl_status["class"] == "validation"

    hubctl_tasks = broker.classify("python tools/hubctl.py tasks")
    assert hubctl_tasks["allowed"] is True
    assert hubctl_tasks["class"] == "validation"

    hubctl_tasks_comp = broker.classify("python tools/hubctl.py tasks --task-id t-1 --complete")
    assert hubctl_tasks_comp["class"] == "mutating"
    assert hubctl_tasks_comp["allowed"] is False

    hubctl_tasks_fail = broker.classify("python tools/hubctl.py tasks --task-id t-1 --fail")
    assert hubctl_tasks_fail["class"] == "mutating"
    assert hubctl_tasks_fail["allowed"] is False

    hubctl_stop = broker.classify("python tools/hubctl.py stop")
    assert hubctl_stop["class"] == "mutating"
    assert hubctl_stop["allowed"] is False

    hubctl_gen = broker.classify("python tools/hubctl.py generate")
    assert hubctl_gen["allowed"] is True
    assert hubctl_gen["class"] == "build"

    pkg_gen = broker.classify("python -m local_ai_hub --generate")
    assert pkg_gen["allowed"] is True
    assert pkg_gen["class"] == "build"

    setup_gen = broker.classify("python tools/setup.py --generate-only")
    assert setup_gen["allowed"] is True
    assert setup_gen["class"] == "build"

    build_res = broker.classify("python -m build")
    assert build_res["allowed"] is True
    assert build_res["class"] == "build"

    pyflakes_res = broker.classify("pyflakes src tools")
    assert pyflakes_res["allowed"] is True
    assert pyflakes_res["class"] == "validation"

    m_pyflakes = broker.classify("python -m pyflakes src")
    assert m_pyflakes["allowed"] is True
    assert m_pyflakes["class"] == "validation"

    telem_res = broker.classify("python tools/telemetry_report.py --days 30")
    assert telem_res["allowed"] is True
    assert telem_res["class"] == "validation"


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
        r1 = post_json("/api/agent-state/tasks", {"action": "create", "task_id": "flat-1", "goal": "Fix everything"})
        assert r1["success"] is True
        assert r1["task"]["task_id"] == "flat-1"

        # 2. Flat task_checkpoint
        r2 = post_json("/api/agent-state/tasks", {"action": "checkpoint", "task_id": "flat-1", "phase": "validation", "next_action": "run_tests"})
        assert r2["success"] is True
        assert r2["task"]["checkpoint"]["phase"] == "validation"

        # 3. Flat memory_record
        r3 = post_json(
            "/api/agent-state/memory",
            {
                "action": "record",
                "key": "flat_k",
                "value": "flat_v",
                "kind": "finding",
                "scope": "repository",
                "provenance": {"root": str(tmp_path)},
            },
        )
        assert r3["success"] is True
        assert r3["record"]["key"] == "flat_k"
        assert r3["record"]["provenance"]["root"] == str(tmp_path)

        # 4. Memory find with query
        r4 = post_json(
            "/api/agent-state/memory",
            {"action": "find", "query": "flat_v", "root": str(tmp_path)},
        )
        assert r4["success"] is True
        assert [record["key"] for record in r4["records"]] == ["flat_k"]
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


def test_task_store_auto_complete_and_fail(tmp_path: Path):
    import pytest
    from local_ai_hub.agent_tasks import TaskStatus, CompletionGateError, InvalidTransitionError

    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_store = AgentStateStore(state_dir / "agent_state.sqlite3", enabled=True)
    task_store = TaskStore(state_store)
    mem_store = MemoryStore(state_store)

    # 1. Auto complete without criteria: PLANNED -> ACTIVE -> VERIFYING -> COMPLETED
    t1 = task_store.create(GoalContract(goal="Do quick task"), ScopeContext(task_id="t-1"), task_id="t-1")
    assert t1.status == TaskStatus.PLANNED
    assert task_store.count() == 1
    assert task_store.count(TaskStatus.PLANNED) == 1

    c1 = task_store.complete("t-1", reason="done quickly")
    assert c1.status == TaskStatus.COMPLETED
    assert task_store.count(TaskStatus.COMPLETED) == 1
    # Idempotent call
    assert task_store.complete("t-1").status == TaskStatus.COMPLETED

    # 2. Auto complete with criteria gates
    t2 = task_store.create(
        GoalContract(goal="Guarded task", acceptance_criteria=["criterion 1"]),
        ScopeContext(task_id="t-2"),
        task_id="t-2",
    )
    # Attempting to complete without receipt fails at verification gate
    with pytest.raises(CompletionGateError):
        task_store.complete("t-2")

    # State should now be in VERIFYING
    assert task_store.get("t-2").status == TaskStatus.VERIFYING

    # Add receipt and complete
    task_store.add_verification_receipt("t-2", "criterion 1", "receipt-abc")
    c2 = task_store.complete("t-2")
    assert c2.status == TaskStatus.COMPLETED

    # 3. Direct fail from PLANNED and ACTIVE
    t3 = task_store.create(GoalContract(goal="Failing task"), ScopeContext(task_id="t-3"), task_id="t-3")
    f3 = task_store.fail("t-3", reason="abandoned before start")
    assert f3.status == TaskStatus.FAILED
    assert task_store.fail("t-3").status == TaskStatus.FAILED

    # Cannot complete a failed task
    with pytest.raises(InvalidTransitionError):
        task_store.complete("t-3")

    # 4. Fail from WAITING and BLOCKED
    t4 = task_store.create(GoalContract(goal="Wait task"), ScopeContext(task_id="t-4"), task_id="t-4")
    task_store.transition("t-4", TaskStatus.ACTIVE, reason="activate", actor="agent", idempotency_key="act-4")
    task_store.transition("t-4", TaskStatus.WAITING, reason="waiting", actor="agent", idempotency_key="wait-4")
    f4 = task_store.fail("t-4", reason="timed out waiting")
    assert f4.status == TaskStatus.FAILED

    # 5. Counts
    assert task_store.count(TaskStatus.FAILED) == 2
    assert task_store.count(TaskStatus.COMPLETED) == 2
    assert task_store.count() == 4

    # 6. MemoryStore count
    assert mem_store.count() == 0
    mem_store.record(MemoryRecord.create(key="k1", value="first", kind="fact", scope="repo"))
    mem_store.record(MemoryRecord.create(key="k2", value="second", kind="decision", scope="repo"))
    assert mem_store.count() == 2


def test_hubctl_tasks_mutation_cli(monkeypatch, capsys):
    import sys
    from tools import hubctl as hubctl_mod

    calls = []

    class MockClient:
        def complete_task(self, task_id, reason=""):
            calls.append(("complete", task_id, reason))
            return {"success": True, "task": {"task_id": task_id, "status": "completed"}}

        def fail_task(self, task_id, reason=""):
            calls.append(("fail", task_id, reason))
            return {"success": True, "task": {"task_id": task_id, "status": "failed"}}

    monkeypatch.setattr(hubctl_mod, "client", lambda: MockClient())

    # 1. Complete with reason
    monkeypatch.setattr(sys, "argv", ["hubctl.py", "tasks", "--task-id", "task-100", "--complete", "--reason", "All done"])
    rc = hubctl_mod.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "Task task-100 completed: All done" in out
    assert calls[-1] == ("complete", "task-100", "All done")

    # 2. Fail with default reason
    monkeypatch.setattr(sys, "argv", ["hubctl.py", "tasks", "--task-id", "task-200", "--fail"])
    rc = hubctl_mod.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "Task task-200 failed: failed via hubctl" in out
    assert calls[-1] == ("fail", "task-200", "failed via hubctl")

    # 3. Missing task-id error
    monkeypatch.setattr(sys, "argv", ["hubctl.py", "tasks", "--complete"])
    rc = hubctl_mod.main()
    assert rc == 1
    err = capsys.readouterr().err
    assert "--task-id is required" in err


def test_external_tools_index_failure_suppression(tmp_path: Path):
    from local_ai_hub.external_tools import ExternalCodeIntelligence

    mgr = ExternalCodeIntelligence({"server": {"state_dir": str(tmp_path)}})
    assert mgr.index_failures == 0

    # Revision scoped error should not increment index_failures
    mgr._record_failure("serena", RuntimeError("indexing exceeded 60s"), operation="index", root=str(tmp_path))
    assert mgr.index_failures == 0

    # Codegraph missing module should not increment index_failures and should disable backend cleanly
    mgr.codegraph_enabled = True
    mgr._codegraph = "cgc"
    mgr._record_failure("codegraph", RuntimeError("No module named 'codegraphcontext'"), operation="index", root=str(tmp_path))
    assert mgr.index_failures == 0
    assert mgr.codegraph_enabled is False
    assert mgr._codegraph is None




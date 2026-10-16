from __future__ import annotations

import json
from pathlib import Path
import threading
import urllib.request
import pytest
import time

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import GoalContract, TaskState, TaskStatus, TaskStore
from local_ai_hub.commands import CommandBroker
from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.agent_verification import VerificationStore
from local_ai_hub.agent_incidents import IncidentStore
from local_ai_hub.app import LocalAIApp
from local_ai_hub import http_server


def test_task_store_get_active_task_filtering(tmp_path: Path):
    db_path = tmp_path / "state.db"
    state_store = AgentStateStore(str(db_path))
    task_store = TaskStore(state_store)

    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"
    repo_a.mkdir()
    repo_b.mkdir()

    # Empty initially
    assert task_store.get_active_task(str(repo_a)) is None

    # Create task 1 for repo_a (status = PLANNED by default)
    contract1 = GoalContract(goal="Task 1", acceptance_criteria=("pytest test_a.py passes",))
    context1 = ScopeContext(repository_id=str(repo_a))
    task1 = task_store.create(contract1, context1, repo_root=str(repo_a))

    # Should find task1 for repo_a, but not repo_b
    active_a = task_store.get_active_task(str(repo_a))
    assert active_a is not None
    assert active_a.task_id == task1.task_id
    assert task_store.get_active_task(str(repo_b)) is None

    # Transition task1 to ACTIVE
    task1_active = task_store.transition(task1.task_id, TaskStatus.ACTIVE, reason="starting", actor="agent", idempotency_key="t1")
    assert task_store.get_active_task(str(repo_a)).task_id == task1.task_id

    # Create task 2 for repo_a (PLANNED)
    contract2 = GoalContract(goal="Task 2", acceptance_criteria=("pytest test_a2.py passes",))
    task2 = task_store.create(contract2, context1, repo_root=str(repo_a))

    # task1 is ACTIVE while task2 is PLANNED -> ACTIVE task1 has priority!
    active_priority = task_store.get_active_task(str(repo_a))
    assert active_priority.task_id == task1.task_id

    # Complete task1
    task_store.transition(task1.task_id, TaskStatus.CANCELLED, reason="cancelled", actor="agent", idempotency_key="t1_c")

    # Now task2 (PLANNED) is the only active candidate
    active_after = task_store.get_active_task(str(repo_a))
    assert active_after.task_id == task2.task_id


def test_command_broker_auto_binds_active_task_and_captures_incident(tmp_path: Path):
    db_path = tmp_path / "state.db"
    state_store = AgentStateStore(str(db_path))
    task_store = TaskStore(state_store)
    verification_store = VerificationStore(state_store, task_store=task_store)
    task_store.set_verification_store(verification_store)

    incident_store = IncidentStore(state_store)

    artifacts = {}

    class _Artifacts:
        def put(self, text, tenant, kind, _content_type="application/json"):
            aid = f"art-{len(artifacts)+1}"
            artifacts[aid] = {
                "success": True,
                "artifact_id": aid,
                "kind": kind,
                "text": text,
                "next_offset": None,
                "tenant": tenant,
            }
            return aid

        def get(self, artifact_id, *, max_chars, tenant):
            return artifacts.get(artifact_id, {"success": False})

    class _RepoState:
        def fingerprint(self, cwd):
            return {"fingerprint": "hash123", "root": str(cwd)}

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
    broker.set_task_store(task_store)
    broker.set_verification_store(verification_store)
    broker.set_incident_store(incident_store)

    repo_dir = tmp_path / "my_project"
    repo_dir.mkdir()

    contract = GoalContract(
        goal="Run tests",
        acceptance_criteria=("pytest unit tests pass",),
    )
    task = task_store.create(contract, ScopeContext(repository_id=str(repo_dir)), repo_root=str(repo_dir))
    task_store.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="agent", idempotency_key="start_key")

    # 1. Successful test command without passing task_id or criterion
    # python -m pytest --version or echo test
    res = broker.run("pytest --version", cwd=str(repo_dir), tenant="agent")
    if res.get("success"):
        # Auto-bound task_id and criterion
        assert res.get("task_id") == task.task_id
        assert res.get("criterion") == "pytest unit tests pass"

    # 2. Failing validation command -> auto captures incident into IncidentStore
    fail_res = broker.run("pytest non_existent_test_file.py", cwd=str(repo_dir), tenant="agent")
    assert fail_res.get("success") is False
    assert fail_res.get("incident_id")
    assert fail_res.get("incident_recorded") is True


def test_http_memory_defaults_to_repository_scope_and_context_pack_injects_task(tmp_path: Path):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(f"""
[server]
bind = "127.0.0.1"
port = 11497
state_dir = "{state_dir.as_posix()}"

[agent_state]
enabled = true

[security]
api_token = "test-api-token-long-enough"
api_token_permissions = ["read", "write"]
api_token_tenant = "test-tenant"
tenant_derivation_key = "test-tenant-derivation-key-0123456789"
allowed_roots = ["{tmp_path.as_posix()}"]
""", encoding="utf-8")

    app = LocalAIApp(str(cfg_path))
    old_app = http_server.APP
    http_server.APP = app

    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def post_json(endpoint: str, data: dict) -> dict:
        data = {"root": str(tmp_path), **data}
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{endpoint}",
            data=json.dumps(data).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-LocalAI-Token": "test-api-token-long-enough",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise AssertionError(exc.read().decode("utf-8", errors="replace")) from exc

    try:
        # 1. Create memory record with kind=fact, NO scope specified
        mem_res = post_json(
            "/api/agent-state/memory",
            {
                "action": "record",
                "record": {
                    "kind": "fact",
                    "key": "framework_choice",
                    "value": "FastAPI v2",
                },
            },
        )
        assert mem_res["success"] is True
        record = mem_res["record"]
        # Must default to repository scope, not task!
        assert record["scope"] == "repository"
        assert record["key"] == "framework_choice"

        # 2. Create active task
        task_res = post_json(
            "/api/agent-state/tasks",
            {
                "action": "create",
                "task_id": "auto-pack-task-1",
                "goal": "Verify context pack auto injection",
                "contract": {
                    "goal": "Verify context pack auto injection",
                    "acceptance_criteria": ["All tests pass"],
                },
            },
        )
        assert task_res["success"] is True

        # Transition task to active
        post_json(
            "/api/agent-state/tasks",
            {
                "action": "transition",
                "task_id": "auto-pack-task-1",
                "status": "active",
                "reason": "starting",
            },
        )

        # 3. Call /api/context/pack WITHOUT task_id
        pack_res = post_json(
            "/api/context/pack",
            {
                "query": "architecture overview",
                "mode": "adaptive",
            },
        )
        assert pack_res["success"] is True
        # The active task was auto-bound!
        assert pack_res.get("task_id") == "auto-pack-task-1"
        assert "task_context" in pack_res or "context" in pack_res

    finally:
        server.shutdown()
        server.server_close()
        http_server.APP = old_app

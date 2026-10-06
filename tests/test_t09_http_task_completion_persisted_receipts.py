from __future__ import annotations

from pathlib import Path
import threading

from local_ai_hub import http_server, mcp_server
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import GoalContract, TaskCheckpoint
from local_ai_hub.app import LocalAIApp
from local_ai_hub.client import HubClient


def test_http_task_complete_uses_persisted_tenant_scoped_receipts(
    tmp_path: Path, monkeypatch
) -> None:
    tenant_id = "agent-t09"
    task_id = "task-t09-http-receipts"
    project_root = tmp_path / "repo"
    project_root.mkdir()
    test_dir = project_root / "tests"
    test_dir.mkdir()
    (test_dir / "test_project_rules.py").write_text(
        "def test_project_command():\n    assert 1 + 1 == 2\n",
        encoding="utf-8",
    )
    (project_root / ".local-ai.toml").write_text(
        '[commands]\ntest = "python -m pytest -q tests/test_project_rules.py"\n'
        '[verification_rules]\nrequired_commands = ["test"]\n',
        encoding="utf-8",
    )
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 11498\nstate_dir = "{state_dir.as_posix()}"\n'
        "\n[agent_state]\nenabled = true\n"
        '\n[security]\napi_token = "t09-test-token"\n',
        encoding="utf-8",
    )

    app = LocalAIApp(str(config_path))
    app.agent_tasks.create(
        GoalContract(
            goal="complete task through production HTTP route",
            acceptance_criteria=("test",),
        ),
        ScopeContext(repository_id=str(project_root), task_id=task_id),
        task_id=task_id,
        actor=tenant_id,
        repo_root=str(project_root),
    )
    command_result = app.commands.run_project_command(
        "test",
        str(project_root),
        tenant=tenant_id,
        task_id=task_id,
        criterion="test",
        timeout=60,
        force=True,
    )
    assert command_result.get("success") is True, command_result
    receipt = command_result.get("verification_receipt")
    assert isinstance(receipt, dict), command_result
    command_evidence = str(command_result.get("verification_evidence_id") or "")
    assert command_evidence
    repository_revision = str(receipt.get("repository_revision") or "")
    assert repository_revision
    task_state = app.agent_tasks.get(task_id)
    assert task_state is not None
    state_data = dict(task_state.checkpoint.state_data)
    state_data["repository_revision"] = repository_revision
    app.agent_tasks.checkpoint(
        task_id,
        TaskCheckpoint(
            phase=task_state.checkpoint.phase,
            next_action=task_state.checkpoint.next_action,
            affected_paths=task_state.checkpoint.affected_paths,
            evidence_ids=task_state.checkpoint.evidence_ids,
            blockers=task_state.checkpoint.blockers,
            state_data=state_data,
        ),
        actor=tenant_id,
        idempotency_key="t09-broker-revision",
    )
    preflight = app.agent_verification.completion(
        task_id, current_revision=repository_revision, current_mutation_generation=0
    )
    assert preflight.complete, (
        preflight.unsatisfied_criteria,
        preflight.stale_criteria,
        preflight.consistency,
        app.artifacts.get(command_evidence, max_chars=50_000, tenant=tenant_id),
        app.agent_tasks.get(task_id).owner,
    )

    monkeypatch.setattr(
        http_server,
        "_completion_revision_or_stop",
        lambda *_args: (repository_revision, None),
    )
    previous_app = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    previous_mcp_client = mcp_server.CLIENT
    mcp_client = HubClient(tenant=tenant_id, config_path=str(config_path), auto_start=False)
    mcp_client.agent = tenant_id
    mcp_client._http_host = "127.0.0.1"
    mcp_client._http_port = server.server_address[1]
    mcp_server.CLIENT = mcp_client
    try:
        before_unauthorized = app.agent_tasks.get(task_id)
        assert before_unauthorized is not None
        mcp_client.api_token = "wrong-t09-test-token"
        unauthorized = mcp_server.local_ai_coord(
            action="task_complete",
            task_id=task_id,
            root=str(project_root),
            reason="unauthorized completion attempt",
        )
        assert unauthorized["success"] is False, unauthorized
        assert unauthorized["status_code"] == 401, unauthorized
        after_unauthorized = app.agent_tasks.get(task_id)
        assert after_unauthorized == before_unauthorized

        mcp_client.api_token = "t09-test-token"
        before_cross_tenant = app.agent_tasks.get(task_id)
        task_events_before_cross_tenant = app.agent_tasks.state_store.events(
            stream_id=f"task:{task_id}"
        )
        mcp_client.tenant = "other-agent"
        mcp_client.agent = "other-agent"
        cross_tenant = mcp_server.local_ai_coord(
            action="task_complete",
            task_id=task_id,
            root=str(project_root),
            reason="cross-tenant completion attempt",
        )
        assert cross_tenant["success"] is False, cross_tenant
        after_cross_tenant = app.agent_tasks.get(task_id)
        assert after_cross_tenant == before_cross_tenant
        assert after_cross_tenant.status == before_cross_tenant.status
        assert after_cross_tenant.owner == before_cross_tenant.owner
        assert app.agent_tasks.state_store.events(
            stream_id=f"task:{task_id}"
        ) == task_events_before_cross_tenant

        mcp_client.tenant = tenant_id
        mcp_client.agent = tenant_id
        payload = mcp_server.local_ai_coord(
            action="task_complete",
            task_id=task_id,
            root=str(project_root),
            reason="persisted project receipts verified through MCP",
        )
        replay = mcp_server.local_ai_coord(
            action="task_complete",
            task_id=task_id,
            root=str(project_root),
            reason="repeat MCP task completion",
        )
        assert replay["success"] is True, replay
        assert replay["task"]["status"] == "completed"
    finally:
        mcp_server.CLIENT = previous_mcp_client
        mcp_client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        http_server.APP = previous_app
    assert payload["success"] is True, payload
    assert payload["task"]["task_id"] == task_id
    assert payload["task"]["status"] == "completed"
    stored = app.agent_tasks.get(task_id)
    assert stored is not None
    assert stored.owner == tenant_id
    assert stored.context.repository_id == str(project_root)
    assert stored.checkpoint.state_data["repo_root"] == str(project_root.resolve())
    assert stored.checkpoint.state_data["repository_revision"] == repository_revision

    completion = app.agent_verification.completion(
        task_id, current_revision=repository_revision, current_mutation_generation=0
    )
    assert completion.complete is True
    assert {
        (receipt.task_id, receipt.owner, receipt.criterion, receipt.repository_revision)
        for receipt in completion.receipts
    } == {(task_id, tenant_id, "test", repository_revision)}
    assert {receipt.evidence_id for receipt in completion.receipts} == {command_evidence}

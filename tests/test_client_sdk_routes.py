from __future__ import annotations

import threading

import pytest


@pytest.fixture
def live_client(tmp_path, monkeypatch):
    from local_ai_hub import http_server
    from local_ai_hub.app import LocalAIApp
    from local_ai_hub.client import HubClient

    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    config = tmp_path / "config.toml"
    state_dir = tmp_path / "state"
    config.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = {server.server_address[1]}\n'
        f'state_dir = "{state_dir.as_posix()}"\n'
        '[agent_state]\nenabled = true\n',
        encoding="utf-8",
    )
    app = LocalAIApp(str(config))
    monkeypatch.setattr(http_server, "APP", app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = HubClient(tenant="sdk-test", config_path=str(config), auto_start=False)
    try:
        yield app, client
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        app.close()


def test_sdk_convenience_methods_map_to_production_http_handlers(live_client, tmp_path):
    app, client = live_client
    routes = []
    root = str(tmp_path)

    def callers(actual_root, symbol, limit):
        routes.append(("callers", actual_root, symbol, limit))
        return {"success": True, "callers": ["Example.call"]}

    def fast_context(actual_root, query, max_tokens):
        routes.append(("context", actual_root, query, max_tokens))
        return {"success": True, "context": ["indexed evidence"]}

    def cancel(tenant, job_id):
        routes.append(("cancel", tenant, job_id))
        return {"success": True, "job_id": job_id, "cancelled": True}

    def evidence(evidence_id, *, verify=True):
        routes.append(("evidence", evidence_id, verify))
        return {"success": True, "evidence_id": evidence_id, "verified": verify}

    app.services.callers = callers
    app.services.fast_context = fast_context
    app.async_jobs.cancel = cancel
    app.evidence.get = evidence

    caller_result = client.callers(root, "Example", limit=7)
    context_result = client.context_pack(root, "find Example callers", max_tokens=512, mode="fast")
    cancel_result = client.cancel_job("job-123")
    evidence_result = client.get_evidence("E123", verify=False)

    assert caller_result["callers"] == ["Example.call"]
    assert context_result["delivery_mode"] == "fast"
    assert cancel_result["cancelled"] is True
    assert evidence_result["verified"] is False
    assert routes == [
        ("callers", root, "Example", 7),
        ("context", root, "find Example callers", 512),
        ("cancel", "sdk-test", "job-123"),
        ("evidence", "E123", False),
    ]


def test_context_pack_exposes_terminal_mode_errors_from_production_handler(live_client, tmp_path):
    _, client = live_client

    result = client.context_pack(str(tmp_path), "query", mode="invalid")

    assert result["success"] is False
    assert result["error"] == "context mode must be adaptive, full or fast"
    assert result["terminal"] is True
    assert result["retryable"] is False


def test_sdk_resume_and_verification_use_real_agent_state_handlers(live_client):
    from local_ai_hub.agent_tasks import TaskStatus

    app, client = live_client
    created = client.create_task(
        "SDK route flow",
        acceptance_criteria=["change_verified"],
        task_id="sdk-route-task",
    )
    assert created["success"] is True
    app.agent_tasks.transition(
        "sdk-route-task",
        TaskStatus.ACTIVE,
        reason="start route test",
        actor="sdk-test",
        idempotency_key="start-sdk-route-task",
    )

    resumed = client.coord(
        "task_resume",
        task_id="sdk-route-task",
        idempotency_key="resume-sdk-route-task",
    )
    receipt = client.verify_receipt(
        "sdk-route-task",
        "change_verified",
        evidence_id="E-sdk-route-test",
    )

    assert resumed["success"] is True
    assert resumed["task"]["status"] == TaskStatus.ACTIVE.value
    assert receipt["success"] is True
    assert receipt["receipt"]["criterion"] == "change_verified"

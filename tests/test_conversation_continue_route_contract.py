from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest



@pytest.fixture
def production_hub(tmp_path, monkeypatch):
    from local_ai_hub import http_server
    from local_ai_hub.app import LocalAIApp
    from local_ai_hub.client import HubClient

    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    state_dir = tmp_path / "state"
    config = tmp_path / "config.toml"
    config.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = {server.server_address[1]}\n'
        f'state_dir = "{state_dir.as_posix()}"\n',
        encoding="utf-8",
    )
    app = LocalAIApp(str(config))
    calls = []

    def fake_generate(model, prompt, system, max_tokens, temperature, tenant, source, priority, **kwargs):
        calls.append({"prompt": prompt, "system": system})
        return {"success": True, "model": model, "text": f"answer {len(calls)}"}

    app.services._generate = fake_generate
    monkeypatch.setattr(http_server, "APP", app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield app, HubClient(config_path=str(config), auto_start=False), calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        app.close()


def _start_conversation(client):
    return client.post(
        "/api/delegate",
        {"task": "first question", "context": "initial facts", "conversation": True},
    )


def test_empty_conversation_is_rejected_through_production_route(production_hub):
    _, client, calls = production_hub

    result = client.post("/api/delegate", {"task": "  ", "conversation": True})

    assert result["success"] is False
    assert result["error"] == "task is required"
    assert calls == []


def test_generic_hub_client_posts_async_job_actions_to_production_route(production_hub):
    app, client, _ = production_hub
    calls = []

    def submit(tenant, job_action, payload):
        calls.append(("submit", tenant, job_action, dict(payload)))
        return {"success": True, "job_id": "job-1"}

    def status(tenant, job_id):
        calls.append(("status", tenant, job_id))
        return {"success": True, "job_id": job_id, "state": "running"}

    def wait(tenant, job_id, timeout_seconds):
        calls.append(("wait", tenant, job_id, timeout_seconds))
        return {"success": True, "job_id": job_id, "state": "completed"}

    def result(tenant, job_id):
        calls.append(("result", tenant, job_id))
        return {"success": True, "job_id": job_id, "state": "completed"}

    def cancel(tenant, job_id):
        calls.append(("cancel", tenant, job_id))
        return {"success": True, "job_id": job_id, "state": "cancelled"}

    app.async_jobs.submit = submit
    app.async_jobs.status = status
    app.async_jobs.wait = wait
    app.async_jobs.result = result
    app.async_jobs.cancel = cancel

    submitted = client.post("/api/async-jobs", {
        "action": "submit", "job_action": "reason", "task": "summarize", "request_id": "stable-submit",
    })
    current = client.post("/api/async-jobs", {"action": "status", "job_id": "job-1"})
    waited = client.post(
        "/api/async-jobs", {"action": "wait", "job_id": "job-1", "timeout_seconds": 0.25}, timeout=1.0
    )
    fetched = client.post("/api/async-jobs", {"action": "result", "job_id": "job-1"})
    cancelled = client.post("/api/async-jobs", {"action": "cancel", "job_id": "job-1"})

    assert submitted["job_id"] == "job-1"
    assert current["state"] == "running"
    assert waited["state"] == "completed"
    assert fetched["state"] == "completed"
    assert cancelled["state"] == "cancelled"
    assert [call[0] for call in calls] == ["submit", "status", "wait", "result", "cancel"]
    assert all(call[1] == calls[0][1] for call in calls)
    assert calls[0][2:] == (
        "reason",
        {"action": "submit", "job_action": "reason", "task": "summarize", "request_id": "stable-submit"},
    )
    assert calls[2][2] == "job-1"
    assert calls[2][3] == pytest.approx(0.25)


def test_http_async_job_submit_rejects_conversation_payload(production_hub):
    _, client, _ = production_hub

    result = client.post(
        "/api/async-jobs",
        {"action": "submit", "job_action": "delegate", "task": "question", "conversation": True},
    )

    assert result["success"] is False
    assert result["error"] == "conversations require delivery=sync"
    assert result["terminal"] is True
    assert result["retryable"] is False


def test_hub_client_continues_through_production_route_and_preserves_transcript(production_hub):
    app, client, calls = production_hub
    service_payloads = []
    continue_conversation = app.services.continue_conversation

    def observe_service_boundary(payload, tenant):
        service_payloads.append(dict(payload))
        return continue_conversation(payload, tenant)

    app.services.continue_conversation = observe_service_boundary
    started = _start_conversation(client)
    prompt = "follow-up question"
    continued = client.continue_conversation(started["conversation_id"], prompt)

    assert continued["success"] is True
    assert continued["conversation_id"] == started["conversation_id"]
    assert service_payloads == [{"conversation_id": started["conversation_id"], "task": prompt}]
    assert "first question" in calls[1]["prompt"]
    assert "answer 1" in calls[1]["prompt"]
    assert prompt in calls[1]["prompt"]


def test_expired_conversation_is_terminal_through_production_route(production_hub):
    from local_ai_hub.conversations import ConversationStore

    app, client, _ = production_hub
    now = [100.0]
    app.services.conversations = ConversationStore(idle_ttl_seconds=5, clock=lambda: now[0])
    started = _start_conversation(client)
    now[0] += 6

    expired = client.continue_conversation(started["conversation_id"], "follow-up")

    assert expired["success"] is False
    assert expired["error"] == "conversation not found"
    assert expired["terminal"] is True
    assert expired["retryable"] is False


def test_competing_continuation_is_retryable_in_progress_through_production_route(production_hub):
    app, client, _ = production_hub
    started = _start_conversation(client)
    entered_generation = threading.Event()
    release_generation = threading.Event()

    def blocking_generate(model, prompt, system, max_tokens, temperature, tenant, source, priority, **kwargs):
        entered_generation.set()
        if not release_generation.wait(timeout=10):
            raise TimeoutError("test did not release blocked generation")
        return {"success": True, "model": model, "text": "follow-up answer"}

    app.services._generate = blocking_generate
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(client.continue_conversation, started["conversation_id"], "first follow-up")
        try:
            assert entered_generation.wait(timeout=5)
            competing = client.continue_conversation(started["conversation_id"], "competing follow-up")
        finally:
            release_generation.set()
        completed = pending.result(timeout=10)

    assert competing["success"] is False
    assert competing["retryable"] is True
    assert competing["in_progress"] is True
    assert completed["success"] is True

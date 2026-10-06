from __future__ import annotations

import threading

import pytest


@pytest.fixture
def production_hub(tmp_path, monkeypatch):
    from local_ai_hub import http_server
    from local_ai_hub.app import LocalAIApp
    from local_ai_hub.client import HubClient

    monkeypatch.setattr(http_server, "_ACTIVE_TRANSCRIPTIONS", http_server._ActiveTranscriptionRegistry())
    monkeypatch.setattr(http_server, "_ACTIVE_CONVERSATIONS", http_server._ActiveTranscriptionRegistry())
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    state_dir = tmp_path / "state"
    config = tmp_path / "config.toml"
    config.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = {server.server_address[1]}\n'
        f'state_dir = "{state_dir.as_posix()}"\n',
        encoding="utf-8",
    )
    app = LocalAIApp(str(config))

    def fake_generate(model, prompt, system, max_tokens, temperature, tenant, source, priority, **kwargs):
        return {"success": True, "model": model, "text": "initial answer"}

    app.services._generate = fake_generate
    monkeypatch.setattr(http_server, "APP", app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield app, HubClient(config_path=str(config), auto_start=False)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        app.close()


def test_gaming_release_receipt_includes_conversation_cancelled_before_snapshot(production_hub):
    from local_ai_hub import http_server

    app, client = production_hub
    initial = client.post(
        "/api/delegate",
        {"task": "initial prompt", "context": "facts", "conversation": True},
    )
    assert initial["success"] is True
    generation_started = threading.Event()
    cancellation_observed = threading.Event()
    allow_worker_exit = threading.Event()
    worker_exited = threading.Event()
    unload_attempted = threading.Event()
    unload_observed = threading.Event()
    results = []

    def blocking_generate(*_args, cancel_event=None, **_kwargs):
        generation_started.set()
        if cancel_event is not None and cancel_event.wait(timeout=3.0):
            cancellation_observed.set()
            if not allow_worker_exit.wait(timeout=3.0):
                return {"success": False, "error": "test worker exit gate timed out"}
            worker_exited.set()
            return {
                "success": False, "cancelled": True, "preempted": True,
                "reason": "cancelled", "terminal": True, "retryable": False,
            }
        return {"success": True, "text": "late answer"}

    class Runtime:
        config = {"ollama": {"enabled": True}}

        def unload_configured_models(self, **_kwargs):
            unload_attempted.set()
            assert cancellation_observed.is_set()
            assert worker_exited.is_set()
            unload_observed.set()
            return {"success": True, "state": "complete", "verified": True}

    app.services._generate = blocking_generate
    app.runtime = Runtime()
    app.embeddings = None
    app.reranker = None
    continuation = threading.Thread(target=lambda: results.append(client.post(
        "/api/conversations/continue",
        {"conversation_id": initial["conversation_id"], "task": "follow up"},
    )))
    continuation.start()
    assert generation_started.wait(timeout=2.0)

    mode_results = []
    mode_change = threading.Thread(target=lambda: mode_results.append(
        client.post("/api/admin/mode", {"mode": "gaming"})
    ))
    mode_change.start()
    assert cancellation_observed.wait(timeout=2.0)
    assert not worker_exited.is_set()
    assert not unload_attempted.wait(timeout=0.5)
    assert not unload_observed.is_set()
    allow_worker_exit.set()
    mode_change.join(timeout=4.0)
    continuation.join(timeout=3.0)

    assert not mode_change.is_alive()
    assert not continuation.is_alive()
    mode_result = mode_results[0]
    assert results[0]["success"] is False
    assert results[0]["cancelled"] is True
    assert mode_result["success"] is True
    assert mode_result["mode"] == "gaming"
    assert mode_result["conversation_release"] == {
        "state": "cancelled",
        "inference_active": False,
        "active": 0,
        "cancelled": True,
    }
    assert cancellation_observed.is_set()
    assert worker_exited.is_set()
    assert unload_observed.is_set()

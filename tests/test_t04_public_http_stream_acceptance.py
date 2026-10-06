from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError

import pytest

from local_ai_hub import http_server
from local_ai_hub.client import HubClient


def test_public_http_conversation_auth_stream_cancel_and_deadline(tmp_path, monkeypatch) -> None:
    from contextlib import ExitStack
    from local_ai_hub.agent_events import AgentEvent
    from local_ai_hub.app import LocalAIApp

    token = "T04_PUBLIC_HTTP_STREAM_SECRET_123"
    with ExitStack() as cleanup:
        server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
        server.daemon_threads = True
        cleanup.callback(server.server_close)
        config = tmp_path / "public-hub.toml"
        config.write_text(
            f'[server]\nbind="127.0.0.1"\nport={server.server_address[1]}\n'
            f'state_dir="{(tmp_path / "state").as_posix()}"\nmax_stream_duration_seconds=5\n'
            f'[security]\napi_token="{token}"\n[agent_state]\nenabled=true\n',
            encoding="utf-8",
        )
        app = LocalAIApp(str(config))
        cleanup.callback(app.close)
        generated = []

        def fake_generate(model, prompt, system, max_tokens, temperature, tenant, source, priority, **kwargs):
            generated.append(prompt)
            return {"success": True, "model": model, "text": f"fixture answer {len(generated)}"}

        app.services._generate = fake_generate
        monkeypatch.setattr(http_server, "APP", app)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        def join_server_thread() -> None:
            server_thread.join(timeout=2)
            assert not server_thread.is_alive(), "HTTP server thread did not stop"

        cleanup.callback(join_server_thread)
        cleanup.callback(server.shutdown)
        client = HubClient(config_path=str(config), auto_start=False)
        cleanup.callback(client.close)
        unauth_config = tmp_path / "unauthorized.toml"
        unauth_config.write_text(
            f'[server]\nbind="127.0.0.1"\nport={server.server_address[1]}\n'
            f'state_dir="{(tmp_path / "unauth-state").as_posix()}"\n',
            encoding="utf-8",
        )
        unauth_client = HubClient(config_path=str(unauth_config), auto_start=False)
        cleanup.callback(unauth_client.close)
        stream_id = "t04-public-auth-cancel"
        appended = app.agent_state.append(
            AgentEvent.create(stream_id, "update", {"public": True}, idempotency_key="t04-public-seed")
        )
        assert appended.error is None
        unauthorized_events = unauth_client.stream_events(stream_id=stream_id, timeout=1)
        cleanup.callback(unauthorized_events.close)
        authorized_events = None
        deadline_events = None
        try:
            denied = unauth_client.post(
                "/api/delegate", {"task": "unauthorized conversation", "conversation": True}
            )
            assert denied["status_code"] == 401
            assert generated == []

            started = client.post(
                "/api/delegate", {"task": "authenticated start", "conversation": True}
            )
            continued = client.continue_conversation(started["conversation_id"], "authenticated follow-up")
            assert started["success"] is True
            assert continued["success"] is True
            assert continued["conversation_id"] == started["conversation_id"]
            assert len(generated) == 2

            with pytest.raises(HTTPError) as error:
                next(unauthorized_events)
            assert error.value.code == 401
            error.value.close()

            cancel = threading.Event()
            authorized_events = client.stream_events(
                stream_id=stream_id, timeout=0, cancel_event=cancel
            )
            cleanup.callback(authorized_events.close)
            kind, payload = next(authorized_events)
            assert kind == "update"
            assert payload["payload"] == {"public": True}
            started = threading.Event()

            def read_next():
                started.set()
                return next(authorized_events, None)

            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(read_next)
                assert started.wait(1)
                time.sleep(0.05)
                cancel.set()
                assert pending.result(timeout=1) is None
            cancel_wake = app.agent_state.append(
                AgentEvent.create(stream_id, "update", {"wake": "cancel"}, idempotency_key="t04-cancel-wake")
            )
            assert cancel_wake.error is None

            client.max_request_timeout = 0.2
            deadline_events = client.stream_events(stream_id="t04-public-deadline", timeout=0)
            cleanup.callback(deadline_events.close)
            started_at = time.monotonic()
            kind, result = next(deadline_events)
            assert kind == "error"
            assert result["retry_timeout"] is True
            assert result["outcome_unknown"] is True
            assert time.monotonic() - started_at < 1.0
            deadline_wake = app.agent_state.append(
                AgentEvent.create("t04-public-deadline", "update", {"wake": "deadline"}, idempotency_key="t04-deadline-wake")
            )
            assert deadline_wake.error is None
        finally:
            if authorized_events is not None:
                authorized_events.close()
            if deadline_events is not None:
                deadline_events.close()

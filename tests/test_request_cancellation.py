from __future__ import annotations

import asyncio
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from local_ai_hub.client import CURRENT_REQUEST_CANCEL_EVENT, HubClient


def test_mcp_adapter_cancellation_reaches_worker_and_restores_context():
    from local_ai_hub.mcp_server import _async_mcp_adapter

    started = threading.Event()
    ended = threading.Event()

    def worker():
        event = CURRENT_REQUEST_CANCEL_EVENT.get()
        assert event is not None
        started.set()
        try:
            assert event.wait(3)
        finally:
            ended.set()

    async def scenario():
        task = asyncio.create_task(_async_mcp_adapter(worker)())
        deadline = time.monotonic() + 3
        while not started.is_set() and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        assert started.is_set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert CURRENT_REQUEST_CANCEL_EVENT.get() is None

    asyncio.run(scenario())
    assert ended.is_set()


def test_context_cancellation_interrupts_blocked_http_receive(tmp_path):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    accepted = threading.Event()
    cancel = threading.Event()

    def serve():
        with listener.accept()[0] as connection:
            connection.settimeout(3)
            connection.recv(65536)
            accepted.set()
            # No response headers: the client is blocked in getresponse().
            while connection.recv(65536):
                pass

    config = tmp_path / "hub.toml"
    config.write_text(
        f'[server]\nport={listener.getsockname()[1]}\nstate_dir="{(tmp_path / "state").as_posix()}"\n',
        encoding="utf-8",
    )
    hub = HubClient(config_path=str(config), auto_start=False)

    def call():
        token = CURRENT_REQUEST_CANCEL_EVENT.set(cancel)
        try:
            return hub.post("/api/command", {"action": "stats"}, timeout=30)
        finally:
            CURRENT_REQUEST_CANCEL_EVENT.reset(token)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            server_future = pool.submit(serve)
            future = pool.submit(call)
            try:
                assert accepted.wait(3)
                cancel.set()
                result = future.result(timeout=2)
                assert result["cancelled"] is True
                assert result.get("request_not_sent") is not True
                assert result["outcome_unknown"] is True
                server_future.result(timeout=2)
            finally:
                cancel.set()
    finally:
        listener.close()


def test_disconnected_coalesced_waiter_does_not_cancel_execution_owner(tmp_path, monkeypatch):
    from test_command_concurrency_contract import _broker, _execution_result

    broker = _broker(tmp_path)
    owner_cancel = threading.Event()
    waiter_cancel = threading.Event()
    started = threading.Event()
    executions = []

    def execute(command, cwd, timeout, cancel_event=None, **kwargs):
        executions.append(cancel_event)
        started.set()
        assert cancel_event.wait(3)
        return {**_execution_result("cancelled"), "success": False, "cancelled": True}

    monkeypatch.setattr(broker, "_execute", execute)
    with ThreadPoolExecutor(max_workers=2) as pool:
        owner = pool.submit(broker.run, "python -m pytest -q", str(tmp_path), request_cancel_event=owner_cancel)
        try:
            assert started.wait(2)
            waiter = pool.submit(broker.run, "python -m pytest -q", str(tmp_path), request_cancel_event=waiter_cancel)
            deadline = time.monotonic() + 2
            while not broker.coalesced and time.monotonic() < deadline:
                time.sleep(0.01)
            assert broker.coalesced
            waiter_cancel.set()
            result = waiter.result(timeout=1)
            assert result["cancelled"] is True
            assert result["coalesced"] is True
            assert not owner_cancel.is_set()
            assert not owner.done()
        finally:
            owner_cancel.set()
        assert owner.result(timeout=2)["cancelled"] is True
    assert executions == [owner_cancel]

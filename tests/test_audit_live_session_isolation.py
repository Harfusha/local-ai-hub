"""Real MCP sessions and HTTP dispatch must never adopt another chat's task."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import threading
import time
from types import SimpleNamespace
import urllib.error
import urllib.request

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from local_ai_hub import http_server, mcp_server
from local_ai_hub.app import LocalAIApp
from local_ai_hub.client import HubClient
from local_ai_hub.commands import CommandBroker


@pytest.fixture
def isolated_hub(tmp_path, monkeypatch):
    roots = [tmp_path / "repository-a", tmp_path / "repository-b"]
    for root in roots:
        root.mkdir()
    config = tmp_path / "config.toml"

    def write_config(port):
        config.write_text(
            f'[server]\nbind = "127.0.0.1"\nport = {port}\n'
            f'state_dir = "{(tmp_path / "state").as_posix()}"\n'
            '[agent_state]\nenabled = true\n'
            '[prewarm]\nenabled = false\n'
            '[headless]\nmanage_ollama = false\n'
            '[security]\napi_token = "isolated-session-acceptance-token"\n'
            'api_token_permissions = ["read", "write"]\n'
            f'allowed_roots = ["{tmp_path.as_posix()}"]\n', encoding="utf-8",
        )

    write_config(11497)
    app = LocalAIApp(str(config))
    retrievals = []
    lock = threading.Lock()

    def bounded_retrieval(root, *_args, **_kwargs):
        with lock:
            retrievals.append(root)
        return {"success": True, "context": f"ISOLATED:{root}", "evidence": []}

    # Retrieval generation is outside this identity test; HTTP authorization,
    # root/session/task binding, real task storage and MCP framing remain real.
    monkeypatch.setattr(app.services, "_hybrid_context_uncached", bounded_retrieval)
    monkeypatch.setattr(http_server, "APP", app)
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    write_config(server.server_address[1])
    client = HubClient(config_path=str(config), auto_start=False)
    monkeypatch.setattr(mcp_server, "CLIENT", mcp_server._MCPHubClientAdapter(client))
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda _event: None)
    for _ in range(100):
        try:
            res = client.get("/health")
            if res.get("success"):
                break
        except Exception:
            pass
        time.sleep(0.01)

    def post(endpoint, payload):
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}{endpoint}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "X-LocalAI-Token": "isolated-session-acceptance-token",
                     "Connection": "close"}, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read(256_001))
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.loads(error.read(256_001))

    try:
        for index, root in enumerate(roots):
            payload = {
                "root": str(root), "action": "create", "task_id": f"isolated-task-{index}",
                "goal": "Isolated fixture task",
                "context": {"session_id": f"isolated-chat-{index}"},
                "contract": {"goal": "Isolated fixture task", "acceptance_criteria": []},
            }
            status, created = post("/api/agent-state/tasks", payload)
            assert status == 200 and created["success"] is True, created
            status, active = post("/api/agent-state/tasks", {
                "root": str(root), "action": "transition", "task_id": payload["task_id"],
                "status": "active", "reason": "isolated test start",
            })
            assert status == 200 and active["success"] is True, active
        yield app, roots, post, retrievals
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        serving.join(timeout=3)
        assert not serving.is_alive()
        app.close()
        assert not app.close_report["failed"] and not app.close_report["pending"], app.close_report


def _assert_unbound(result, own_root, foreign_root):
    assert result["success"] is True, result
    assert not result.get("task_id"), result
    assert "task_context" not in result, result
    serialized = json.dumps(result)
    assert str(foreign_root).replace("\\", "\\\\") not in serialized
    assert "isolated-task-" not in serialized
    assert "ISOLATED:" in serialized, result
    assert own_root.name in serialized


def test_two_http_chats_do_not_adopt_active_tasks(isolated_hub):
    _app, roots, post, retrievals = isolated_hub
    barrier = threading.Barrier(2)

    def request(index):
        barrier.wait(timeout=5)
        status, result = post("/api/context/pack", {
            "root": str(roots[index]), "session_id": f"isolated-chat-{index}",
            "query": "same isolated query", "mode": "adaptive",
        })
        assert status == 200, result
        _assert_unbound(result, roots[index], roots[1 - index])

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(request, index) for index in range(2)]
        for future in futures:
            future.result(timeout=15)
    assert set(retrievals) == {str(root.resolve()) for root in roots}


def test_two_unbound_commands_never_look_up_active_tasks(isolated_hub, tmp_path, monkeypatch):
    app, roots, _post, _retrievals = isolated_hub

    def implicit_lookup(*_args, **_kwargs):
        pytest.fail("unbound command attempted implicit active-task lookup")

    monkeypatch.setattr(app.agent_tasks, "get_active_task", implicit_lookup)
    broker = CommandBroker({
        "server": {"state_dir": str(tmp_path / "command-state")},
        "commands": {"enabled": True, "allow_read": True},
    }, repo_state=SimpleNamespace(fingerprint=lambda _root: {}))
    broker.set_task_store(app.agent_tasks)
    barrier = threading.Barrier(2)

    def run(index):
        barrier.wait(timeout=5)
        result = broker.run("git --version", str(roots[index]), timeout=5, bypass_cache=True)
        assert result["success"] is True, result
        assert not result.get("task_id"), result
        assert "verification_receipt" not in result
        assert "git version" in result["stdout"]

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run, index) for index in range(2)]
        for future in futures:
            future.result(timeout=15)


def test_fresh_mcp_sessions_after_task_completion_keep_explicit_scope(isolated_hub):
    _app, roots, post, _retrievals = isolated_hub

    async def request(index):
        async with create_connected_server_and_client_session(
            mcp_server.mcp, read_timeout_seconds=timedelta(seconds=8),
        ) as session:
            result = await session.call_tool("local_ai_repo", {
                "action": "context", "root": str(roots[index]),
                "query": "same isolated MCP query", "mode": "adaptive",
                "max_response_tokens": 3200, "response_profile": "compact",
            })
            assert not result.isError, result
            structured = result.structuredContent
            value = structured if structured is not None else json.loads(result.content[0].text)
            _assert_unbound(value, roots[index], roots[1 - index])

    async def parallel_sessions():
        await asyncio.gather(request(0), request(1))

    asyncio.run(parallel_sessions())
    for phase in ("verifying", "completed"):
        status, completed = post("/api/agent-state/tasks", {
            "root": str(roots[0]), "action": "transition", "task_id": "isolated-task-0",
            "status": phase, "reason": "isolated fixture work complete",
        })
        assert status == 200 and completed["success"] is True, completed
    # Both sessions are closed; initialize two genuinely new MCP connections.
    asyncio.run(parallel_sessions())


@pytest.mark.parametrize("wrong_field", ["root", "session_id"])
def test_explicit_task_context_rejects_foreign_identity_before_retrieval(isolated_hub, wrong_field):
    _app, roots, post, retrievals = isolated_hub
    payload = {"root": str(roots[0]), "session_id": "isolated-chat-0",
               "task_id": "isolated-task-0", "query": "explicit task", "mode": "adaptive"}
    payload[wrong_field] = str(roots[1]) if wrong_field == "root" else "isolated-chat-1"
    payload.update(action="compile", token_budget=1024)
    status, result = post("/api/agent-state/context", payload)
    assert status == 403, result
    assert result["success"] is False
    assert retrievals == []


def test_repository_memory_defaults_remain_isolated_with_two_active_chats(isolated_hub):
    _app, roots, post, _retrievals = isolated_hub
    stored = []
    for index, root in enumerate(roots):
        status, result = post("/api/agent-state/memory", {
            "root": str(root), "action": "record",
            "record": {"kind": "fact", "key": "isolation-marker",
                       "value": f"repository-{index}-private-value"},
        })
        assert status == 200 and result["success"] is True, result
        assert result["record"]["scope"] == "repository"
        stored.append(result["record"])
    assert stored[0]["scope_id"] != stored[1]["scope_id"]
    for index, root in enumerate(roots):
        status, found = post("/api/agent-state/memory", {
            "root": str(root), "action": "find", "scope": "repository",
            "query": "isolation-marker", "semantic": False, "limit": 10,
        })
        assert status == 200 and found["success"] is True, found
        assert [record["record_id"] for record in found["records"]] == [stored[index]["record_id"]]
        assert f"repository-{1 - index}-private-value" not in json.dumps(found)

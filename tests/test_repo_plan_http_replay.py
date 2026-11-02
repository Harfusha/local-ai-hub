"""Plan replay through registered MCP, real HTTP, and file-backed storage."""

import asyncio
import threading
from pathlib import Path

import pytest

from local_ai_hub import http_server, mcp_server
from local_ai_hub.app import LocalAIApp
from local_ai_hub.client import HubClient
from local_ai_hub.repo_plan.workspace import RepoPlanWorkspace


@pytest.mark.parametrize("action", ["plan_create", "plan_update", "plan_task_edit", "plan_task_delete", "plan_archive", "plan_adopt_legacy_board"])
def test_plan_update_retry_through_real_http_and_mcp(tmp_path, monkeypatch, action):
    import local_ai_hub.repo_plan.workspace as workspace_module
    assert Path(workspace_module.__file__).resolve().is_relative_to(Path(__file__).resolve().parents[1] / "src")
    root = tmp_path / "repo"
    root.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    config = tmp_path / "config.toml"
    config.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 11498\nstate_dir = "{state.as_posix()}"\n'
        f'\n[security]\napi_token = "test-token"\nallowed_roots = ["{root.as_posix()}"]\n',
        encoding="utf-8",
    )
    workspace = RepoPlanWorkspace(root)
    workspace.init_workspace()
    created = None if action in {"plan_create", "plan_adopt_legacy_board"} else workspace.create_plan(plan_id="plan_replay", title="Initial")
    if action in {"plan_task_edit", "plan_task_delete"}:
        created = workspace.edit_task("plan_replay", "task_a", title="Initial", expected_revision=created["file_revision"])
    app = LocalAIApp(str(config))
    monkeypatch.setattr(http_server, "APP", app)
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = HubClient(config_path=str(config), auto_start=False)
    client._http_host, client._http_port = server.server_address
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    arguments = {"action": action, "root": str(root), "plan_id": "plan_replay",
                 "idempotency_key": "http-retry"}
    if created is not None:
        arguments["expected_revision"] = created["file_revision"]
    if action in {"plan_create", "plan_update", "plan_adopt_legacy_board"}:
        arguments["title"] = "First"
        different = {**arguments, "title": "Different"}
    elif action == "plan_task_edit":
        arguments.update(task_id="task_a", task_data={"title": "First"})
        different = {**arguments, "task_data": {"title": "Different"}}
    elif action == "plan_task_delete":
        arguments["task_id"] = "task_a"
        different = {**arguments, "task_id": "task_b"}
    else:
        different = {**arguments, "owner": "different-owner"}
    try:
        _, first = asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", arguments))
        assert first["success"] is True, first
        assert first["mutation_applied"] is True
        later = workspace.update_plan("plan_replay", description="Later", expected_revision=first["file_revision"])
        _, replay = asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", arguments))
        assert replay["success"] is True, replay
        assert replay["file_revision"] == first["file_revision"]
        assert replay["mutation_applied"] is True
        assert workspace.get_plan("plan_replay")["file_revision"] == later["file_revision"]
        _, conflict = asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", different))
        assert conflict["success"] is False
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

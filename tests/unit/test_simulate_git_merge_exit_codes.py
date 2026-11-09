import subprocess

import pytest

from local_ai_hub.process_utils import simulate_git_merge


@pytest.fixture
def conflicted_repo(tmp_path):
    def git(*args):
        return subprocess.run(["git", "-C", str(tmp_path), *args], check=True,
                              capture_output=True, text=True, timeout=15)

    def commit(message):
        git("add", "--", "conflict.txt")
        git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
            "-c", "commit.gpgsign=false", "commit", "-qm", message)

    git("-c", "init.templateDir=", "init", "-q", "-b", "target")
    path = tmp_path / "conflict.txt"
    path.write_text("base\n", encoding="utf-8")
    commit("base")
    git("checkout", "-qb", "source")
    path.write_text("source\n", encoding="utf-8")
    commit("source")
    git("checkout", "-q", "target")
    path.write_text("target\n", encoding="utf-8")
    commit("target")
    return tmp_path


def test_invalid_ref_is_not_a_successful_conflict(conflicted_repo):
    result = simulate_git_merge(conflicted_repo, "does-not-exist", "target")
    assert result["success"] is False, result.get("conflicts")
    assert result["exit_code"] != 0
    assert result["error"]
    assert "mergeable" not in result


def test_real_conflict_remains_a_successful_simulation(conflicted_repo):
    result = simulate_git_merge(conflicted_repo, "source", "target")
    assert result["success"] is True
    assert result["mergeable"] is False and result["exit_code"] == 1
    assert any("conflict" in item.lower() for item in result["conflicts"])


def test_clean_merge_is_successful(conflicted_repo):
    result = simulate_git_merge(conflicted_repo, "target", "target")
    assert result["success"] is True
    assert result["mergeable"] is True and result["exit_code"] == 0
    assert result["conflicts"] == []


def test_service_simulates_real_conflict(conflicted_repo):
    from local_ai_hub.services import LocalAIServices

    service = object.__new__(LocalAIServices)
    result = service.simulate_merge(str(conflicted_repo), "source", "target")
    assert result["success"] is True
    assert result["mergeable"] is False and result["exit_code"] == 1


def test_loopback_merge_simulation_enforces_root_policy(conflicted_repo, monkeypatch):
    import asyncio
    import json
    import threading
    from local_ai_hub import http_server, mcp_server
    from local_ai_hub.app import LocalAIApp
    from local_ai_hub.client import HubClient
    from local_ai_hub import process_utils
    from unittest.mock import Mock

    merge_spy = Mock(wraps=process_utils.simulate_git_merge)
    monkeypatch.setattr(process_utils, "simulate_git_merge", merge_spy)
    outside = conflicted_repo.parent / (conflicted_repo.name + "_outside")
    outside.mkdir()
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    config = conflicted_repo / "hub-test.toml"
    state = conflicted_repo / "hub-state"
    config.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = {server.server_address[1]}\n'
        f'state_dir = "{state.as_posix()}"\n'
        '[agent_state]\nenabled = true\n[security]\n'
        f'allowed_roots = ["{conflicted_repo.as_posix()}"]\n', encoding="utf-8"
    )
    app = LocalAIApp(str(config))
    monkeypatch.setattr(http_server, "APP", app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = HubClient(config_path=str(config), auto_start=False)
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server.FEATURES, "agent_os", True)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_: None)
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda _event: None)
    try:
        result = client.coord(action="simulate_merge", root=str(conflicted_repo),
                              source_branch="source", target_branch="target")
        assert result["success"] is True, result
        assert result["mergeable"] is False and result["exit_code"] == 1
        assert merge_spy.call_count == 1
        wire = asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", {
            "action": "simulate_merge", "root": str(conflicted_repo),
            "source_branch": "source", "target_branch": "target", "response_profile": "compact",
        }))
        blocks = wire[0] if isinstance(wire, tuple) else wire
        projected = json.loads(blocks[0].text)
        assert projected["success"] is True, projected
        assert projected["mergeable"] is False and projected["exit_code"] == 1
        assert projected["conflicts"]
        assert merge_spy.call_count == 2
        invalid_wire = asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", {
            "action": "simulate_merge", "root": str(conflicted_repo),
            "source_branch": "missing-branch", "target_branch": "target", "response_profile": "compact",
        }))
        invalid_blocks = invalid_wire[0] if isinstance(invalid_wire, tuple) else invalid_wire
        invalid = json.loads(invalid_blocks[0].text)
        assert invalid["success"] is False, invalid
        assert invalid.get("error") and invalid.get("mergeable") is None, invalid
        assert merge_spy.call_count == 3
        denied_wire = asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", {
            "action": "simulate_merge", "root": str(outside),
            "source_branch": "source", "target_branch": "target", "response_profile": "compact",
        }))
        denied_blocks = denied_wire[0] if isinstance(denied_wire, tuple) else denied_wire
        denied_mcp = json.loads(denied_blocks[0].text)
        assert denied_mcp["success"] is False, denied_mcp
        assert merge_spy.call_count == 3
        denied = client.coord(action="simulate_merge", root=str(outside),
                              source_branch="source", target_branch="target")
        assert denied["success"] is False, denied
        assert denied.get("status_code") == 403, denied
        assert denied.get("error_code") == "root_not_allowed", denied
        missing = client.post("/api/coord/simulate_merge", {"source_branch": "source"})
        assert missing["success"] is False and missing.get("status_code") == 400, missing
        assert merge_spy.call_count == 3
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        app.close()

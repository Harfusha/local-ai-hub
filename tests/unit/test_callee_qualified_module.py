import pytest

from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.repo_tools import RepositoryTools


@pytest.fixture
def engine_and_root(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "mod.py").write_text("def target():\n    return helper()\n", encoding="utf-8")
    (package / "other.py").write_text("def target():\n    return wrong()\n", encoding="utf-8")
    engine = object.__new__(DeterministicEngine)
    engine.repo_tools = RepositoryTools({})
    return engine, str(tmp_path)


@pytest.mark.parametrize("symbol", ["pkg.mod::target", "pkg::mod::target"])
def test_qualified_callees_resolve_only_exact_module(engine_and_root, symbol):
    engine, root = engine_and_root
    result = engine.find_callees(root, symbol)
    assert result["success"] is True, result
    assert {item["callee"] for item in result["callees"]} == {"helper"}
    assert {item["file"] for item in result["callees"]} == {"pkg/mod.py"}


def test_ambiguous_unqualified_callee_still_fails(engine_and_root):
    engine, root = engine_and_root
    result = engine.find_callees(root, "target")
    assert result["success"] is False
    assert result["coverage"]["resolution"] == "ambiguous_unqualified_definition"


def test_dotted_name_without_separator_still_rejected(engine_and_root):
    engine, root = engine_and_root
    result = engine.find_callees(root, "pkg.mod.target")
    assert result["success"] is False
    assert result["coverage"]["resolution"] == "unsupported_qualification"


def test_src_layout_resolves_module_without_src_prefix(tmp_path):
    module = tmp_path / "src" / "pkg" / "mod.py"
    module.parent.mkdir(parents=True)
    module.write_text("def target():\n    return helper()\n", encoding="utf-8")
    engine = object.__new__(DeterministicEngine)
    engine.repo_tools = RepositoryTools({})
    result = engine.find_callees(str(tmp_path), "pkg.mod::target")
    assert result["success"] is True, result
    assert [item["callee"] for item in result["callees"]] == ["helper"]


def test_src_layout_suffix_collision_fails_closed(tmp_path):
    for prefix in ("src", "vendor_copy"):
        module = tmp_path / prefix / "pkg" / "mod.py"
        module.parent.mkdir(parents=True)
        module.write_text("def target():\n    return helper()\n", encoding="utf-8")
    engine = object.__new__(DeterministicEngine)
    engine.repo_tools = RepositoryTools({})
    result = engine.find_callees(str(tmp_path), "pkg.mod::target")
    assert result["success"] is False
    assert result["coverage"]["resolution"] == "ambiguous_qualified_definition"


def test_duplicate_definition_in_same_module_fails_closed(tmp_path):
    module = tmp_path / "pkg" / "mod.py"
    module.parent.mkdir(parents=True)
    module.write_text(
        "def target():\n    return first()\n\ndef target():\n    return second()\n",
        encoding="utf-8",
    )
    engine = object.__new__(DeterministicEngine)
    engine.repo_tools = RepositoryTools({})
    result = engine.find_callees(str(tmp_path), "pkg.mod::target")
    assert result["success"] is False
    assert result["callees"] == []
    assert result["coverage"]["resolution"] == "ambiguous_qualified_definition"


def test_qualified_call_graph_through_loopback_mcp(tmp_path, monkeypatch):
    import asyncio
    import threading

    from local_ai_hub import http_server, mcp_server
    from local_ai_hub.app import LocalAIApp
    from local_ai_hub.client import HubClient

    project = tmp_path / "project"
    module = project / "src" / "pkg" / "mod.py"
    module.parent.mkdir(parents=True)
    module.write_text("def target():\n    return helper()\n", encoding="utf-8")
    (project / "caller.py").write_text("def caller():\n    return target()\n", encoding="utf-8")
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    config = tmp_path / "hub-test.toml"
    config.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = {server.server_address[1]}\n'
        f'state_dir = "{(tmp_path / "state").as_posix()}"\n'
        f'[security]\nallowed_roots = ["{project.as_posix()}"]\n', encoding="utf-8",
    )
    app = LocalAIApp(str(config))
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(app.services, "code_index", None)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    client = HubClient(config_path=str(config), auto_start=False)
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_: None)
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda _event: None)
    try:
        _, result = asyncio.run(mcp_server.mcp.call_tool("local_ai_repo", {
            "action": "call_graph", "root": str(project), "query": "pkg.mod::target",
            "depth": 1, "limit": 5, "response_profile": "compact",
        }))
        assert result["success"] is True, result
        assert any(item["callee"] == "helper" for item in result["callees"])
        assert any(item["caller"] == "caller" for item in result["callers"])
        assert result["partial"] is True  # qualified callers remain syntactic and freshness unchecked
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
        app.close()

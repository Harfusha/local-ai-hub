import asyncio
from pathlib import Path

from local_ai_hub import mcp_server
from local_ai_hub.mcp_server import mcp


def _call_tool(name, arguments):
    return asyncio.run(mcp.call_tool(name, arguments))


def test_mcp_module_comes_from_current_checkout():
    expected = Path(__file__).resolve().parents[2] / "src" / "local_ai_hub" / "mcp_server.py"
    assert Path(mcp_server.__file__).resolve() == expected.resolve()


def test_command_root_alias_maps_to_cwd(monkeypatch, tmp_path):
    captured = {}

    class DummyClient:
        def post(self, url, payload, **kwargs):
            if url == "/api/command":
                captured.update(url=url, payload=payload)
            return {"success": True}

    monkeypatch.setattr("local_ai_hub.mcp_server.CLIENT", DummyClient())

    result = _call_tool("local_ai_command", {
        "action": "run", "root": str(tmp_path), "command": "echo 1",
    })

    assert captured.get("url") == "/api/command", repr(result)
    assert captured["payload"]["cwd"] == str(tmp_path)
    assert captured["payload"]["root"] == str(tmp_path)


def test_repo_paths_alias_maps_to_changed_paths(monkeypatch, tmp_path):
    captured = {}

    class DummyClient:
        def post(self, url, payload, **kwargs):
            if url == "/api/context/pack":
                captured.update(url=url, payload=payload)
            return {"success": True, "context": "ok"}

    monkeypatch.setattr("local_ai_hub.mcp_server.CLIENT", DummyClient())

    result = _call_tool("local_ai_repo", {
        "action": "context", "root": str(tmp_path), "query": "find foo.py",
        "paths": ["foo.py"],
        "guarded": True,
    })

    assert captured.get("url") == "/api/context/pack", repr(result)
    assert captured["payload"]["changed_paths"] == ["foo.py"]


def test_repo_canonical_empty_changed_paths_precedes_aliases(monkeypatch, tmp_path):
    captured = {}

    class DummyClient:
        def post(self, url, payload, **kwargs):
            if url == "/api/context/pack":
                captured.update(payload=payload)
            return {"success": True, "context": "ok"}

    monkeypatch.setattr("local_ai_hub.mcp_server.CLIENT", DummyClient())

    _call_tool("local_ai_repo", {
        "action": "context", "root": str(tmp_path),
        "query": "find files",
        "changed_paths": [], "paths": ["alias.py"], "files": ["other.py"],
        "guarded": True,
    })

    assert captured["payload"]["changed_paths"] == []


def test_repo_cwd_files_and_symbol_aliases(monkeypatch, tmp_path):
    captured = {}

    class DummyClient:
        def post(self, url, payload, **kwargs):
            if url == "/api/repo/dependency_slice":
                captured.update(url=url, payload=payload)
            return {"success": True}

    monkeypatch.setattr("local_ai_hub.mcp_server.CLIENT", DummyClient())

    _call_tool("local_ai_repo", {
        "action": "dependency_slice", "cwd": str(tmp_path),
        "files": ["module.py"], "symbol": "Widget.run",
    })

    assert captured["url"] == "/api/repo/dependency_slice"
    assert captured["payload"]["root"] == str(tmp_path)
    assert captured["payload"]["symbol"] == "Widget.run"


def test_command_changed_paths_alias_maps_to_format_paths(monkeypatch, tmp_path):
    captured = {}

    class DummyClient:
        def post(self, url, payload, **kwargs):
            if url == "/api/command":
                captured.update(payload=payload)
            return {"success": True}

    monkeypatch.setattr("local_ai_hub.mcp_server.CLIENT", DummyClient())

    _call_tool("local_ai_command", {
        "action": "format", "cwd": str(tmp_path),
        "command": "fallback.py", "changed_paths": ["selected.py"],
    })

    assert captured["payload"]["paths"] == ["selected.py"]

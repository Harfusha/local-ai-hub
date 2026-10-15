import asyncio

import pytest
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


def test_repo_accepts_canonical_positional_root_and_query(monkeypatch, tmp_path):
    captured = {}

    def capture(action, root, query, *args, **kwargs):
        captured.update(action=action, root=root, query=query)
        return {"success": True}

    monkeypatch.setattr(mcp_server, "_local_ai_repo_impl", capture)

    mcp_server.local_ai_repo("search", str(tmp_path), "needle")

    assert captured == {"action": "search", "root": str(tmp_path), "query": "needle"}


def test_repo_accepts_canonical_positional_diff(monkeypatch, tmp_path):
    captured = {}

    class DummyClient:
        def post(self, url, payload, **kwargs):
            if url == "/api/repo/diagnose":
                captured.update(url=url, payload=payload)
            return {"success": True}

    monkeypatch.setattr(mcp_server, "CLIENT", DummyClient())

    mcp_server.local_ai_repo("diagnose", str(tmp_path), "", "inspect this diff")

    assert captured["url"] == "/api/repo/diagnose"
    assert captured["payload"]["text"] == "inspect this diff"


def test_repo_preserves_late_positional_changed_paths_and_phase(monkeypatch, tmp_path):
    captured = {}

    class DummyClient:
        def post(self, url, payload, **kwargs):
            if url == "/api/context/pack":
                captured.update(url=url, payload=payload)
            return {"success": True, "context": "ok"}

    monkeypatch.setattr(mcp_server, "CLIENT", DummyClient())

    result = mcp_server.local_ai_repo(
        "context", str(tmp_path), "find changes", "", "", "", "", "HEAD",
        False, False, 0, None, "adaptive", "", "auto", "", None, "",
        False, False, None, None, 0, "", "", False, "", "", "", "", "", "",
        ["src/changed.py"], "review", ["src/focus.py"], "", guarded=True,
    )

    assert captured.get("url") == "/api/context/pack", repr(result)
    assert captured["payload"]["changed_paths"] == ["src/changed.py"]
    assert captured["payload"]["phase"] == "review"


def test_command_preserves_legacy_positional_timeout(monkeypatch, tmp_path):
    captured = {}

    class DummyClient:
        def post(self, url, payload, **kwargs):
            captured.update(url=url, payload=payload)
            return {"success": True}

    monkeypatch.setattr(mcp_server, "CLIENT", DummyClient())
    monkeypatch.setattr(mcp_server.FEATURES, "commands", True)
    monkeypatch.setattr(mcp_server, "_client_root", lambda value: value)
    monkeypatch.setattr(mcp_server, "_timeout", lambda _name: 300)

    mcp_server.local_ai_command("run", "pytest -q", str(tmp_path), 27)

    assert captured["url"] == "/api/command"
    assert captured["payload"]["cwd"] == str(tmp_path)
    assert captured["payload"]["timeout"] == 27


@pytest.mark.parametrize("alias,value", [
    ("cwd", "."), ("symbol", "Widget.run"), ("paths", ["module.py"]), ("files", ["module.py"]),
])
def test_repo_registered_wrapper_rejects_aliases_before_client(monkeypatch, alias, value):
    calls = []
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_kwargs: None)

    class DummyClient:
        def post(self, url, payload, **kwargs):
            calls.append((url, payload))
            return {"success": True}

    monkeypatch.setattr("local_ai_hub.mcp_server.CLIENT", DummyClient())
    result = _call_tool("local_ai_repo", {
        "action": "search", "root": ".", "query": "Widget.run", alias: value,
    })

    assert calls == []
    assert "unsupported" in str(result).lower() or "unexpected" in str(result).lower()


@pytest.mark.parametrize("alias,value", [
    ("cwd", "."), ("symbol", "Widget.run"), ("paths", ["module.py"]), ("files", ["module.py"]),
])
def test_repo_direct_python_call_rejects_alias_keyword(alias, value):
    with pytest.raises(TypeError):
        mcp_server.local_ai_repo(action="search", root=".", query="Widget.run", **{alias: value})


def test_repo_schema_excludes_aliases_and_allows_relation_pagination():
    from local_ai_hub.operation_contracts import (
        operation_parameters_schema, operation_tool_input_schema, validate_operation_arguments,
    )

    properties = operation_parameters_schema("local_ai_repo")["properties"]
    assert not {"cwd", "symbol", "paths", "files"} & set(properties)
    input_schema = operation_tool_input_schema("local_ai_repo")
    assert input_schema["additionalProperties"] is False
    for action in ("callers", "callees", "implementations"):
        assert validate_operation_arguments(
            "local_ai_repo", action, {"limit": 2, "offset": 4},
        ) is None
        assert validate_operation_arguments(
            "local_ai_repo", action, {"limit": True, "offset": 0},
        ) is not None


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

@pytest.mark.parametrize("alias", ["changed_paths", "files"])
def test_command_canonical_empty_paths_excludes_alias_files(monkeypatch, tmp_path, alias):
    captured = {}

    class DummyClient:
        def post(self, url, payload, **kwargs):
            if url == "/api/command":
                captured.update(url=url, payload=payload)
            return {"success": True}

    monkeypatch.setattr(mcp_server, "CLIENT", DummyClient())
    assert Path(mcp_server.__file__).resolve().is_relative_to(
        Path(__file__).resolve().parents[2] / "src"
    )
    result = _call_tool("local_ai_command", {
        "action": "format", "cwd": str(tmp_path), "paths": [],
        alias: ["excluded.py"],
    })

    assert captured.get("url") == "/api/command", repr(result)
    assert captured["payload"]["paths"] == []

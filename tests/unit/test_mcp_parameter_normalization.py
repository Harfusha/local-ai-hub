import asyncio

import pytest
from pathlib import Path

from local_ai_hub import mcp_server
from local_ai_hub.mcp_server import mcp


def _call_tool(name, arguments):
    return asyncio.run(mcp.call_tool(name, arguments))


def _use_active_operational_mode(monkeypatch):
    from local_ai_hub.operational_mode import OperationalModeSnapshot

    snapshot = OperationalModeSnapshot("active", 1, None)
    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda _state_dir: snapshot)


def test_mcp_module_comes_from_current_checkout():
    expected = Path(__file__).resolve().parents[2] / "src" / "local_ai_hub" / "mcp_server.py"
    assert Path(mcp_server.__file__).resolve() == expected.resolve()


def test_command_root_does_not_replace_cwd(monkeypatch, tmp_path):
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
    assert captured["payload"]["cwd"] == mcp_server._workspace
    assert captured["payload"]["root"] == str(tmp_path)


def test_repo_accepts_canonical_root_and_query_keywords(monkeypatch, tmp_path):
    captured = {}

    def capture(action, root, query, *args, **kwargs):
        captured.update(action=action, root=root, query=query)
        return {"success": True}

    monkeypatch.setattr(mcp_server, "_local_ai_repo_impl", capture)

    mcp_server.local_ai_repo(action="search", root=str(tmp_path), query="needle")

    assert captured == {"action": "search", "root": str(tmp_path), "query": "needle"}


def test_repo_accepts_canonical_positional_diff(monkeypatch, tmp_path):
    captured = {}

    class DummyClient:
        def post(self, url, payload, **kwargs):
            if url == "/api/repo/diagnose":
                captured.update(url=url, payload=payload)
            return {"success": True}

    monkeypatch.setattr(mcp_server, "CLIENT", DummyClient())

    mcp_server.local_ai_repo(
        action="diagnose", root=str(tmp_path), diff="inspect this diff",
    )

    assert captured["url"] == "/api/repo/diagnose"
    assert captured["payload"]["text"] == "inspect this diff"


def test_repo_forwards_canonical_changed_paths_and_phase(monkeypatch, tmp_path):
    captured = {}

    class DummyClient:
        def post(self, url, payload, **kwargs):
            if url == "/api/context/pack":
                captured.update(url=url, payload=payload)
            return {"success": True, "context": "ok"}

    monkeypatch.setattr(mcp_server, "CLIENT", DummyClient())

    result = mcp_server.local_ai_repo(
        action="context",
        root=str(tmp_path),
        query="find changes",
        changed_paths=["src/changed.py"],
        phase="review",
        focus=["src/focus.py"],
        guarded=True,
    )

    assert captured.get("url") == "/api/context/pack", repr(result)
    assert captured["payload"]["changed_paths"] == ["src/changed.py"]
    assert captured["payload"]["phase"] == "review"


def test_command_accepts_canonical_timeout_keyword(monkeypatch, tmp_path):
    captured = {}

    class DummyClient:
        def post(self, url, payload, **kwargs):
            captured.update(url=url, payload=payload)
            return {"success": True}

    monkeypatch.setattr(mcp_server, "CLIENT", DummyClient())
    monkeypatch.setattr(mcp_server.FEATURES, "commands", True)
    monkeypatch.setattr(mcp_server, "_client_root", lambda value: value)
    monkeypatch.setattr(mcp_server, "_timeout", lambda _name: 300)

    mcp_server.local_ai_command("run", command="pytest -q", cwd=str(tmp_path), timeout=27)

    assert captured["url"] == "/api/command"
    assert captured["payload"]["cwd"] == str(tmp_path)
    assert captured["payload"]["timeout"] == 27


def test_command_rejects_legacy_positional_parameters():
    with pytest.raises(TypeError):
        mcp_server.local_ai_command("run", "pytest -q", ".", 27)


@pytest.mark.parametrize("alias,value", [
    ("cwd", "."), ("symbol", "Widget.run"), ("paths", ["module.py"]), ("files", ["module.py"]),
])
def test_repo_registered_wrapper_rejects_aliases_before_client(monkeypatch, alias, value):
    calls = []
    _use_active_operational_mode(monkeypatch)
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
def test_repo_direct_python_call_rejects_alias_keyword(monkeypatch, alias, value):
    _use_active_operational_mode(monkeypatch)
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


@pytest.mark.parametrize("alias,value", [
    ("changed_paths", ["selected.py"]), ("files", ["selected.py"]), ("input", "legacy stdin"),
])
def test_command_contract_rejects_retired_aliases(alias, value):
    assert validate_operation_arguments("local_ai_command", "format", {alias: value}) is not None


def test_command_format_requires_nonempty_canonical_paths():
    assert validate_operation_arguments(
        "local_ai_command", "format", {"command": "legacy.py"},
    ) is not None
    assert validate_operation_arguments(
        "local_ai_command", "format", {"paths": []},
    ) is not None
    assert validate_operation_arguments(
        "local_ai_command", "format", {"paths": ["selected.py"]},
    ) is None

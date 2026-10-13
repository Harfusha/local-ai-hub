import asyncio
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from local_ai_hub import mcp_server
from local_ai_hub.mcp_server import mcp


def _public_command_schema():
    tools = asyncio.run(mcp.list_tools())
    command = next(tool for tool in tools if tool.name == "local_ai_command")
    return command.inputSchema


def test_mcp_module_comes_from_assigned_checkout():
    expected = Path(__file__).resolve().parents[2] / "src" / "local_ai_hub" / "mcp_server.py"
    assert Path(mcp_server.__file__).resolve() == expected.resolve()


def test_public_command_schema_defines_flaky_runs_contract():
    schema = _public_command_schema()
    runs = schema["properties"]["runs"]

    assert "flaky_detect" in schema["properties"]["action"]["enum"]
    assert runs["type"] == "integer"
    assert runs["minimum"] == 1
    assert runs["default"] == 5

    validator = Draft202012Validator(schema)
    assert validator.is_valid({"action": "flaky_detect", "command": "pytest -q", "runs": 1})
    assert not validator.is_valid({"action": "flaky_detect", "command": "pytest -q", "runs": 0})
    assert not validator.is_valid({"action": "flaky_detect", "command": "pytest -q", "runs": 1.5})


@pytest.mark.parametrize(("arguments", "expected_runs"), [
    ({"action": "flaky_detect", "command": "pytest -q", "runs": 3}, 3),
    ({"action": "flaky_detect", "command": "pytest -q"}, 5),
])
def test_public_flaky_detect_call_forwards_requested_or_default_runs(
    monkeypatch, tmp_path, arguments, expected_runs,
):
    captured = []

    class FakeClient:
        def post(self, url, payload, **kwargs):
            captured.append((url, payload))
            return {"success": True, "runs": payload["runs"]}

    monkeypatch.setattr(mcp_server, "CLIENT", FakeClient())
    monkeypatch.setattr(mcp_server.FEATURES, "commands", True)
    monkeypatch.setattr(mcp_server, "_client_root", lambda value: value)
    monkeypatch.setattr(mcp_server, "_timeout", lambda _name: 300)
    arguments = {**arguments, "cwd": str(tmp_path)}

    asyncio.run(mcp.call_tool("local_ai_command", arguments))

    command_call = next((payload for url, payload in captured if url == "/api/command"), None)
    assert command_call is not None
    assert command_call["action"] == "flaky_detect"
    assert command_call["cwd"] == str(tmp_path)
    assert command_call["runs"] == expected_runs

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from local_ai_hub.token_accounting import json_tokens


@pytest.fixture
def isolated_mcp_server(tmp_path_factory):
    root = tmp_path_factory.mktemp("brief-status-authority")
    state_dir = root / "state"
    config_path = root / "config.toml"
    config_path.write_text(
        "[server]\n"
        'bind = "127.0.0.1"\n'
        "port = 49173\n"
        "auto_start_ollama = false\n"
        f'state_dir = "{state_dir.as_posix()}"\n',
        encoding="utf-8",
    )
    patcher = pytest.MonkeyPatch()
    try:
        server = _import_mcp_server(root, config_path, patcher)
        yield server
    finally:
        patcher.undo()


def _import_mcp_server(root, config_path, patcher):
    patcher.setenv("LOCAL_AI_CONFIG", str(config_path))
    module_name = "local_ai_hub._mcp_server_brief_status_authority"
    source_path = Path(__file__).resolve().parents[2] / "src" / "local_ai_hub" / "mcp_server.py"
    spec = importlib.util.spec_from_file_location(module_name, source_path)
    assert spec is not None and spec.loader is not None
    server = importlib.util.module_from_spec(spec)
    patcher.setitem(sys.modules, module_name, server)
    spec.loader.exec_module(server)
    patcher.setattr(server.FEATURES, "status", True)
    patcher.setattr(server._ACCOUNTING_REPORTER, "record", lambda event: None)
    patcher.setattr(server.CONTEXT_LEDGER, "record", lambda **kwargs: None)
    return server


def _write_test_config(root):
    state_dir = root / "state"
    config_path = root / "config.toml"
    config_path.write_text(
        "[server]\n"
        'bind = "127.0.0.1"\n'
        "port = 49173\n"
        "auto_start_ollama = false\n"
        f'state_dir = "{state_dir.as_posix()}"\n',
        encoding="utf-8",
    )
    return config_path


@pytest.fixture
def existing_canonical_mcp_module(monkeypatch):
    module_name = "local_ai_hub.mcp_server"
    canonical = sys.modules.get(module_name)
    if canonical is None:
        canonical = ModuleType(module_name)
        monkeypatch.setitem(sys.modules, module_name, canonical)
    return module_name, canonical


def test_brief_status_import_coexists_with_existing_canonical_module(
    existing_canonical_mcp_module, isolated_mcp_server, monkeypatch
):
    module_name, canonical = existing_canonical_mcp_module
    server = isolated_mcp_server
    raw = {"success": False, "degraded": True, "hub_online": True}
    monkeypatch.setattr(server.CLIENT, "get", lambda path, **kwargs: dict(raw))
    contents, structured = asyncio.run(
        server.mcp.call_tool(
            "local_ai_status",
            {"detail": "brief", "response_profile": "compact", "max_response_tokens": 1600},
        )
    )
    assert json.loads(contents[0].text)["hub_online"] is True
    assert structured["hub_online"] is True
    assert sys.modules[module_name] is canonical


@pytest.mark.parametrize(
    ("raw", "expected_online"),
    [
        (
            {
                "success": False,
                "degraded": True,
                "hub_online": True,
                "error": "optional metadata unavailable",
                "retryable": False,
                "terminal": True,
            },
            True,
        ),
        ({"success": False, "hub_online": False}, False),
        ({"success": False}, None),
    ],
)
def test_brief_status_preserves_authoritative_online_state_on_wire(
    isolated_mcp_server, monkeypatch, raw, expected_online
):
    server = isolated_mcp_server

    def get(path, **kwargs):
        assert path.startswith(("/api/status", "/api/live/status"))
        return dict(raw)

    monkeypatch.setattr(server.CLIENT, "get", get)
    requested = 1600
    contents, structured = asyncio.run(
        server.mcp.call_tool(
            "local_ai_status",
            {
                "detail": "brief",
                "response_profile": "compact",
                "max_response_tokens": requested,
            },
        )
    )

    actual = json.loads(contents[0].text)
    if expected_online is None:
        assert "hub_online" not in actual
    else:
        assert actual["hub_online"] is expected_online
    assert actual["success"] is raw["success"]
    for key in ("degraded", "error", "retryable", "terminal"):
        if key in raw:
            assert actual[key] == raw[key]

    wire = {
        "content": [{"type": "text", "text": contents[0].text}],
        "structuredContent": structured,
        "isError": False,
    }
    wire_tokens = json_tokens(wire)
    assert wire_tokens <= requested
    assert actual["response_budget"]["returned_tokens"] == wire_tokens
    assert structured["response_budget"]["returned_tokens"] == wire_tokens


def test_brief_status_rejects_unrepresentable_budget_without_false_success(
    isolated_mcp_server, monkeypatch
):
    server = isolated_mcp_server
    raw = {
        "success": False,
        "degraded": True,
        "hub_online": True,
        "error": "metadata unavailable " * 300,
        "retryable": False,
        "terminal": True,
    }
    monkeypatch.setattr(server.CLIENT, "get", lambda path, **kwargs: dict(raw))
    requested = 128
    result = asyncio.run(
        server.mcp.call_tool(
            "local_ai_status",
            {
                "detail": "brief",
                "response_profile": "compact",
                "max_response_tokens": requested,
            },
        )
    )
    if isinstance(result, tuple):
        contents, structured = result
    else:
        contents, structured = result, None

    actual = json.loads(contents[0].text)
    assert actual["success"] is False
    assert isinstance(actual.get("error"), str) and actual["error"]
    budget = actual["response_budget"]
    assert budget["requested_tokens"] == requested

    wire = {"content": [{"type": "text", "text": contents[0].text}]}
    if structured is not None:
        wire["structuredContent"] = structured
        wire["isError"] = False
    wire_tokens = json_tokens(wire)
    assert wire_tokens <= requested
    assert budget["returned_tokens"] == wire_tokens
    if structured is not None:
        assert structured["success"] is False
        assert structured["response_budget"]["returned_tokens"] == wire_tokens

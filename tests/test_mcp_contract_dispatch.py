from __future__ import annotations

import asyncio

import pytest


def test_mcp_client_adapter_keeps_missing_post_monkeypatch_on_adapter(monkeypatch) -> None:
    from local_ai_hub import mcp_server

    class ClientWithoutPost:
        def request(self, path, payload=None, **kwargs):
            return {"path": path, "payload": payload, "kwargs": kwargs}

    client = ClientWithoutPost()
    adapter = mcp_server._MCPHubClientAdapter(client)

    def fake_post(*_args, **_kwargs):
        return {"success": True}

    monkeypatch.setattr(adapter, "post", fake_post, raising=False)

    assert adapter.post is fake_post
    assert not hasattr(client, "post")


def test_mcp_dispatch_rejects_unknown_arguments_before_http_tool_call(monkeypatch) -> None:
    from local_ai_hub import mcp_server

    calls: list[str] = []

    async def fake_call_tool(name, arguments, *, convert_result=False):
        calls.append(name)
        return {"success": True}

    monkeypatch.setattr(mcp_server.mcp._tool_manager, "call_tool", fake_call_tool)

    _content, payload = asyncio.run(
        mcp_server._compact_mcp_call_tool(
            "local_ai_status",
            {"detail": "brief", "unknown_argument": True},
        )
    )

    assert payload["success"] is False
    assert payload["status_code"] == 400
    assert "unknown_argument" in payload["error"]
    assert calls == []


def test_mcp_dispatch_rejects_artifact_list_get_fields_before_tool_call(monkeypatch) -> None:
    from local_ai_hub import mcp_server

    calls: list[str] = []

    async def fake_call_tool(name, arguments, *, convert_result=False):
        calls.append(name)
        return {"success": True}

    monkeypatch.setattr(mcp_server.mcp._tool_manager, "call_tool", fake_call_tool)

    _content, payload = asyncio.run(
        mcp_server._compact_mcp_call_tool(
            "local_ai_artifact",
            {"action": "list", "artifact_id": "artifact-1"},
        )
    )

    assert payload["success"] is False
    assert payload["status_code"] == 400
    assert "artifact_id" in payload["error"]
    assert calls == []


@pytest.mark.parametrize(
    "arguments",
    [
        {"action": "slice", "artifact_id": "artifact-1", "offset": -1},
        {"action": "slice", "artifact_id": "artifact-1", "max_chars": 0},
        {"action": "slice", "artifact_id": "artifact-1", "max_chars": 50001},
    ],
)
def test_mcp_dispatch_rejects_out_of_range_artifact_slice_before_tool_call(
    monkeypatch, arguments
) -> None:
    from local_ai_hub import mcp_server

    calls: list[str] = []

    async def fake_call_tool(name, _arguments, *, convert_result=False):
        calls.append(name)
        return {"success": True}

    monkeypatch.setattr(mcp_server.mcp._tool_manager, "call_tool", fake_call_tool)

    _content, payload = asyncio.run(
        mcp_server._compact_mcp_call_tool("local_ai_artifact", arguments)
    )

    assert payload["success"] is False
    assert payload["status_code"] == 400
    assert calls == []


def test_mcp_dispatch_rejects_invalid_output_envelope(monkeypatch) -> None:
    from local_ai_hub import mcp_server

    async def fake_call_tool(_name, _arguments, *, convert_result=False):
        return {"success": "yes"}

    monkeypatch.setattr(mcp_server.mcp._tool_manager, "call_tool", fake_call_tool)
    monkeypatch.setattr(mcp_server.mcp._tool_manager, "get_tool", lambda _name: None)
    monkeypatch.setattr(mcp_server, "_ALL_REGISTERED_TOOLS", {})

    _content, payload = asyncio.run(
        mcp_server._compact_mcp_call_tool(
            "local_ai_status",
            {"detail": "brief"},
        )
    )

    assert payload["success"] is False
    assert payload["status_code"] == 500
    assert "output contract" in payload["error"]


def test_mcp_dispatch_rejects_invalid_artifact_list_item_shape(monkeypatch) -> None:
    from local_ai_hub import mcp_server

    async def fake_call_tool(_name, _arguments, *, convert_result=False):
        return {"success": True, "artifacts": [{"artifact_id": "artifact-1"}]}

    monkeypatch.setattr(mcp_server.mcp._tool_manager, "call_tool", fake_call_tool)
    monkeypatch.setattr(mcp_server.mcp._tool_manager, "get_tool", lambda _name: None)
    monkeypatch.setattr(mcp_server, "_ALL_REGISTERED_TOOLS", {})

    _content, payload = asyncio.run(
        mcp_server._compact_mcp_call_tool(
            "local_ai_artifact", {"action": "list"}
        )
    )

    assert payload["success"] is False
    assert payload["status_code"] == 500
    assert "output contract" in payload["error"]


def test_live_mcp_schema_publishes_action_conditions_and_output_schema() -> None:
    from local_ai_hub import mcp_server

    registered = mcp_server.mcp._tool_manager._tools["local_ai_artifact"]
    input_schema = registered.parameters
    output_schema = registered.output_schema

    assert "allOf" in input_schema
    assert any(
        branch.get("then", {}).get("required") == ["action", "artifact_id"]
        for branch in input_schema["allOf"]
    )
    assert output_schema["type"] == "object"
    assert output_schema["additionalProperties"] is True
    assert "anyOf" not in output_schema
    assert output_schema["properties"]["success"]["type"] == "boolean"
    assert output_schema["properties"]["status"]["type"] == "string"


def test_live_mcp_schemas_match_registry_for_every_public_tool() -> None:
    from local_ai_hub import mcp_server
    from local_ai_hub.operation_contracts import (
        operation_tool_input_schema,
        operation_tool_output_schema,
    )

    registered = mcp_server.mcp._tool_manager._tools
    wire_tools = {tool.name: tool for tool in asyncio.run(mcp_server.mcp.list_tools())}
    enabled_tools = set(mcp_server.FEATURES.enabled_tools)
    assert set(wire_tools) == enabled_tools

    for name in enabled_tools:
        expected_input = operation_tool_input_schema(name, mcp_server.FEATURES)
        if name == "local_ai_task":
            expected_input["properties"]["request_id"] = {
                "type": "string", "default": "",
                "description": "Stable async-job idempotency key and request correlation ID.",
            }
            non_async_actions = sorted(set(mcp_server.operation_actions(name, mcp_server.FEATURES)) - {"submit", "status", "wait", "result", "cancel"})
            expected_input.setdefault("allOf", []).append({
                "if": {"properties": {"action": {"enum": non_async_actions}}, "required": ["action"]},
                "then": {"not": {"required": ["request_id"]}},
            })
        expected_output = operation_tool_output_schema(name, mcp_server.FEATURES)
        assert registered[name].parameters == expected_input, name
        assert wire_tools[name].inputSchema == expected_input, name
        assert registered[name].output_schema == expected_output, name
        assert wire_tools[name].outputSchema == expected_output, name
def test_mcp_solve_is_gated_as_heavy_and_repo_map_read_stays_lightweight(monkeypatch) -> None:
    from local_ai_hub import mcp_server

    gate_calls = []
    client_calls = []

    def gate(snapshot, action, *, requires_heavy_work=True):
        gate_calls.append((action, requires_heavy_work))
        if requires_heavy_work:
            return {
                "success": False,
                "error_code": "operational_mode_blocked",
                "action": action,
                "terminal": True,
                "retryable": False,
            }
        return None

    def post(path, payload, *, timeout):
        client_calls.append(path)
        return {"success": True, "tree": {}, "files": []}

    monkeypatch.setattr(
        mcp_server,
        "load_operational_mode",
        lambda *_args, **_kwargs: mcp_server.OperationalModeSnapshot("gaming", 0, None),
    )
    monkeypatch.setattr(mcp_server, "operational_mode_gate_error", gate)
    monkeypatch.setattr(mcp_server.FEATURES, "commands", True)
    monkeypatch.setattr(mcp_server.FEATURES, "repo", True)
    monkeypatch.setattr(mcp_server.CLIENT, "post", post)
    # This test covers action gating and dispatch; isolate background accounting.
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "_send", lambda *_args, **_kwargs: None)

    command_result = mcp_server.local_ai_repo(
        action="solve", task="bounded task", root="C:/repo"
    )

    assert gate_calls == [("solve", True)]
    assert command_result["error_code"] == "operational_mode_blocked"
    assert client_calls == []

    read_result = mcp_server.local_ai_repo(action="map", root="C:/repo")

    assert gate_calls == [("solve", True), ("map", False)]
    assert read_result.get("error_code") != "operational_mode_blocked"
    assert client_calls == ["/api/repo/map"]


def test_instrumented_mcp_action_reaches_inprocess_client_with_classified_metadata(monkeypatch) -> None:
    from local_ai_hub import mcp_server

    calls = []

    class FakeHubClient:
        def request(
            self,
            path,
            payload=None,
            *,
            timeout=30.0,
            replay_safe=False,
            request_id=None,
            operational_action=None,
            requires_heavy_work=True,
        ):
            calls.append((
                path,
                operational_action,
                requires_heavy_work,
            ))
            return {"success": True, "items": []}

        def post(self, path, payload=None, *, timeout=30.0):
            return self.request(path, payload, timeout=timeout)

    monkeypatch.setattr(mcp_server, "CLIENT", mcp_server._MCPHubClientAdapter(FakeHubClient()))
    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda *_a, **_k: mcp_server.OperationalModeSnapshot("active", 0, None))
    monkeypatch.setattr(mcp_server, "operational_mode_gate_error", lambda *_a, **_k: None)
    monkeypatch.setattr(mcp_server, "_record_adoption", lambda *_a, **_k: None)
    monkeypatch.setattr(mcp_server, "_tool_catalog_schema_tokens", lambda: 0)
    monkeypatch.setattr(mcp_server, "finalize_tool_accounting", lambda **_k: {})
    monkeypatch.setattr(mcp_server.CONTEXT_LEDGER, "record", lambda **_k: None)
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda *_a: None)
    monkeypatch.setattr(mcp_server, "semantic_handoff_hint", lambda *_a: None)

    def local_ai_repo(action: str, root: str):
        return mcp_server.CLIENT.post("/api/search", {"action": action, "root": root})

    dispatch = mcp_server._instrumented_tool()(local_ai_repo)
    dispatch(action="map", root="C:/repo")
    dispatch(action="search", root="C:/repo")

    assert calls == [
        ("/api/search", "map", False),
        ("/api/search", "search", False),
    ]

def test_mcp_client_adapter_forwards_semantic_metadata_to_hub_client_request() -> None:
    from local_ai_hub import mcp_server

    calls = []

    class FakeHubClient:
        def request(
            self,
            path,
            payload=None,
            *,
            timeout=30.0,
            replay_safe=False,
            request_id=None,
            operational_action=None,
            requires_heavy_work=True,
        ):
            calls.append((path, payload, {
                "timeout": timeout,
                "replay_safe": replay_safe,
                "request_id": request_id,
                "operational_action": operational_action,
                "requires_heavy_work": requires_heavy_work,
            }))
            return {"success": True}

        def post(self, path, payload=None, *, timeout=30.0):
            return self.request(path, payload, timeout=timeout)

        def get(
            self,
            path,
            *,
            timeout=15.0,
            operational_action=None,
            requires_heavy_work=True,
        ):
            return self.request(
                path,
                None,
                timeout=timeout,
                operational_action=operational_action,
                requires_heavy_work=requires_heavy_work,
            )

    client = mcp_server._MCPHubClientAdapter(FakeHubClient())
    token = mcp_server._CURRENT_OPERATIONAL_CONTEXT.set(("map", False))
    try:
        result = client.post("/api/repo/map", {"root": "C:/repo"}, timeout=2.0)
        status = client.get("/api/live/status", timeout=1.0)
    finally:
        mcp_server._CURRENT_OPERATIONAL_CONTEXT.reset(token)

    assert result == {"success": True}
    assert status == {"success": True}
    assert calls == [
        (
            "/api/repo/map",
            {"root": "C:/repo"},
            {
                "timeout": 2.0,
                "replay_safe": False,
                "request_id": None,
                "operational_action": "map",
                "requires_heavy_work": False,
            },
        ),
        (
            "/api/live/status",
            None,
            {
                "timeout": 1.0,
                "replay_safe": False,
                "request_id": None,
                "operational_action": "map",
                "requires_heavy_work": False,
            },
        ),
    ]

def test_mcp_transport_metadata_keeps_deterministic_reads_light() -> None:
    from local_ai_hub.mcp_server import _classify_mcp_operation

    assert _classify_mcp_operation("local_ai_repo", {"action": "map"}) == ("map", False)
    assert _classify_mcp_operation("local_ai_repo", {"action": "code_index"}) == ("code_index", False)
    assert _classify_mcp_operation("local_ai_artifact", {"action": "slice"}) == ("slice", False)
    assert _classify_mcp_operation("local_ai_status", {"detail": "brief"}) == ("brief", False)
    assert _classify_mcp_operation("local_ai_status", {}) == ("brief", False)
    assert _classify_mcp_operation("local_ai_repo", {"action": "search"}) == ("search", False)

def test_mcp_client_forwards_config_and_keeps_autostart_lazy(monkeypatch) -> None:
    from local_ai_hub import mcp_server

    calls = {}

    class FakeHubClient:
        def __init__(self, *, config_path, auto_start):
            self.requests = []
            calls.update(
                config_path=config_path,
                auto_start=auto_start,
                requests=self.requests,
            )

        def request(self, path, payload=None):
            self.requests.append((path, payload))
            return {"success": True}

    monkeypatch.setattr(mcp_server, "HubClient", FakeHubClient)

    client = mcp_server._build_mcp_client("C:/config/hub.toml")

    assert isinstance(client._client, FakeHubClient)
    assert calls == {
        "config_path": "C:/config/hub.toml",
        "auto_start": True,
        "requests": [],
    }


def test_protocol_accounting_uses_shared_mcp_client_as_light_telemetry(monkeypatch) -> None:
    from local_ai_hub import mcp_server

    calls = []

    class SharedMCPClient:
        def post(self, path, payload, *, timeout):
            calls.append((
                path,
                payload,
                timeout,
                mcp_server._CURRENT_OPERATIONAL_CONTEXT.get(),
            ))
            return {"success": True}

    def forbidden_client(*_args, **_kwargs):
        raise AssertionError("accounting must reuse MCP client, not create HTTP client")

    monkeypatch.setattr(mcp_server, "CLIENT", SharedMCPClient())
    monkeypatch.setattr(mcp_server, "HubClient", forbidden_client)
    events = [{"tool": "local_ai_repo", "operation": "map", "request_tokens": 4}]

    mcp_server._ProtocolAccountingReporter()._send(events)

    assert len(calls) == 1
    path, payload, timeout, policy = calls[0]
    assert path == "/api/telemetry/tool-accounting"
    assert payload["events"] == events
    assert payload["batch_id"]
    assert timeout == 0.25
    assert policy == ("telemetry", False)



def test_stdio_tools_list_matches_registered_output_contracts(tmp_path) -> None:
    import sys
    from pathlib import Path

    from local_ai_hub import mcp_server
    from local_ai_hub.operation_contracts import (
        OPERATION_CONTRACTS,
        operation_tool_input_schema,
        operation_tool_output_schema,
    )
    from mcp_stdio_catalog_support import explicit_catalog_environment, stdio_catalog

    root = Path(__file__).resolve().parents[1]
    env, features = explicit_catalog_environment(tmp_path, root=root)
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "root-schema-test", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]
    initialized, listed = stdio_catalog(
        [
            sys.executable,
            "-B",
            "-c",
            "from local_ai_hub import mcp_server; "
            "mcp_server.CLIENT.ensure_server = lambda **_kwargs: True; "
            "mcp_server.main()",
        ],
        cwd=root,
        env=env,
        initialize_params=messages[0]["params"],
        timeout=15,
    )

    assert initialized["protocolVersion"] == "2025-06-18"
    wire_tools = {tool["name"]: tool for tool in listed["tools"]}
    expected_names = set(features.enabled_tools)
    assert set(wire_tools) == expected_names
    assert expected_names == set(OPERATION_CONTRACTS)

    from unittest.mock import patch

    with patch.object(mcp_server, "FEATURES", features):
        for name in expected_names:
            expected_input = operation_tool_input_schema(name, features)
            if name == "local_ai_task":
                expected_input["properties"]["request_id"] = {
                    "type": "string", "default": "",
                    "description": "Stable async-job idempotency key and request correlation ID.",
                }
                non_async_actions = sorted(set(mcp_server.operation_actions(name, features)) - {"submit", "status", "wait", "result", "cancel"})
                expected_input.setdefault("allOf", []).append({
                    "if": {"properties": {"action": {"enum": non_async_actions}}, "required": ["action"]},
                    "then": {"not": {"required": ["request_id"]}},
                })
            assert wire_tools[name]["inputSchema"] == expected_input, name
            assert wire_tools[name]["outputSchema"] == operation_tool_output_schema(name, features), name
    if "local_ai_rag" in wire_tools:
        search_schema = wire_tools["local_ai_rag"]["outputSchema"]["x-action-output-contracts"]["search"]
        result_item = search_schema["results"]["items"]
        assert result_item["properties"]["chunk_no"] == {"type": "integer"}


def test_stdio_tools_list_hides_feature_disabled_tools(tmp_path) -> None:
    import os
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    config = tmp_path / "disabled-features.toml"
    config.write_text("[features]\nrag = false\ncommands = false\n", encoding="utf-8")
    env = os.environ.copy()
    env["LOCAL_AI_CONFIG"] = str(config)
    env["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(root / "src"), env.get("PYTHONPATH", "")) if value
    )
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "disabled-schema-test", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]
    from mcp_stdio_catalog_support import stdio_catalog

    initialized, listed = stdio_catalog(
        [
            sys.executable,
            "-B",
            "-c",
            "from local_ai_hub import mcp_server; "
            "mcp_server.CLIENT.ensure_server = lambda **_kwargs: True; "
            "mcp_server.main()",
        ],
        cwd=root,
        env=env,
        initialize_params=messages[0]["params"],
        timeout=15,
    )

    assert initialized["protocolVersion"] == "2025-06-18"
    wire_tools = {tool["name"]: tool for tool in listed["tools"]}
    assert "local_ai_rag" not in wire_tools
    assert "local_ai_command" not in wire_tools
    assert all(tool.get("outputSchema") for tool in wire_tools.values())


def test_mcp_repo_search_passes_path_hints_to_client_keyword(monkeypatch) -> None:
    from local_ai_hub import mcp_server

    calls = []
    hints = [{"path": "src/local_ai_hub", "purpose": "repository_search", "scope": "repo_search"}]
    expected_hints = [
        {"path": "src/target.py", "purpose": "repository_search", "scope": "repo_search"},
        *hints,
    ]

    class CapturingClient:
        def post(self, path, payload=None, *, timeout=30.0, path_hints=None):
            calls.append((path, payload, path_hints))
            return {"success": True, "results": []}

    monkeypatch.setattr(mcp_server, "CLIENT", CapturingClient())
    monkeypatch.setattr(mcp_server, "_client_root", lambda root: root)

    result = mcp_server.local_ai_repo(
        action="search", root="C:/repo", query="auth", path="src/target.py", path_hints=hints
    )

    assert result["success"] is True
    search_calls = [call for call in calls if call[0] == "/api/search"]
    assert search_calls == [
        (
            "/api/search",
            {
                "root": "C:/repo",
                "query": "auth",
                "top_k": 12,
                "enrich": False,
                "limit": 24,
                "offset": 0,
            },
            expected_hints,
        )
    ]

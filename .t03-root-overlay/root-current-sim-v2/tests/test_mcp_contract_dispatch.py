from __future__ import annotations

import asyncio

import pytest

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
            {"action": "brief", "unknown_argument": True},
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
        {"action": "slice", "artifact_id": "artifact-1", "max_chars": 511},
        {"action": "slice", "artifact_id": "artifact-1", "max_chars": 12001},
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

    _content, payload = asyncio.run(
        mcp_server._compact_mcp_call_tool(
            "local_ai_status",
            {"action": "brief"},
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
    from local_ai_hub.operation_contracts import OPERATION_CONTRACTS, operation_tool_output_schema

    registered = mcp_server.mcp._tool_manager._tools
    wire_tools = {tool.name: tool for tool in asyncio.run(mcp_server.mcp.list_tools())}
    assert set(wire_tools) == set(OPERATION_CONTRACTS)

    for name in OPERATION_CONTRACTS:
        expected_input = mcp_server._mcp_input_schema(name, mcp_server.FEATURES)
        expected_output = operation_tool_output_schema(name, mcp_server.FEATURES)
        assert registered[name].parameters == expected_input, name
        assert wire_tools[name].inputSchema == expected_input, name
        assert registered[name].output_schema == expected_output, name
        assert wire_tools[name].outputSchema == expected_output, name

def test_mcp_action_alias_schema_and_dispatch_use_canonical_contract(monkeypatch) -> None:
    from local_ai_hub import mcp_server

    schema = mcp_server._mcp_input_schema("local_ai_coord", mcp_server.FEATURES)
    action_schema = schema["properties"]["action"]
    assert "task_new" in action_schema["enum"]
    assert "task_new" in mcp_server.CoordAction.__args__
    canonical = next(
        branch for branch in schema["allOf"]
        if branch.get("if", {}).get("properties", {}).get("action", {}).get("const") == "task_create"
    )
    alias = next(
        branch for branch in schema["allOf"]
        if branch.get("if", {}).get("properties", {}).get("action", {}).get("const") == "task_new"
    )
    assert alias["then"] == canonical["then"]

    validated: list[dict[str, object]] = []
    dispatched: list[dict[str, object]] = []
    output_actions: list[str] = []

    def validate_call(_name, arguments, *, features):
        validated.append(arguments)
        return None

    def validate_output(_name, action, _result):
        output_actions.append(action)
        return None

    async def fake_call_tool(_name, arguments, *, convert_result=False):
        dispatched.append(arguments)
        return {"success": True}

    monkeypatch.setattr(mcp_server, "validate_operation_call", validate_call)
    monkeypatch.setattr(mcp_server, "validate_operation_output", validate_output)
    monkeypatch.setattr(mcp_server.mcp._tool_manager, "call_tool", fake_call_tool)
    _content, payload = asyncio.run(mcp_server._compact_mcp_call_tool(
        "local_ai_coord", {"action": "task_new", "task": "alias contract"}
    ))

    assert payload["success"] is True
    assert validated[0]["action"] == "task_create"
    assert dispatched[0]["action"] == "task_new"
    assert output_actions == ["task_create"]

def test_mcp_command_run_is_gated_as_heavy_and_repo_map_read_stays_lightweight(monkeypatch) -> None:
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

    command_result = mcp_server.local_ai_command(
        action="run", command="python -m pytest -q", cwd="."
    )

    assert gate_calls == [("run", True)]
    assert command_result["error_code"] == "operational_mode_blocked"
    assert client_calls == []

    read_result = mcp_server.local_ai_repo(action="map", root="C:/repo")

    assert gate_calls == [("run", True), ("map", False)]
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
        ("/api/search", "search", True),
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
    assert _classify_mcp_operation("local_ai_status", {"detail": "agent_state"}) == ("agent_state", True)
    assert _classify_mcp_operation("local_ai_command", {"action": "run"}) == ("run", True)
    assert _classify_mcp_operation("local_ai_repo", {"action": "search"}) == ("search", True)

def test_mcp_transport_selection_injects_lazy_transport_with_same_config_and_tenant(monkeypatch) -> None:
    from local_ai_hub import mcp_server

    calls = {}

    class FakeTransport:
        def __init__(self, *, config_path):
            calls["transport_config"] = config_path

    class FakeHubClient:
        def __init__(self, *, tenant, config_path, inprocess_transport):
            self.inprocess_transport = inprocess_transport
            calls.update(
                tenant=tenant,
                client_config=config_path,
                transport=inprocess_transport,
            )

    monkeypatch.setattr(mcp_server, "InProcessTransport", FakeTransport, raising=False)
    monkeypatch.setattr(mcp_server, "HubClient", FakeHubClient)

    client = mcp_server._build_mcp_client("agent:workspace", "C:/config/hub.toml")

    assert isinstance(client._client, FakeHubClient)
    assert calls == {
        "tenant": "agent:workspace",
        "client_config": "C:/config/hub.toml",
        "transport_config": "C:/config/hub.toml",
        "transport": client._client.inprocess_transport,
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

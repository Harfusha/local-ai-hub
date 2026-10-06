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
    assert output_schema["anyOf"]
    assert all(
        branch["properties"]["success"]["type"] == "boolean"
        for branch in output_schema["anyOf"]
    )


def test_status_adoption_contract_allows_valid_bypass_and_dispatches_fields(monkeypatch) -> None:
    from local_ai_hub import mcp_server

    captured: dict[str, object] = {}

    async def fake_call_tool(name, arguments, *, convert_result=False):
        captured.update(name=name, arguments=arguments)
        return {
            "success": True,
            "version": None,
            "ollama_online": None,
            "active_model": None,
            "queued": 0,
            "inflight": 0,
            "net_cloud_token_delta_est": 0,
            "cache_hits": 0,
            "coalesced_waiters": 0,
        }

    monkeypatch.setattr(mcp_server.mcp._tool_manager, "call_tool", fake_call_tool)
    status_tool = next(
        tool for tool in asyncio.run(mcp_server.mcp.list_tools())
        if tool.name == "local_ai_status"
    )
    status_properties = status_tool.inputSchema["properties"]
    assert status_properties["adoption_signal"]["enum"] == ["", "bypassed"]
    assert status_properties["target_tool"]["enum"]
    assert any(
        row.get("if", {}).get("properties", {}).get("adoption_signal", {}).get("const") == "bypassed"
        and row.get("then", {}).get("required") == ["target_tool", "target_action"]
        for row in status_tool.inputSchema["allOf"]
    )
    arguments = {
        "detail": "brief",
        "adoption_signal": "bypassed",
        "target_tool": "local_ai_repo",
        "target_action": "search",
    }

    _content, payload = asyncio.run(
        mcp_server._compact_mcp_call_tool("local_ai_status", arguments)
    )

    assert payload["success"] is True
    assert captured == {"name": "local_ai_status", "arguments": arguments}


@pytest.mark.parametrize(
    "arguments",
    [
        {"detail": "brief", "adoption_signal": "bypassed", "target_action": "search"},
        {"detail": "brief", "adoption_signal": "bypassed", "target_tool": "local_ai_repo"},
        {"detail": "brief", "target_tool": "local_ai_repo", "target_action": "search"},
        {
            "detail": "brief",
            "adoption_signal": "bypassed",
            "target_tool": "local_ai_repo",
            "target_action": "not_an_action",
        },
    ],
)
def test_invalid_status_adoption_pair_is_rejected_before_dispatch(monkeypatch, arguments) -> None:
    from local_ai_hub import mcp_server

    async def fail_if_dispatched(*_args, **_kwargs):
        pytest.fail("invalid adoption metadata must be rejected before tool dispatch")

    monkeypatch.setattr(mcp_server.mcp._tool_manager, "call_tool", fail_if_dispatched)
    _content, payload = asyncio.run(
        mcp_server._compact_mcp_call_tool("local_ai_status", arguments)
    )

    assert payload["success"] is False
    assert payload["status_code"] == 400
    assert payload["terminal"] is True
    assert payload["retryable"] is False


def test_mcp_validation_and_disabled_tool_errors_keep_http_status_parity(monkeypatch) -> None:
    from types import SimpleNamespace
    from local_ai_hub import mcp_server
    from local_ai_hub.operation_contracts import validate_operation_call

    disabled_features = SimpleNamespace(repo=False)
    monkeypatch.setattr(mcp_server, "FEATURES", disabled_features)
    calls = []

    async def fake_call_tool(name, arguments, *, convert_result=False):
        calls.append(name)
        return {"success": True}

    monkeypatch.setattr(mcp_server.mcp._tool_manager, "call_tool", fake_call_tool)
    disabled = validate_operation_call("local_ai_repo", {"action": "search"}, features=disabled_features)
    _content, payload = asyncio.run(
        mcp_server._compact_mcp_call_tool("local_ai_repo", {"action": "search"})
    )

    assert disabled is not None and disabled[0] == payload["status_code"] == 403
    assert payload["terminal"] is True and payload["retryable"] is False
    assert calls == []


def test_mcp_unexpected_dispatch_failure_is_bounded_http_500_shape(monkeypatch) -> None:
    from local_ai_hub import mcp_server

    async def fail_dispatch(*_args, **_kwargs):
        raise RuntimeError("backend exploded\nprivate detail")

    monkeypatch.setattr(mcp_server.mcp._tool_manager, "call_tool", fail_dispatch)
    _content, payload = asyncio.run(
        mcp_server._compact_mcp_call_tool("local_ai_status", {"detail": "brief"})
    )

    assert payload == {
        "success": False,
        "status_code": 500,
        "terminal": True,
        "retryable": False,
        "error": "MCP tool failed: backend exploded",
    }


def test_http_mcp_invalid_work_continue_error_semantics_match(tmp_path, monkeypatch) -> None:
    import json
    import threading
    import urllib.error
    import urllib.request
    from types import SimpleNamespace

    from local_ai_hub.app import LocalAIApp
    from local_ai_hub import http_server, mcp_server

    state_dir = tmp_path / "state"
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join([
            '[server]',
            'bind = "127.0.0.1"',
            'port = 11498',
            f'state_dir = "{state_dir.as_posix()}"',
        ]),
        encoding="utf-8",
    )
    app = LocalAIApp(str(config_path))
    previous_app = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(mcp_server, "FEATURES", SimpleNamespace(work_orchestrator=True))

    async def fail_if_dispatched(*_args, **_kwargs):
        pytest.fail("MCP must reject the same missing answer before tool dispatch")

    monkeypatch.setattr(mcp_server.mcp._tool_manager, "call_tool", fail_if_dispatched)
    try:
        request_body = {"action": "continue", "work_id": "work-1"}
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/work-orders",
            data=json.dumps(request_body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-LocalAI-Tenant": "tenant-a",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request) as response:
                http_status = response.status
                http_payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            http_status = error.code
            http_payload = json.loads(error.read().decode("utf-8"))

        _content, mcp_payload = asyncio.run(
            mcp_server._compact_mcp_call_tool("local_ai_work", request_body)
        )

        assert http_status == mcp_payload["status_code"] == 400, (
            f"HTTP returned {http_status} {http_payload!r}; MCP returned {mcp_payload!r}"
        )
        for field, expected in (("success", False), ("terminal", True), ("retryable", False)):
            assert http_payload[field] == mcp_payload[field] == expected
        assert http_payload["error"] == "answer is required"
        assert mcp_payload["error"] == "answer is required for action='continue'"
        assert mcp_payload["error"].startswith(http_payload["error"])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        http_server.APP = previous_app
        app.close()


def test_live_output_schemas_expose_action_specific_variants() -> None:
    from local_ai_hub import mcp_server
    from local_ai_hub.operation_contracts import operation_actions

    tools = mcp_server.mcp._tool_manager._tools
    catalog = asyncio.run(mcp_server.mcp.list_tools())
    for name in (
        "local_ai_repo", "local_ai_task", "local_ai_rag",
        "local_ai_command", "local_ai_coord", "local_ai_work",
    ):
        output_schema = tools[name].output_schema
        wire_tool = next(tool for tool in catalog if tool.name == name)
        assert output_schema["anyOf"]
        assert {
            branch["x-operation-action"] for branch in output_schema["anyOf"]
        } == set(operation_actions(name, mcp_server.FEATURES))
        assert {
            branch["x-operation-action"] for branch in wire_tool.outputSchema["anyOf"]
        } == set(operation_actions(name, mcp_server.FEATURES))


def test_live_mcp_schemas_match_registry_for_every_public_tool() -> None:
    from local_ai_hub import mcp_server
    from local_ai_hub.operation_contracts import (
        OPERATION_CONTRACTS,
        operation_tool_input_schema,
        operation_tool_output_schema,
    )

    registered = mcp_server.mcp._tool_manager._tools
    wire_tools = {tool.name: tool for tool in asyncio.run(mcp_server.mcp.list_tools())}
    assert set(wire_tools) == set(OPERATION_CONTRACTS)

    for name in OPERATION_CONTRACTS:
        expected_input = operation_tool_input_schema(name, mcp_server.FEATURES)
        expected_output = operation_tool_output_schema(name, mcp_server.FEATURES)
        assert registered[name].parameters == expected_input, name
        assert wire_tools[name].inputSchema == expected_input, name
        assert registered[name].output_schema == expected_output, name
        assert wire_tools[name].outputSchema == expected_output, name


def test_live_output_schema_has_closed_branch_for_every_enabled_action() -> None:
    from local_ai_hub import mcp_server
    from local_ai_hub.operation_contracts import OPERATION_CONTRACTS, operation_actions

    registered = mcp_server.mcp._tool_manager._tools
    wire_tools = {tool.name: tool for tool in asyncio.run(mcp_server.mcp.list_tools())}
    for name in OPERATION_CONTRACTS:
        actions = operation_actions(name, mcp_server.FEATURES)
        for schema in (registered[name].output_schema, wire_tools[name].outputSchema):
            branches = schema.get("anyOf", [schema])
            assert len(branches) == len(actions), name
            assert {branch.get("x-operation-action") for branch in branches} == set(actions), name
            assert all(branch.get("additionalProperties") is False for branch in branches), name
        map_schema = next(
            branch for branch in registered["local_ai_repo"].output_schema["anyOf"]
            if branch["x-operation-action"] == "map"
        )
        assert {"tree", "files"} <= set(map_schema["properties"])
        assert not {"text", "receipt_id", "edits"} & set(map_schema["properties"])


def test_mcp_dispatch_rejects_action_forbidden_output_fields(monkeypatch) -> None:
    from local_ai_hub import mcp_server

    async def fake_call_tool(_name, _arguments, *, convert_result=False):
        return {"success": True, "tree": {}, "files": [], "text": "forbidden for map"}

    monkeypatch.setattr(mcp_server.mcp._tool_manager, "call_tool", fake_call_tool)

    _content, payload = asyncio.run(
        mcp_server._compact_mcp_call_tool("local_ai_repo", {"action": "map"})
    )

    assert payload["success"] is False
    assert payload["status_code"] == 500
    assert "text" in payload["error"]
    assert "output contract" in payload["error"]


def test_output_schema_omits_disabled_actions_and_their_payload_fields() -> None:
    from local_ai_hub.features import FeatureSet
    from local_ai_hub.operation_contracts import operation_actions, operation_tool_output_schema

    features = FeatureSet({"features": {"repo": True, "batch_replacement": False}})
    actions = operation_actions("local_ai_repo", features)
    schema = operation_tool_output_schema("local_ai_repo", features)

    assert "batch_replace" not in actions
    assert {branch["x-operation-action"] for branch in schema["anyOf"]} == set(actions)
    assert all("edits" not in branch["properties"] for branch in schema["anyOf"])


def test_enabled_batch_replacement_schema_publishes_edit_arguments() -> None:
    from local_ai_hub.features import FeatureSet
    from local_ai_hub.operation_contracts import operation_tool_input_schema

    features = FeatureSet({"features": {"repo": True, "batch_replacement": True}})
    schema = operation_tool_input_schema("local_ai_repo", features)

    assert "batch_replace" in schema["properties"]["action"]["enum"]
    assert "edits" in schema["properties"]
    assert "dry_run" in schema["properties"]


def test_mcp_transport_selection_uses_http_autostart_with_same_config_and_tenant(monkeypatch) -> None:
    from local_ai_hub import mcp_server

    calls = {}

    class FakeHubClient:
        def __init__(self, *, tenant, config_path, auto_start):
            calls.update(
                tenant=tenant,
                client_config=config_path,
                auto_start=auto_start,
            )

    monkeypatch.setattr(mcp_server, "HubClient", FakeHubClient)

    client = mcp_server._build_mcp_client("agent:workspace", "C:/config/hub.toml")

    assert isinstance(client._client, FakeHubClient)
    assert calls == {
        "tenant": "agent:workspace",
        "client_config": "C:/config/hub.toml",
        "auto_start": True,
    }


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
    monkeypatch.setattr(mcp_server, "_operational_mode_rejection", lambda *_a, **_k: None)
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
            },
            expected_hints,
        )
    ]


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

def test_instrumented_tools_classify_heavy_command_and_lightweight_repo_reads(monkeypatch) -> None:
    from local_ai_hub import mcp_server

    gate_calls = []
    client_calls = []

    def gate(action, *, requires_heavy_work=True):
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
        client_calls.append((path, payload, timeout))
        return {"success": True, "items": []}

    monkeypatch.setattr(mcp_server, "_operational_mode_rejection", gate, raising=False)
    monkeypatch.setattr(
        mcp_server,
        "load_operational_mode",
        lambda *_args, **_kwargs: mcp_server.OperationalModeSnapshot("active", 0, None),
    )
    monkeypatch.setattr(mcp_server, "operational_mode_gate_error", lambda _snapshot: None)
    monkeypatch.setattr(mcp_server.FEATURES, "commands", True)
    monkeypatch.setattr(mcp_server.FEATURES, "repo", True)
    monkeypatch.setattr(mcp_server.CLIENT, "post", post)

    blocked_command = mcp_server.local_ai_command(
        action="run", command="python -m pytest -q", cwd="."
    )

    assert gate_calls == [("run", True)]
    assert blocked_command["error_code"] == "operational_mode_blocked"
    assert client_calls == []

    lightweight_read = mcp_server.local_ai_repo(action="map", root="C:/repo")

    assert gate_calls == [("run", True), ("map", False)]
    assert lightweight_read.get("error_code") != "operational_mode_blocked"
    repo_map_calls = [call for call in client_calls if call[0] == "/api/repo/map"]
    assert len(repo_map_calls) == 1
    assert all(path != "/api/command" for path, _payload, _timeout in client_calls)


def test_shared_daemon_mcp_clients_keep_tenant_root_task_isolated() -> None:
    import json
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from local_ai_hub.client import HubClient
    from local_ai_hub.mcp_server import _MCPHubClientAdapter

    captured = []
    lock = threading.Lock()
    both_requests = threading.Barrier(2)

    def pooled_open(method, path, body, headers, _timeout, **_kwargs):
        with lock:
            captured.append((
                method,
                path,
                headers["X-LocalAI-Tenant"],
                json.loads(body),
            ))
        both_requests.wait(timeout=2)
        return b'{"success":true}'

    clients = []
    for tenant in ("tenant-a", "tenant-b"):
        client = HubClient(tenant=tenant, auto_start=False)
        client._pooled_open = pooled_open
        clients.append(_MCPHubClientAdapter(client))

    requests = [
        ("C:/tenant-a/work", "task-a"),
        ("C:/tenant-b/work", "task-b"),
    ]
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(
                lambda pair: clients[0 if pair[1] == "task-a" else 1].post(
                    "/api/agent-state/tasks",
                    {"action": "checkpoint", "root": pair[0], "task_id": pair[1]},
                    timeout=2.0,
                ),
                requests,
            ))
    finally:
        for client in clients:
            client.close()

    assert all(result["success"] is True for result in results)
    assert sorted((tenant, payload["root"], payload["task_id"]) for _, _, tenant, payload in captured) == [
        ("tenant-a", "C:/tenant-a/work", "task-a"),
        ("tenant-b", "C:/tenant-b/work", "task-b"),
    ]


def test_concurrent_instrumented_mcp_actions_keep_task_metadata_isolated(monkeypatch) -> None:
    import threading

    from local_ai_hub import mcp_server
    from local_ai_hub.trace_context import efficiency_metadata

    captured = []
    lock = threading.Lock()
    both_dispatches = threading.Barrier(2)

    class FakeClient:
        def coord(self, **payload):
            metadata = efficiency_metadata()
            operation = mcp_server._CURRENT_OPERATIONAL_CONTEXT.get()
            with lock:
                captured.append((
                    payload["action"],
                    payload["task_id"],
                    metadata.get("task_id"),
                    operation,
                ))
            both_dispatches.wait(timeout=2)
            return {
                "success": True,
                "task_id": payload["task_id"],
                "task": {"task_id": payload["task_id"], "status": "active"},
                "status": "active",
            }

    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server.FEATURES, "agent_os", True)
    monkeypatch.setattr(mcp_server, "CLIENT", FakeClient())

    async def run_calls():
        return await asyncio.gather(*(
            asyncio.to_thread(
                mcp_server.local_ai_coord,
                action="task_checkpoint",
                root=".",
                task_id=task_id,
                checkpoint={"next_action": query},
            )
            for query, task_id in (
                ("query-a", "task-a"),
                ("query-b", "task-b"),
            )
        ))

    results = asyncio.run(run_calls())

    assert all(payload["success"] is True for payload in results)
    assert sorted(set(captured)) == [
        ("task_checkpoint", "task-a", "task-a", ("task_checkpoint", True)),
        ("task_checkpoint", "task-b", "task-b", ("task_checkpoint", True)),
    ]

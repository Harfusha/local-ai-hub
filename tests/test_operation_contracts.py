import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import get_args

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_ai_hub.features import FeatureSet
from local_ai_hub.generator import generate_mcp_tool_schemas
from local_ai_hub import mcp_server as local_ai_mcp
from local_ai_hub.operation_contracts import (
    OPERATION_CONTRACTS,
    operation_actions,
    operation_input_schema,
    operation_metadata,
    operation_output_schema,
    operation_parameters_schema,
    operation_tool_output_schema,
    operation_tool_input_schema,
    validate_operation_arguments,
    validate_operation_output,
)


TOOL = "local_ai_artifact"


def _config(*, enabled: bool = True) -> dict:
    return {
        "features": {
            "status": False,
            "repo": False,
            "tasks": False,
            "rag": False,
            "commands": False,
            "coord": False,
            "artifacts": enabled,
        },
        "artifacts": {"enabled": True},
        "token_saving": {"compact_responses": True},
    }


def test_artifact_registry_drives_feature_actions_and_generated_schema():
    config = _config()
    actions = list(operation_actions(TOOL))
    feature_set = FeatureSet.from_config(config)
    schema = generate_mcp_tool_schemas(config)[TOOL]["parameters"]

    assert actions == ["get", "slice", "list"]
    assert feature_set.supported_artifact_actions() == actions
    assert schema["properties"]["action"]["enum"] == actions
    assert "artifact_id" not in schema.get("required", [])
    assert schema["allOf"][0]["if"]["properties"]["action"]["enum"] == ["list"]
    assert schema["allOf"][0]["else"]["required"] == ["artifact_id"]
    assert schema["allOf"][0]["else"]["properties"]["artifact_id"]["minLength"] == 1
    assert schema["properties"]["binary"] == {"type": "boolean", "default": False}


def test_artifact_runtime_validation_matches_action_contract():
    assert validate_operation_arguments(TOOL, "get", {"artifact_id": ""}) == "artifact_id is required for action='get'"
    assert validate_operation_arguments(TOOL, "slice", {"artifact_id": ""}) == "artifact_id is required for action='slice'"
    assert validate_operation_arguments(TOOL, "list", {}) is None
    assert "expected one of get, slice, list" in validate_operation_arguments(TOOL, "unknown", {})
    assert validate_operation_arguments(TOOL, "list", {"offset": 0}) == "offset is not valid for action='list'"


def test_artifact_handler_applies_registry_validation_before_backend_call(monkeypatch):
    monkeypatch.setattr(local_ai_mcp, "FEATURES", FeatureSet.from_config(_config()))
    monkeypatch.setattr(local_ai_mcp, "_record_adoption", lambda *args, **kwargs: None)

    result = local_ai_mcp.local_ai_artifact(action="get")

    assert result["success"] is False
    assert result["error"] == "artifact_id is required for action='get'"


def test_artifact_operation_metadata_and_disabled_gate_are_explicit():
    contract = OPERATION_CONTRACTS[TOOL]
    assert contract["feature_gate"] == "artifacts"
    assert contract["timeout"]
    assert contract["projection"] == "artifact"
    assert all(
        operation["side_effects"] == "read_only"
        and operation["idempotent"] is True
        and operation["retry_safe"] is True
        and operation["automatic_replay"] is False
        for operation in contract["actions"].values()
    )
    assert FeatureSet.from_config(_config(enabled=False)).supported_artifact_actions() == []
    assert TOOL not in generate_mcp_tool_schemas(_config(enabled=False))
    expected_parameters = operation_parameters_schema(TOOL)
    generated_parameters = generate_mcp_tool_schemas(_config())[TOOL]["parameters"]
    assert generated_parameters["type"] == expected_parameters["type"]
    assert generated_parameters["allOf"] == expected_parameters["allOf"]
    assert all(
        generated_parameters["properties"][key] == value
        for key, value in expected_parameters["properties"].items()
    )


def test_surface_inventory_uses_generated_operation_contract_metadata():
    spec = importlib.util.spec_from_file_location("surface_inventory_contract_test", ROOT / "tools" / "surface_inventory.py")
    assert spec is not None and spec.loader is not None
    inventory_module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = inventory_module
    spec.loader.exec_module(inventory_module)

    inventory = inventory_module.collect_inventory(ROOT)
    action_findings = {
        row["name"]: row
        for row in inventory_module._findings(inventory)
        if row["surface"] == f"MCP action {TOOL}"
    }
    action_rows = {name: row["contract"] for name, row in action_findings.items()}

    assert set(action_rows) == set(operation_actions(TOOL))
    assert action_rows["get"]["required_fields"] == ["artifact_id"]
    assert action_rows["list"]["required_fields"] == []
    assert all(action_rows[action]["idempotent"] is True for action in action_rows)
    assert all(action_rows[action]["retry_safe"] is True for action in action_rows)
    assert all(action_rows[action]["automatic_replay"] is False for action in action_rows)
    assert all(action_rows[action]["projection"] == "artifact" for action in action_rows)
    assert all(
        "src/local_ai_hub/operation_contracts.py:OPERATION_CONTRACTS" in row["evidence"]
        for row in action_findings.values()
    )


def test_mcp_boundary_rejects_invalid_operation_before_handler(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from local_ai_hub import mcp_server

    called = False

    async def forbidden_handler_call(_name, _arguments, *, convert_result):
        nonlocal called
        called = True
        raise AssertionError("invalid contract must be rejected before handler dispatch")

    monkeypatch.setattr(
        mcp_server,
        "FEATURES",
        SimpleNamespace(repo=True, code_intelligence=False, status=True, agent_os=False),
    )
    monkeypatch.setattr(mcp_server.mcp._tool_manager, "call_tool", forbidden_handler_call)

    response = asyncio.run(
        mcp_server.mcp.call_tool("local_ai_repo", {"action": "graph"})
    )

    assert response[1]["status_code"] == 400
    assert "invalid action" in response[1]["error"]
    assert called is False

    response = asyncio.run(
        mcp_server.mcp.call_tool("local_ai_status", {"action": "agent_state"})
    )
    assert response[1]["status_code"] == 400
    assert "invalid action" in response[1]["error"]
    assert called is False


def test_runtime_validation_uses_gate_selector_and_action_fields():
    from types import SimpleNamespace

    from local_ai_hub.operation_contracts import validate_operation_call

    features = SimpleNamespace(
        repo=True,
        code_intelligence=False,
        status=True,
        work_orchestrator=True,
    )

    assert validate_operation_call("local_ai_repo", {"action": "search"}, features=features) is None

    invalid_action = validate_operation_call(
        "local_ai_repo", {"action": "graph"}, features=features
    )
    assert invalid_action is not None
    assert invalid_action[0] == 400
    assert "invalid action" in invalid_action[1]

    disabled = validate_operation_call(
        "local_ai_repo", {"action": "search"}, features=SimpleNamespace(repo=False)
    )
    assert disabled is not None
    assert disabled[0] == 403
    assert "disabled" in disabled[1]

    missing_required = validate_operation_call(
        "local_ai_work", {"action": "submit"}, features=features
    )
    assert missing_required is not None
    assert missing_required[0] == 400
    assert "root is required" in missing_required[1]

    # Omitted selectors keep handler defaults; explicit values are contract-checked.
    assert validate_operation_call("local_ai_repo", {"query": "x"}, features=features) is None


def test_registry_metadata_and_selector_schemas_cover_all_eight_public_tools():
    expected_selectors = {
        "local_ai_status": "detail",
        "local_ai_repo": "action",
        "local_ai_task": "action",
        "local_ai_rag": "action",
        "local_ai_command": "action",
        "local_ai_coord": "action",
        "local_ai_artifact": "action",
        "local_ai_work": "action",
    }
    config = _config()
    config["features"].update({
        "status": True,
        "repo": True,
        "tasks": True,
        "local_models": True,
        "rag": True,
        "commands": True,
        "coord": True,
        "agent_os": True,
        "artifacts": True,
        "work_orchestrator": True,
        "preprocessing": True,
        "batch_replacement": True,
    })
    config.update({
        "server": {"auto_start_ollama": True},
        "commands": {"enabled": True},
        "coord": {"enabled": True},
        "preprocessing": {"enabled": True},
        "work_orchestrator": {"enabled": True},
        "code_intelligence": {"enabled": True, "serena_enabled": True},
        "speculative_lint": {"enabled": True},
        "models": {"fast_code": "test-code", "vision": "test-vision"},
    })

    schemas = generate_mcp_tool_schemas(config)

    assert set(OPERATION_CONTRACTS) == set(expected_selectors)
    assert set(schemas) == set(expected_selectors)
    for tool, selector in expected_selectors.items():
        contract = OPERATION_CONTRACTS[tool]
        schema = schemas[tool]
        assert schema["x-operation-contract"]["actions"] == contract["actions"]
        assert schema["parameters"]["properties"][selector]["enum"] == list(contract["actions"])


def test_generated_parameters_are_registry_sourced_for_all_eight_tools():
    config = _config()
    config["features"].update({
        "status": True,
        "repo": True,
        "tasks": True,
        "local_models": True,
        "rag": True,
        "commands": True,
        "coord": True,
        "agent_os": True,
        "artifacts": True,
        "work_orchestrator": True,
        "preprocessing": True,
        "batch_replacement": True,
        "vision": True,
        "code_intelligence": True,
        "serena": True,
    })
    config.update({
        "server": {"auto_start_ollama": True},
        "commands": {"enabled": True},
        "coord": {"enabled": True},
        "preprocessing": {"enabled": True},
        "work_orchestrator": {"enabled": True},
        "code_intelligence": {"enabled": True, "serena_enabled": True},
        "speculative_lint": {"enabled": True},
        "models": {"fast_code": "test-code", "vision": "test-vision"},
    })

    schemas = generate_mcp_tool_schemas(config)

    assert set(schemas) == set(OPERATION_CONTRACTS)
    for tool, schema in schemas.items():
        assert schema["parameters"] == operation_parameters_schema(tool)


def test_registry_schemas_keep_feature_filters_and_action_specific_requirements():
    config = _config()
    config["features"].update({
        "status": True,
        "repo": True,
        "tasks": True,
        "local_models": True,
        "rag": True,
        "commands": True,
        "coord": True,
        "agent_os": False,
        "artifacts": True,
        "work_orchestrator": True,
        "preprocessing": False,
        "batch_replacement": False,
        "vision": False,
        "code_intelligence": False,
        "serena": False,
    })
    config.update({
        "server": {"auto_start_ollama": True},
        "commands": {"enabled": True},
        "coord": {"enabled": True},
        "preprocessing": {"enabled": False},
        "work_orchestrator": {"enabled": True},
        "code_intelligence": {"enabled": False, "serena_enabled": False},
        "speculative_lint": {"enabled": False},
        "models": {"fast_code": "test-code", "vision": "test-vision"},
    })

    schemas = generate_mcp_tool_schemas(config)
    feature_set = FeatureSet.from_config(config)
    for tool, schema in schemas.items():
        assert schema["parameters"] == operation_parameters_schema(tool, feature_set)

    status = schemas["local_ai_status"]["parameters"]["properties"]
    repo = schemas["local_ai_repo"]["parameters"]["properties"]
    task = schemas["local_ai_task"]["parameters"]["properties"]
    command = schemas["local_ai_command"]["parameters"]["properties"]
    coord = schemas["local_ai_coord"]["parameters"]["properties"]

    assert "agent_state" not in status["detail"]["enum"]
    assert "agent_state" not in status["action"]["enum"]
    assert "graph" not in repo["action"]["enum"]
    assert "dry_run" not in repo and "edits" not in repo
    assert "vision" not in task["action"]["enum"]
    assert "speculative_lint" not in command["action"]["enum"]
    assert "task_create" not in coord["action"]["enum"]
    assert schemas["local_ai_repo"]["parameters"]["properties"]["max_response_tokens"]["minimum"] == 0

    work_parameters = schemas["local_ai_work"]["parameters"]
    assert work_parameters["required"] == ["action"]
    work_action_rules = {
        row["if"]["properties"]["action"]["enum"][0]: row["then"]["required"]
        for row in work_parameters["allOf"]
    }
    assert work_action_rules["submit"] == ["root", "task"]
    assert work_action_rules["status"] == ["work_id"]
    assert work_action_rules["continue"] == ["work_id", "answer"]


def test_status_action_aliases_match_live_and_generated_schemas():
    config = _config()
    config["features"].update({"status": True, "agent_os": True})
    feature_set = FeatureSet.from_config(config)
    schema = generate_mcp_tool_schemas(config)["local_ai_status"]["parameters"]["properties"]
    detail_actions = list(operation_actions("local_ai_status", feature_set))

    assert schema["detail"]["enum"] == detail_actions
    assert schema["action"]["enum"] == detail_actions + ["status", "health", "check", "info"]

    import asyncio

    live_tool = next(
        tool for tool in asyncio.run(local_ai_mcp.mcp.list_tools())
        if tool.name == "local_ai_status"
    )
    live_actions = list(operation_actions("local_ai_status", local_ai_mcp.FEATURES))
    assert live_tool.inputSchema["properties"]["action"]["enum"] == (
        live_actions + ["status", "health", "check", "info"]
    )


def test_live_repo_action_literal_respects_batch_replacement_feature():
    disabled_config = _config()
    disabled_config["features"].update({"repo": True, "batch_replacement": False})
    disabled_features = FeatureSet.from_config(disabled_config)
    enabled_config = _config()
    enabled_config["features"].update({"repo": True, "batch_replacement": True})
    enabled_features = FeatureSet.from_config(enabled_config)

    disabled_actions = get_args(local_ai_mcp._repo_action_type(disabled_features))
    enabled_actions = get_args(local_ai_mcp._repo_action_type(enabled_features))
    assert "batch_replace" not in disabled_actions
    assert "batch_replace" in enabled_actions


def test_repo_search_timeout_respects_120_second_protocol_limit(monkeypatch):
    captured = {}

    def post(path, payload, *, timeout):
        captured.update(path=path, payload=payload, timeout=timeout)
        return {"success": True, "results": []}

    monkeypatch.setattr(local_ai_mcp, "FEATURES", SimpleNamespace(repo=True, enriched_search=False))
    monkeypatch.setattr(local_ai_mcp, "CLIENT", SimpleNamespace(post=post))
    monkeypatch.setattr(local_ai_mcp, "MCP_CFG", {"quick_timeout_seconds": 180})
    monkeypatch.setattr(local_ai_mcp, "_client_root", lambda root: root)

    local_ai_mcp._local_ai_repo_impl(
        action="search", root="C:/repo", query="needle",
        path_hints=[{"path": "src", "purpose": "repository_search", "scope": "repo_search"}],
    )

    assert captured == {
        "path": "/api/search",
        "payload": {
            "root": "C:/repo", "query": "needle", "top_k": 12, "enrich": False,
            "path_hints": [{"path": "src", "purpose": "repository_search", "scope": "repo_search"}],
        },
        "timeout": 120,
    }


def test_repo_verify_receipt_schema_and_runtime_require_complete_typed_receipt():
    config = _config()
    config["features"].update({"repo": True, "coord": True, "agent_os": True})
    feature_set = FeatureSet.from_config(config)
    parameters = generate_mcp_tool_schemas(config)["local_ai_repo"]["parameters"]
    receipt_schema = parameters["properties"]["receipt"]

    assert receipt_schema["type"] == "object"
    assert receipt_schema["required"] == ["task_id", "criterion", "passed"]
    assert receipt_schema["properties"]["passed"]["type"] == "boolean"
    verify_rule = next(
        row for row in parameters["allOf"]
        if row["if"]["properties"]["action"]["enum"] == ["verify_receipt"]
    )
    assert verify_rule["then"]["required"] == ["receipt"]

    assert validate_operation_arguments(
        "local_ai_repo", "verify_receipt",
        {"receipt": {"task_id": "task-1", "criterion": "focused test", "passed": False}},
        features=feature_set,
    ) is None
    assert validate_operation_arguments(
        "local_ai_repo", "verify_receipt",
        {"receipt": {"task_id": "task-1", "criterion": "focused test"}},
        features=feature_set,
    ) == "receipt.passed is required for action='verify_receipt'"
    assert validate_operation_arguments(
        "local_ai_repo", "verify_receipt",
        {"receipt": {"task_id": "task-1", "criterion": "focused test", "passed": "false"}},
        features=feature_set,
    ) == "receipt.passed must be boolean for action='verify_receipt'"


def test_repo_verify_receipt_requires_evidence_for_passed_receipts():
    config = _config()
    config["features"].update({"repo": True, "coord": True, "agent_os": True})
    feature_set = FeatureSet.from_config(config)
    receipt_schema = generate_mcp_tool_schemas(config)["local_ai_repo"]["parameters"]["properties"]["receipt"]

    assert receipt_schema["properties"]["receipt_id"]["type"] == "string"
    assert receipt_schema["properties"]["observed_at"]["type"] == "number"
    assert receipt_schema["properties"]["expires_at"]["type"] == ["number", "null"]
    evidence_rule = next(
        row for row in receipt_schema["allOf"]
        if row["if"]["properties"]["passed"]["enum"] == [True]
    )
    assert evidence_rule["then"]["required"] == ["evidence_id"]
    assert evidence_rule["then"]["properties"]["evidence_id"]["minLength"] == 1

    assert validate_operation_arguments(
        "local_ai_repo", "verify_receipt",
        {"receipt": {"task_id": "task-1", "criterion": "focused test", "passed": True}},
        features=feature_set,
    ) == "receipt.evidence_id is required for passed verification receipts"
    assert validate_operation_arguments(
        "local_ai_repo", "verify_receipt",
        {"receipt": {
            "task_id": "task-1", "criterion": "focused test", "passed": True,
            "evidence_id": "test-run-1",
        }},
        features=feature_set,
    ) is None


def test_repo_verify_receipt_validates_nested_schema_types():
    config = _config()
    config["features"].update({"repo": True, "coord": True, "agent_os": True})
    feature_set = FeatureSet.from_config(config)
    receipt = {"task_id": "task-1", "criterion": "focused test", "passed": False}

    invalid_observed_at = validate_operation_arguments(
        "local_ai_repo", "verify_receipt",
        {"receipt": {**receipt, "observed_at": "not-a-number"}},
        features=feature_set,
    )
    invalid_expires_at = validate_operation_arguments(
        "local_ai_repo", "verify_receipt",
        {"receipt": {**receipt, "expires_at": True}},
        features=feature_set,
    )
    invalid_receipt_id = validate_operation_arguments(
        "local_ai_repo", "verify_receipt",
        {"receipt": {**receipt, "receipt_id": ""}},
        features=feature_set,
    )
    whitespace_task_id = validate_operation_arguments(
        "local_ai_repo", "verify_receipt",
        {"receipt": {**receipt, "task_id": "   "}},
        features=feature_set,
    )

    assert invalid_observed_at == "receipt.observed_at must be number for action='verify_receipt'"
    assert invalid_expires_at == "receipt.expires_at must be number or null for action='verify_receipt'"
    assert invalid_receipt_id == "receipt.receipt_id must have at least 1 characters for action='verify_receipt'"
    assert whitespace_task_id == "receipt.task_id is required for action='verify_receipt'"


def test_runtime_validation_enforces_registered_schema_constraints():
    assert validate_operation_arguments(
        "local_ai_artifact", "list", {"max_response_tokens": -1}
    ) == "max_response_tokens must be >= 0 for action='list'"
    assert validate_operation_arguments(
        "local_ai_artifact", "list", {"response_profile": "unregistered"}
    ) == "response_profile must be one of minimal, compact, standard, debug, delta for action='list'"
    assert validate_operation_arguments(
        "local_ai_task", "evaluation_record", {"quality_pass": "true"}
    ) == "quality_pass must be boolean or null for action='evaluation_record'"


def test_mcp_compaction_preserves_reliability_evidence_and_cancel_metadata(monkeypatch):
    monkeypatch.setattr(
        local_ai_mcp,
        "PROJECTOR",
        SimpleNamespace(project=lambda value, *_args, **_kwargs: value),
    )
    monkeypatch.setattr(local_ai_mcp, "RESPONSE_BUDGET_ENABLED", True)
    options_token = local_ai_mcp._CURRENT_RESPONSE_OPTIONS.set({
        "max_response_tokens": 512,
        "response_profile": "minimal",
    })
    try:
        result = local_ai_mcp._compact({
            "success": False,
            "terminal": True,
            "retryable": False,
            "degraded": True,
            "stale": True,
            "evidence_ids": ["E123"],
            "cancelled": True,
            "cancel_requested": True,
            "cancel_reason": "operator request",
            "text": "detail " * 4000,
            "bulk": {f"field_{index}": index for index in range(1000)},
        })
    finally:
        local_ai_mcp._CURRENT_RESPONSE_OPTIONS.reset(options_token)

    assert result["success"] is False
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert result["degraded"] is True
    assert result["stale"] is True
    assert result["evidence_ids"] == ["E123"]
    assert result["cancelled"] is True
    assert result["cancel_requested"] is True
    assert result["cancel_reason"] == "operator request"


def test_action_metadata_exposes_consistent_input_and_output_schemas():
    config = _config()
    config["features"].update({
        "status": True,
        "repo": True,
        "tasks": True,
        "local_models": True,
        "rag": True,
        "commands": True,
        "coord": True,
        "agent_os": True,
        "artifacts": True,
        "work_orchestrator": True,
        "preprocessing": True,
        "batch_replacement": True,
        "vision": True,
        "code_intelligence": True,
        "serena": True,
    })
    config.update({
        "server": {"auto_start_ollama": True},
        "commands": {"enabled": True},
        "coord": {"enabled": True},
        "preprocessing": {"enabled": True},
        "work_orchestrator": {"enabled": True},
        "code_intelligence": {"enabled": True, "serena_enabled": True},
        "speculative_lint": {"enabled": True},
        "models": {"fast_code": "test-code", "vision": "test-vision"},
    })
    schemas = generate_mcp_tool_schemas(config)

    assert set(schemas) == set(OPERATION_CONTRACTS)
    for tool, generated in schemas.items():
        metadata = operation_metadata(tool)
        selector = OPERATION_CONTRACTS[tool]["selector_field"]
        actions = operation_actions(tool)

        assert list(metadata["actions"]) == list(OPERATION_CONTRACTS[tool]["action_order"])
        assert list(generated["x-operation-contract"]["actions"]) == list(metadata["actions"])
        for action in actions:
            action_metadata = metadata["actions"][action]
            input_schema = operation_input_schema(tool, action)
            output_schema = operation_output_schema(tool, action)

            assert action_metadata["input_schema"] == input_schema
            assert action_metadata["output_schema"] == output_schema
            assert OPERATION_CONTRACTS[tool]["actions"][action]["input_schema"] == input_schema
            assert OPERATION_CONTRACTS[tool]["actions"][action]["output_schema"] == output_schema
            assert input_schema["type"] == "object"
            assert input_schema["properties"][selector]["enum"] == [action]
            assert input_schema["required"] == [selector, *action_metadata["required"]]
            assert output_schema["type"] == "object"
            assert output_schema["additionalProperties"] is False
            assert output_schema["title"] == f"{tool}.{action} result"
            assert generated["x-operation-contract"]["actions"][action] == action_metadata


def test_status_adoption_fields_are_registered_and_validated_as_a_pair():
    parameters = operation_parameters_schema("local_ai_status")
    properties = parameters["properties"]

    assert properties["adoption_signal"]["enum"] == ["", "bypassed"]
    assert properties["target_tool"]["enum"] == list(OPERATION_CONTRACTS)
    assert properties["target_action"]["type"] == "string"
    assert validate_operation_arguments(
        "local_ai_status",
        "brief",
        {
            "detail": "brief",
            "adoption_signal": "bypassed",
            "target_tool": "local_ai_repo",
            "target_action": "search",
        },
    ) is None
    assert validate_operation_arguments(
        "local_ai_status", "brief", {"detail": "brief", "target_tool": "local_ai_repo"}
    ) == "target_tool requires adoption_signal='bypassed'"
    assert validate_operation_arguments(
        "local_ai_status",
        "brief",
        {
            "detail": "brief",
            "adoption_signal": "bypassed",
            "target_tool": "local_ai_repo",
            "target_action": "unknown",
        },
    ) == "target_action is not supported for target_tool='local_ai_repo'"


def test_primary_tool_outputs_publish_distinct_action_shapes():
    representatives = {
        "local_ai_repo": ("search", "results"),
        "local_ai_task": ("submit", "job_id"),
        "local_ai_rag": ("search", "results"),
        "local_ai_command": ("run", "exit_code"),
        "local_ai_coord": ("task_create", "task_id"),
        "local_ai_work": ("submit", "work_id"),
    }

    for tool, (action, result_field) in representatives.items():
        action_schema = operation_output_schema(tool, action)
        tool_schema = operation_tool_output_schema(tool)

        assert result_field in action_schema["properties"]
        assert action_schema["x-operation-action"] == action
        assert tool_schema["anyOf"]
        assert {branch["x-operation-action"] for branch in tool_schema["anyOf"]} == set(
            operation_actions(tool)
        )


def test_every_primary_action_publishes_typed_payload_fields():
    envelope_fields = {
        "success", "error", "terminal", "retryable", "degraded", "stale",
        "evidence_ids", "cancelled", "cancel_requested", "cancel_reason",
    }
    for tool in (
        "local_ai_repo", "local_ai_task", "local_ai_rag",
        "local_ai_command", "local_ai_coord", "local_ai_work",
    ):
        for action in operation_actions(tool):
            schema = operation_output_schema(tool, action)
            payload_fields = set(schema["properties"]) - envelope_fields
            assert payload_fields, f"{tool}.{action} has only a generic response envelope"
            assert schema["x-operation-action"] == action


@pytest.mark.parametrize(
    ("tool", "action", "field", "expected_schema", "valid_value", "invalid_value"),
    [
        ("local_ai_repo", "preprocess_status", "projects", {"type": "array", "items": {"type": "object"}}, [], "bad"),
        ("local_ai_command", "webhook_replay", "status_code", {"type": "integer"}, 200, "200"),
        ("local_ai_command", "webhook_replay", "duration_ms", {"type": "number"}, 1.5, "1.5"),
        ("local_ai_coord", "task_zombie_reap", "reaped", {"type": "array", "items": {"type": "string"}}, ["task-1"], [1]),
        ("local_ai_coord", "task_zombie_reap", "count", {"type": "integer"}, 1, "1"),
        ("local_ai_coord", "task_cleanup_worktree", "had_worktree", {"type": "boolean"}, True, 1),
        ("local_ai_coord", "task_cleanup_worktree", "cleanup", {"type": "object"}, {}, []),
    ],
)
def test_action_output_contracts_type_specialized_dispatch_results(
    tool, action, field, expected_schema, valid_value, invalid_value
):
    schema = operation_output_schema(tool, action)
    assert schema["properties"][field] == expected_schema
    assert schema["x-operation-action"] == action
    assert validate_operation_output(tool, action, {"success": True, field: valid_value}) is None
    error = validate_operation_output(tool, action, {"success": True, field: invalid_value})
    assert field in error
    if tool == "local_ai_command" and action == "webhook_replay":
        assert validate_operation_output(
            tool, action, {"success": False, "error": "connection refused"}
        ) is None


def test_action_input_contracts_filter_tool_wide_fields_and_runtime_arguments():
    search = operation_input_schema("local_ai_repo", "search")
    batch = operation_input_schema("local_ai_repo", "batch_replace")

    assert {"root", "query", "include_code", "path_hints"} <= set(search["properties"])
    assert not {"receipt", "edits", "dry_run", "changed_paths"} & set(search["properties"])
    path_hints = search["properties"]["path_hints"]
    assert path_hints["type"] == "array"
    assert path_hints["items"]["required"] == ["path", "purpose", "scope"]
    assert {"evidence_id", "provenance", "repository_revision", "config_digest", "expires_at"} <= set(
        path_hints["items"]["properties"]
    )
    assert validate_operation_arguments(
        "local_ai_repo", "search", {
            "query": "find parser",
            "path_hints": [{"path": "src", "purpose": "repository_search", "scope": "repo_search"}],
        }
    ) is None
    assert validate_operation_arguments(
        "local_ai_repo", "search", {"query": "find parser", "path_hints": ["src"]}
    )
    assert {"root", "edits", "dry_run"} <= set(batch["properties"])
    assert "receipt" not in batch["properties"]
    assert validate_operation_arguments(
        "local_ai_repo", "search", {"query": "needle", "receipt": {}}
    ) == "receipt is not valid for action='search'"


def test_repo_search_path_hints_schema_declares_bounds():
    hints = operation_input_schema("local_ai_repo", "search")["properties"]["path_hints"]

    assert hints["maxItems"] == 64
    assert hints["items"]["properties"]["path"]["maxLength"] == 1024


@pytest.mark.parametrize(
    ("hints", "invalid_field"),
    [
        ([{"path": "src", "purpose": "repository_search"}], "scope"),
        ([{"path": "src", "purpose": "repository_search", "scope": "repo_search", "extra": "x"}], "extra"),
        ([{"path": "x" * 1025, "purpose": "repository_search", "scope": "repo_search"}], "path"),
        ([{"path": "src", "purpose": "repository_search", "scope": "repo_search"}] * 65, "path_hints"),
    ],
)
def test_repo_search_path_hints_rejects_invalid_nested_records(hints, invalid_field):
    error = validate_operation_arguments(
        "local_ai_repo", "search", {"query": "find parser", "path_hints": hints}
    )

    assert error is not None
    assert invalid_field in error


def test_task_submit_contract_includes_async_job_payload_arguments():
    submit = operation_input_schema("local_ai_task", "submit")
    status = operation_input_schema("local_ai_task", "status")

    assert {"task", "context", "candidate", "complexity", "max_tokens", "tasks", "profile", "root", "workspace"} <= set(submit["properties"])
    assert {"job_id", "job_action", "timeout_seconds"} <= set(submit["properties"])
    assert not {"task", "context", "candidate", "tasks", "profile", "workspace"} & set(status["properties"])
    assert validate_operation_arguments(
        "local_ai_task",
        "submit",
        {"task": "summarize", "context": "brief", "tasks": [], "job_action": "reason"},
    ) is None


def test_coord_contracts_include_handler_consumed_arguments():
    receipt = operation_input_schema("local_ai_coord", "verify_receipt")
    completion = operation_input_schema("local_ai_coord", "verify_completion")
    relation = operation_input_schema("local_ai_coord", "relation_record")
    sync = operation_input_schema("local_ai_coord", "task_sync")

    assert {"checkpoint", "status", "criterion", "key", "value", "query"} <= set(receipt["properties"])
    assert {"repository_revision", "task_id", "query", "value", "key"} <= set(completion["properties"])
    assert {"key", "task_id", "query", "task", "reason", "status", "value", "target_scope", "record", "ttl_seconds", "max_tokens"} <= set(relation["properties"])
    assert {"key", "task_id", "status", "ttl_seconds", "max_tokens", "record"} <= set(sync["properties"])
    assert validate_operation_arguments(
        "local_ai_coord", "verify_receipt",
        {"task_id": "task-1", "checkpoint": {"task_id": "task-1", "criterion": "check", "passed": True}, "status": "passed"},
    ) is None
    assert validate_operation_arguments(
        "local_ai_coord", "verify_completion", {"task_id": "task-1", "repository_revision": "abc"}
    ) is None
    assert validate_operation_arguments(
        "local_ai_coord", "relation_record", {"key": "source", "value": "target", "reason": "depends_on", "ttl_seconds": 1}
    ) is None
    assert validate_operation_arguments(
        "local_ai_coord", "task_sync", {"status": "import", "record": [{"seq": 1}]}
    ) is None


def test_task_continue_contract_includes_conversation_id():
    schema = operation_input_schema("local_ai_task", "continue")

    assert "conversation_id" in schema["properties"]
    assert validate_operation_arguments(
        "local_ai_task", "continue", {"conversation_id": "conversation-1", "task": "continue"}
    ) is None


def test_coord_decision_and_merge_contracts_include_handler_inputs():
    assert validate_operation_arguments(
        "local_ai_coord", "incident_decision",
        {"fingerprint": {"kind": "timeout"}, "tool_outcome": {"success": False}},
    ) is None
    assert validate_operation_arguments(
        "local_ai_coord", "simulate_merge",
        {"key": "feature", "task_id": "branch", "value": "source", "target_scope": "main"},
    ) is None


def test_repo_action_contracts_include_handler_inputs():
    cases = [
        ("generate_dataset", {"relation": "json"}),
        ("secret_scan", {"staged": True}),
        ("complexity", {"include_tests": True}),
        ("git_diff", {"path": "src/app.py", "max_tokens": 100}),
        ("mutation_test", {"diff": "diff --git a/a b/a"}),
    ]
    for action, arguments in cases:
        schema = operation_input_schema("local_ai_repo", action)
        assert set(arguments) <= set(schema["properties"]), action
        assert validate_operation_arguments("local_ai_repo", action, arguments) is None, action


@pytest.mark.parametrize(
    ("tool", "action", "arguments", "path"),
    [
        ("local_ai_task", "batch", {"tasks": [{"options": {"temperature": float("nan")}}]}, "tasks[0].options.temperature"),
        ("local_ai_coord", "task_sync", {"status": "import", "record": [{"weight": float("inf")}]}, "record[0].weight"),
    ],
)
def test_non_finite_numbers_are_rejected_recursively(tool, action, arguments, path):
    error = validate_operation_arguments(tool, action, arguments)
    assert error == f"{path} must be finite for action='{action}'"


def test_task_sync_output_contract_describes_export_and_import_deltas():
    schema = operation_output_schema("local_ai_coord", "task_sync")

    assert {"events", "count", "imported_count", "duplicate_count"} <= set(schema["properties"])
    assert validate_operation_output(
        "local_ai_coord", "task_sync", {"success": True, "events": [{"seq": 1}], "count": 1}
    ) is None
    assert validate_operation_output(
        "local_ai_coord", "task_sync", {"success": True, "events": "bad", "count": 1}
    ) is not None


def test_non_finite_numbers_are_rejected_in_untyped_nested_output_fields():
    error = validate_operation_output(
        "local_ai_repo", "search", {"results": [{"scores": [float("nan")]}]}
    )
    assert error == "result.results[0].scores[0] must be finite for action='search'"


def test_every_registered_action_has_a_narrow_input_contract():
    for tool, contract in OPERATION_CONTRACTS.items():
        tool_properties = set(operation_parameters_schema(tool)["properties"])
        feature_properties = set()
        for fields in contract.get("conditional_properties", {}).values():
            feature_properties.update(fields)
        for action in operation_actions(tool):
            action_contract = contract["actions"][action]
            schema = operation_input_schema(tool, action)
            assert action_contract["allowed"] is not None, f"{tool}.{action} has no allowlist"
            assert set(action_contract["allowed"]) <= tool_properties | feature_properties
            assert schema["additionalProperties"] is False
            common = {"extra_fields", contract["selector_field"]}
            common.update({"max_response_tokens", "response_profile", "reuse_key"})
            if tool == "local_ai_status":
                common.add("action")
            expected = (common | set(action_contract["allowed"])) & tool_properties
            assert set(schema["properties"]) == expected, f"{tool}.{action} exposes unrelated inputs"


def test_live_input_schema_conditions_each_action_on_its_allowed_fields():
    feature_set = FeatureSet({"features": {"repo": True, "batch_replacement": True}})
    schema = operation_tool_input_schema("local_ai_repo", feature_set)
    branches = {
        row["if"]["properties"]["action"]["const"]: row["then"]
        for row in schema["allOf"]
        if row.get("if", {}).get("properties", {}).get("action", {}).get("const")
    }

    search = branches["search"]
    batch = branches["batch_replace"]
    assert search["additionalProperties"] is False
    assert {"root", "query", "include_code", "path_hints"} <= set(search["properties"])
    assert not {"receipt", "edits", "dry_run", "changed_paths"} & set(search["properties"])
    assert {"root", "edits", "dry_run"} <= set(batch["properties"])


@pytest.mark.parametrize(
    ("tool", "action", "result", "field"),
    [
        ("local_ai_repo", "search", {"results": "not-an-array"}, "results"),
        ("local_ai_task", "submit", {"job_id": 42}, "job_id"),
        ("local_ai_rag", "search", {"results": "not-an-array"}, "results"),
        ("local_ai_command", "run", {"exit_code": "zero"}, "exit_code"),
        ("local_ai_coord", "task_create", {"task_id": 42}, "task_id"),
        ("local_ai_work", "submit", {"work_id": 42}, "work_id"),
    ],
)
def test_all_public_tool_payload_fields_are_runtime_validated(tool, action, result, field):
    error = validate_operation_output(tool, action, result)
    assert error is not None
    assert field in error


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_top_level_numbers_are_rejected(value):
    error = validate_operation_arguments(
        "local_ai_task", "delegate", {"task": "summarize", "latency_budget_ms": value}
    )
    assert error == "latency_budget_ms must be finite for action='delegate'"


def test_output_contract_rejects_non_object_and_non_finite_declared_values():
    assert "wrong JSON type" in validate_operation_output("local_ai_repo", "search", ["not an object"])
    error = validate_operation_output("local_ai_repo", "deterministic", {"confidence": float("nan")})
    assert error is not None and "confidence" in error


def test_artifact_list_schema_rejects_fields_used_only_by_get_and_slice():
    schema = operation_input_schema("local_ai_artifact", "list")

    assert "artifact_id" not in schema["properties"]
    assert validate_operation_arguments(
        "local_ai_artifact", "list", {"artifact_id": "artifact-1"}
    ) == "artifact_id is not valid for action='list'"


@pytest.mark.parametrize("action", ["get", "slice"])
def test_artifact_slice_numeric_bounds_are_published_and_enforced(action):
    schema = operation_input_schema("local_ai_artifact", action)
    assert schema["properties"]["offset"]["minimum"] == 0
    assert schema["properties"]["max_chars"]["minimum"] == 512
    assert schema["properties"]["max_chars"]["maximum"] == 12000

    base = {"artifact_id": "artifact-1"}
    assert validate_operation_arguments(
        "local_ai_artifact", action, {**base, "offset": 0, "max_chars": 512}
    ) is None
    assert validate_operation_arguments(
        "local_ai_artifact", action, {**base, "max_chars": 12000}
    ) is None
    assert validate_operation_arguments(
        "local_ai_artifact", action, {**base, "offset": -1}
    ) is not None
    for max_chars in (511, 12001):
        assert validate_operation_arguments(
            "local_ai_artifact", action, {**base, "max_chars": max_chars}
        ) is not None


def test_artifact_output_schemas_describe_source_payload_variants():
    list_schema = operation_output_schema("local_ai_artifact", "list")
    get_schema = operation_output_schema("local_ai_artifact", "get")

    list_success = next(
        branch for branch in list_schema["anyOf"]
        if branch.get("properties", {}).get("artifacts")
    )
    artifact = list_success["properties"]["artifacts"]["items"]
    assert artifact["properties"] == {
        "artifact_id": {"type": "string"},
        "kind": {"type": "string"},
        "size_bytes": {"type": "integer"},
        "created_at": {"type": "number"},
        "mime_type": {"type": "string"},
    }
    assert {"text", "evidence_id", "binary_payload"}.issubset(
        set(get_schema["anyOf"][0]["properties"])
        | set(get_schema["anyOf"][1]["properties"])
        | set(get_schema["anyOf"][2]["properties"])
    )


def test_mcp_tools_list_publishes_artifact_output_shape_union():
    import asyncio

    from local_ai_hub import mcp_server

    tool = next(
        item for item in asyncio.run(mcp_server.mcp.list_tools())
        if item.name == "local_ai_artifact"
    )
    output_schema = tool.outputSchema

    assert len(output_schema["anyOf"]) == 3
    list_action = next(
        shape for shape in output_schema["anyOf"]
        if any("artifacts" in variant.get("properties", {}) for variant in shape["anyOf"])
    )
    list_shape = next(
        variant for variant in list_action["anyOf"]
        if "artifacts" in variant.get("properties", {})
    )
    assert list_shape["properties"]["artifacts"]["items"]["required"] == [
        "artifact_id", "kind", "size_bytes", "created_at", "mime_type"
    ]


def test_mcp_tools_list_scopes_artifact_list_arguments():
    import asyncio

    from local_ai_hub import mcp_server

    tool = next(
        item for item in asyncio.run(mcp_server.mcp.list_tools())
        if item.name == "local_ai_artifact"
    )
    input_schema = tool.inputSchema
    list_rule = next(
        rule for rule in input_schema["allOf"]
        if rule["if"]["properties"]["action"]["const"] == "list"
    )

    assert {"required": ["artifact_id"]} in list_rule["then"]["not"]["anyOf"]


def test_receipt_schema_conditionally_requires_evidence_only_when_passed():
    config = _config()
    config["features"].update({"repo": True, "coord": True, "agent_os": True})
    feature_set = FeatureSet.from_config(config)
    receipt_schema = generate_mcp_tool_schemas(config)["local_ai_repo"]["parameters"]["properties"]["receipt"]
    evidence_rule = next(
        row for row in receipt_schema["allOf"]
        if row["if"]["properties"]["passed"]["enum"] == [True]
    )

    assert evidence_rule["then"]["required"] == ["evidence_id"]
    assert evidence_rule["then"]["properties"]["evidence_id"]["minLength"] == 1
    assert validate_operation_arguments(
        "local_ai_repo", "verify_receipt",
        {"receipt": {"task_id": "task-1", "criterion": "focused test", "passed": False}},
        features=feature_set,
    ) is None
    assert validate_operation_arguments(
        "local_ai_repo", "verify_receipt",
        {"receipt": {
            "task_id": "task-1", "criterion": "focused test", "passed": True,
            "evidence_id": "  ",
        }},
        features=feature_set,
    ) == "receipt.evidence_id is required for passed verification receipts"


def test_output_validation_checks_shared_envelope_and_keeps_nested_payloads():
    valid_result = {
        "success": True,
        "terminal": False,
        "retryable": True,
        "error": "temporary",
        "results": [{"action_payload": {"count": 3}}],
    }

    assert validate_operation_output("local_ai_repo", "search", valid_result) is None
    assert validate_operation_output("local_ai_repo", "search", "plain text") == (
        "result has the wrong JSON type for action='search'"
    )
    assert validate_operation_output("local_ai_repo", "search", None) == (
        "result has the wrong JSON type for action='search'"
    )
    assert validate_operation_output(
        "local_ai_repo", "search", {**valid_result, "success": "yes"}
    ) == "success must be boolean for action='search'"
    assert validate_operation_output(
        "local_ai_repo", "search", {**valid_result, "terminal": 1}
    ) == "terminal must be boolean for action='search'"
    assert validate_operation_output(
        "local_ai_repo", "search", {**valid_result, "retryable": None}
    ) == "retryable must be boolean for action='search'"
    assert validate_operation_output(
        "local_ai_repo", "search", {**valid_result, "error": False}
    ) == "error must be string for action='search'"


def test_status_output_contracts_match_brief_and_cache_projections():
    brief = {
        "success": True,
        "version": "1.0",
        "ollama_online": None,
        "active_model": None,
        "queued": 0,
        "inflight": None,
        "net_cloud_token_delta_est": 12.5,
        "cache_hits": 3,
        "coalesced_waiters": 0,
        "vram_pressure": "nominal",
        "context_budget_factor": 1.0,
    }
    cache = {
        "success": True,
        "generation_cache": None,
        "semantic_cache": {},
        "repo_cache": None,
        "repo_snapshots": {},
        "commands": None,
        "lossless_router": {},
        "pipeline": None,
        "preprocessing": {},
        "tool_agent": None,
        "circuit_breakers": {},
        "fallback_count": 0,
        "embeddings": None,
        "reranker": None,
        "token_saving": {},
        "context_ledger": {},
    }

    assert validate_operation_output("local_ai_status", "brief", brief) is None
    assert validate_operation_output("local_ai_status", "cache", cache) is None
    assert validate_operation_output(
        "local_ai_status", "brief", {**brief, "queued": "0"}
    ) == "result.queued has the wrong JSON type for action='brief'"
    assert validate_operation_output(
        "local_ai_status", "cache", {**cache, "context_ledger": []}
    ) == "result.context_ledger has the wrong JSON type for action='cache'"


def test_status_telemetry_contract_types_every_projected_summary_metric():
    from local_ai_hub.operation_contracts import operation_output_schema

    report = {
        "success": True,
        "window": {},
        "summary": {"events": 1, "net_cloud_token_delta_est": 7.5},
        "queue": {},
        "hotspots": [],
        "by_operation": [],
        "error_fingerprints": [],
        "detail": {},
        "decision_grade": {},
    }
    projected = local_ai_mcp._telemetry_status_projection({"success": True, "report": report})
    schema = operation_output_schema("local_ai_status", "telemetry")

    assert projected["summary"]["net_cloud_token_delta_est"] == 7.5
    assert schema["anyOf"][0]["properties"]["summary"]["properties"]["net_cloud_token_delta_est"] == {"type": "number"}
    assert validate_operation_output("local_ai_status", "telemetry", projected) is None
    malformed = {
        **projected,
        "summary": {**projected["summary"], "net_cloud_token_delta_est": "7.5"},
    }
    assert validate_operation_output(
        "local_ai_status", "telemetry", malformed
    ) == "result.summary.net_cloud_token_delta_est has the wrong JSON type for action='telemetry'"


def test_status_full_and_agent_state_outputs_have_typed_success_and_failure_shapes():
    full = {
        "success": True,
        "hub_online": True,
        "version": "1.0",
        "uptime_seconds": 10,
        "features": {"status": True},
        "runtime_stats": {},
        "capabilities": {},
    }
    agent_state = {
        "success": True,
        "enabled": False,
        "active_tasks": [],
        "tasks_count": 0,
        "incidents_count": 0,
        "candidates_count": 0,
        "status": "healthy",
    }
    failure = {"success": False, "error": "status unavailable"}

    for action, payload, typed_fields in (
        ("full", full, {"hub_online": "boolean", "uptime_seconds": "integer"}),
        (
            "agent_state",
            agent_state,
            {"enabled": "boolean", "active_tasks": "array", "tasks_count": "integer"},
        ),
    ):
        schema = operation_output_schema("local_ai_status", action)
        success = next(branch for branch in schema["anyOf"] if branch.get("required"))
        failure_schema = next(
            branch for branch in schema["anyOf"]
            if branch.get("properties", {}).get("success", {}).get("const") is False
        )
        assert set(success["required"]) <= payload.keys()
        assert failure_schema["properties"]["error"] == {"type": "string"}
        for field, expected_type in typed_fields.items():
            assert success["properties"][field]["type"] == expected_type
        assert validate_operation_output("local_ai_status", action, payload) is None
        assert validate_operation_output("local_ai_status", action, failure) is None

    assert validate_operation_output(
        "local_ai_status", "full", {**full, "uptime_seconds": "10"}
    ) == "result.uptime_seconds has the wrong JSON type for action='full'"
    assert validate_operation_output(
        "local_ai_status", "agent_state", {**agent_state, "active_tasks": "none"}
    ) == "result.active_tasks has the wrong JSON type for action='agent_state'"

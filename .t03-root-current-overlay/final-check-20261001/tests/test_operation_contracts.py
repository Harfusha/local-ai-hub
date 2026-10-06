import importlib.util
import sys

import pytest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, get_args

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

    # Only selectors with declared defaults may be omitted.
    assert validate_operation_call("local_ai_status", {}, features=features) is None
    missing_repo_action = validate_operation_call(
        "local_ai_repo", {"query": "x"}, features=features
    )
    assert missing_repo_action is not None
    assert missing_repo_action[0] == 400
    assert "invalid action" in missing_repo_action[1]


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
    from local_ai_hub.operation_contracts import operation_tool_input_schema, validate_operation_arguments

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
    disabled_schema = operation_tool_input_schema("local_ai_repo", disabled_features)
    enabled_schema = operation_tool_input_schema("local_ai_repo", enabled_features)
    assert "edits" not in disabled_schema["properties"]
    assert "dry_run" not in disabled_schema["properties"]
    assert "edits" in enabled_schema["properties"]
    assert "dry_run" in enabled_schema["properties"]
    assert validate_operation_arguments(
        "local_ai_repo", "context", {"edits": []}, features=disabled_features
    ) is not None


def test_repo_search_timeout_respects_120_second_protocol_limit(monkeypatch):
    captured = {}

    def post(path, payload, *, timeout, path_hints=None):
        captured.update(path=path, payload=payload, timeout=timeout, path_hints=path_hints)
        return {"success": True, "results": []}

    monkeypatch.setattr(local_ai_mcp, "FEATURES", SimpleNamespace(repo=True, enriched_search=False))
    monkeypatch.setattr(local_ai_mcp, "CLIENT", SimpleNamespace(post=post))
    monkeypatch.setattr(local_ai_mcp, "MCP_CFG", {"quick_timeout_seconds": 180})
    monkeypatch.setattr(local_ai_mcp, "_client_root", lambda root: root)

    local_ai_mcp._local_ai_repo_impl(action="search", root="C:/repo", query="needle")

    assert captured == {
        "path": "/api/search",
        "payload": {"root": "C:/repo", "query": "needle", "top_k": 12, "enrich": False},
        "timeout": 120,
        "path_hints": None,
    }


def test_repo_path_hints_schema_is_bounded_and_context_scoped():
    from local_ai_hub.operation_contracts import (
        operation_input_schema,
        operation_tool_input_schema,
        validate_operation_arguments,
    )

    schema = operation_tool_input_schema("local_ai_repo")
    hints = schema["properties"]["path_hints"]
    assert hints["type"] == "array"
    assert hints["maxItems"] == 64
    item = hints["items"]
    assert item["required"] == ["path", "purpose", "scope"]
    assert item["properties"]["path"]["maxLength"] == 1024
    assert item["additionalProperties"] is False
    context_schema = operation_input_schema("local_ai_repo", "context")
    search_schema = operation_input_schema("local_ai_repo", "search")
    context_fields = ("path_hints", "directory_hints", "exclude_paths", "force_include_paths")
    assert all(field in context_schema["properties"] for field in context_fields)
    assert all(field not in search_schema["properties"] for field in context_fields[1:])
    assert all(schema["properties"][field]["maxItems"] == 64 for field in context_fields[1:])
    for field in context_fields:
        assert any(
            rule.get("if", {}).get("properties", {}).get("mode") == {"not": {"const": "adaptive"}}
            and rule.get("then", {}).get("not", {}).get("required") == [field]
            for rule in schema.get("allOf", [])
        )

    valid = {"path_hints": [{"path": "src/auth.py", "purpose": "repository_search", "scope": "repo_search"}]}
    assert validate_operation_arguments("local_ai_repo", "search", valid) is None
    context_hints = {
        **valid,
        "directory_hints": ["src"],
        "exclude_paths": ["vendor"],
        "force_include_paths": ["README.md"],
    }
    assert validate_operation_arguments("local_ai_repo", "context", context_hints) is None
    assert validate_operation_arguments(
        "local_ai_repo", "context", {"mode": "adaptive", **context_hints}
    ) is None
    for mode in ("fast", "full", "custom", None):
        assert validate_operation_arguments(
            "local_ai_repo", "context", {"mode": mode, "path_hints": None}
        ) is not None
    assert validate_operation_arguments(
        "local_ai_repo", "search", {"path_hints": [{"path": "src/auth.py", "purpose": "repository_search"}]}
    ) is not None
    assert validate_operation_arguments(
        "local_ai_repo", "search", {"path_hints": [{"path": "x" * 1025, "purpose": "repository_search", "scope": "repo_search"}]}
    ) is not None
    assert validate_operation_arguments(
        "local_ai_repo", "search", {"path_hints": [{"path": "src/auth.py", "purpose": "repository_search", "scope": "repo_search", "extra": "x"}]}
    ) is not None
    assert validate_operation_arguments("local_ai_repo", "search", {"path_hints": [{}] * 65}) is not None


def test_repo_verify_receipt_is_action_scoped():
    from local_ai_hub.operation_contracts import (
        operation_input_schema,
        operation_tool_input_schema,
        validate_operation_arguments,
    )
    from local_ai_hub.features import FeatureSet

    assert "receipt" not in operation_input_schema("local_ai_repo", "search")["properties"]
    assert "receipt" not in operation_input_schema("local_ai_repo", "context")["properties"]
    assert "receipt" in operation_input_schema("local_ai_repo", "verify_receipt")["properties"]

    valid_receipt = {
        "task_id": "task-1", "criterion": "focused test", "passed": False,
    }
    assert validate_operation_arguments(
        "local_ai_repo", "search", {"receipt": valid_receipt}
    ) == "receipt is only valid for action='verify_receipt'"

    disabled_config = _config()
    disabled_config["features"]["agent_os"] = False
    disabled_features = FeatureSet.from_config(disabled_config)
    disabled_schema = operation_tool_input_schema("local_ai_repo", disabled_features)
    assert "verify_receipt" not in disabled_schema["properties"]["action"]["enum"]
    assert any(
        rule.get("if", {}).get("properties", {}).get("action") == {"const": "context"}
        and rule.get("then", {}).get("not", {}).get("anyOf")
        for rule in disabled_schema.get("allOf", [])
    )
    assert validate_operation_arguments(
        "local_ai_repo", "context", {"receipt": valid_receipt}, features=disabled_features
    ) == "receipt is only valid for action='verify_receipt'"


def test_local_ai_repo_path_hints_normalize_and_reject_root_escape(monkeypatch, tmp_path):
    from local_ai_hub import mcp_server

    captured = []
    hint = {"path": str(tmp_path / "src"), "purpose": "repository_search", "scope": "repo_search"}

    def consumer(*args, path_hints=None):
        captured.append(path_hints)
        return {"success": True}

    monkeypatch.setattr(mcp_server, "_local_ai_repo_impl", consumer)
    result = mcp_server.local_ai_repo("search", root=str(tmp_path), path_hints=[hint])
    assert result["success"] is True
    assert captured == [[{**hint, "path": "src"}]]

    rejected = mcp_server.local_ai_repo(
        "search",
        root=str(tmp_path),
        path_hints=[{"path": "../escape", "purpose": "repository_search", "scope": "repo_search"}],
    )
    assert rejected["success"] is False
    assert len(captured) == 1


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
        "local_ai_task", "reason", {"quality_pass": "true"}
    ) == "quality_pass must be boolean or null for action='reason'"


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
            assert output_schema["additionalProperties"] is True
            assert output_schema["title"] == f"{tool}.{action} result"
            assert generated["x-operation-contract"]["actions"][action] == action_metadata


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


def test_mcp_tools_list_publishes_shared_output_envelope():
    import asyncio

    from local_ai_hub import mcp_server
    from local_ai_hub.operation_contracts import operation_tool_output_schema

    tool = next(
        item for item in asyncio.run(mcp_server.mcp.list_tools())
        if item.name == "local_ai_artifact"
    )
    output_schema = tool.outputSchema

    assert output_schema == operation_tool_output_schema("local_ai_artifact")
    assert output_schema["type"] == "object"
    assert output_schema["additionalProperties"] is True
    assert "anyOf" not in output_schema
    assert {"success", "status", "status_code", "error", "warning", "terminal", "retryable"} <= set(
        output_schema["properties"]
    )


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


def test_output_validation_checks_shared_envelope_and_keeps_extra_payloads():
    valid_result = {
        "success": True,
        "terminal": False,
        "retryable": True,
        "error": "temporary",
        "action_payload": {"count": 3},
    }

    assert validate_operation_output("local_ai_repo", "search", valid_result) is None
    assert validate_operation_output("local_ai_repo", "search", "plain text") == "result must be an object"
    assert validate_operation_output("local_ai_repo", "search", None) == "result must be an object"
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
    ) == "result does not match a declared output variant for action='brief'"
    assert validate_operation_output(
        "local_ai_status", "cache", {**cache, "context_ledger": []}
    ) == "result does not match a declared output variant for action='cache'"


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
    ) == "result does not match a declared output variant for action='telemetry'"



def _stub_registered_mcp_tool(monkeypatch, tool_name: str, value: Any):
    import local_ai_hub.mcp_server as mcp_server

    calls: list[dict[str, Any]] = []
    registered_tool = mcp_server.mcp._tool_manager._tools[tool_name]

    def fake_handler(**arguments: Any):
        calls.append(arguments)
        return value

    monkeypatch.setattr(registered_tool, "fn", fake_handler)
    return calls


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("local_ai_rag", {"action": "ingest_document", "content": "body", "title": "doc", "metadata": {}}),
        ("local_ai_rag", {"action": "ingest_diagram", "image_path": "diagram.svg", "caption": "diagram"}),
        ("local_ai_task", {"action": "cancel", "job_id": "job-1"}),
        ("local_ai_task", {
            "action": "reason", "task": "review", "phase": "review", "focus": ["src"],
            "preload_profile": "balanced", "repository_revision": "abc123", "changed_paths": ["src/a.py"],
        }),
        ("local_ai_repo", {
            "action": "context_compile", "include_diagnostics": True, "clone_id": "clone",
            "worktree_id": "worktree", "branch": "main", "repository_id": "repo",
            "session_id": "session", "repository_revision": "abc123",
        }),
        ("local_ai_repo", {"action": "pipeline", "steps": [{"action": "profile"}]}),
        ("local_ai_repo", {"action": "preprocess", "is_worktree": True, "parent_root": "."}),
        ("local_ai_status", {
            "adoption_signal": "bypassed", "target_tool": "local_ai_repo", "target_action": "search",
        }),
        ("local_ai_task", {"action": "eval_suite", "task_id": "task-1", "cases": [], "language": "python"}),
        ("local_ai_command", {"action": "patch_and_verify", "execution_id": "exec-1", "paths": ["src/a.py"], "patch": "diff"}),
        ("local_ai_coord", {"action": "task_complete", "task_id": "task-1", "criterion": "c1", "board_id": "board-1"}),
    ],
)
def test_registered_mcp_dispatch_accepts_handler_inputs(
    tool_name: str, arguments: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    import local_ai_hub.mcp_server as mcp_server

    result: dict[str, Any] = {"success": True}
    if tool_name == "local_ai_status":
        result.update({
            "version": "1.0",
            "ollama_online": None,
            "active_model": None,
            "queued": 0,
            "inflight": None,
            "net_cloud_token_delta_est": 0.0,
            "cache_hits": 0,
            "coalesced_waiters": 0,
            "vram_pressure": "nominal",
            "context_budget_factor": 1.0,
        })
    calls = _stub_registered_mcp_tool(monkeypatch, tool_name, result)
    response = asyncio.run(mcp_server.mcp.call_tool(tool_name, arguments))

    assert response[1]["success"] is True
    assert len(calls) == 1
    assert all(calls[0][key] == value for key, value in arguments.items())


@pytest.mark.parametrize(
    ("tool_name", "arguments", "field"),
    [
        ("local_ai_task", {"action": "cancel", "phase": "review"}, "phase"),
        ("local_ai_repo", {"action": "search", "clone_id": "clone"}, "clone_id"),
        ("local_ai_repo", {"action": "preprocess", "include_diagnostics": True}, "include_diagnostics"),
        ("local_ai_repo", {"action": "context_compile", "is_worktree": True}, "is_worktree"),
    ],
)
def test_registered_mcp_dispatch_rejects_context_fields_for_wrong_action(
    tool_name: str, arguments: dict[str, Any], field: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    import local_ai_hub.mcp_server as mcp_server

    calls = _stub_registered_mcp_tool(monkeypatch, tool_name, {"success": True})
    response = asyncio.run(mcp_server.mcp.call_tool(tool_name, arguments))

    assert response[1]["status_code"] == 400
    assert field in response[1]["error"]
    assert calls == []


def test_registered_status_dispatch_rejects_incomplete_adoption_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    import local_ai_hub.mcp_server as mcp_server

    class NeverCallClient:
        def get(self, *_args, **_kwargs):
            raise AssertionError("incomplete adoption report reached backend")

    monkeypatch.setattr(mcp_server, "CLIENT", NeverCallClient())
    response = asyncio.run(mcp_server.mcp.call_tool(
        "local_ai_status", {"adoption_signal": "bypassed"}
    ))

    assert response[1]["success"] is False
    assert "supported target_tool and safe target_action" in response[1]["error"]


def test_registered_mcp_dispatch_accepts_feature_enabled_batch_replace(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    from typing import Any, Literal

    import local_ai_hub.mcp_server as mcp_server
    from local_ai_hub.features import FeatureSet
    from local_ai_hub.operation_contracts import operation_tool_input_schema

    features = FeatureSet({"features": {"repo": True, "batch_replacement": True}})
    monkeypatch.setattr(mcp_server, "FEATURES", features)
    fresh_mcp = mcp_server.FastMCP("batch-replacement-test")
    calls: list[dict[str, Any]] = []

    def batch_tool(
        action: Literal["batch_replace"],
        edits: list[dict[str, Any]],
        dry_run: bool = False,
    ) -> dict[str, Any]:
        calls.append({"action": action, "edits": edits, "dry_run": dry_run})
        return {"success": True}

    fresh_mcp.tool(name="local_ai_repo")(batch_tool)
    registered_tool = fresh_mcp._tool_manager._tools["local_ai_repo"]
    registry_schema = operation_tool_input_schema("local_ai_repo", features)
    assert {"edits", "dry_run"} <= set(registry_schema["properties"])
    assert {"edits", "dry_run"} <= set(registered_tool.parameters["properties"])

    monkeypatch.setattr(mcp_server, "mcp", fresh_mcp)
    fresh_mcp.call_tool = mcp_server._compact_mcp_call_tool
    fresh_mcp._mcp_server.call_tool(validate_input=False)(mcp_server._compact_mcp_call_tool)
    arguments = {
        "action": "batch_replace",
        "edits": [{"path": "a.py", "old": "x", "new": "y"}],
        "dry_run": True,
    }

    response = asyncio.run(fresh_mcp.call_tool("local_ai_repo", arguments))

    assert response[1]["success"] is True
    assert calls == [{"action": "batch_replace", "edits": arguments["edits"], "dry_run": True}]


def test_registered_mcp_dispatch_validates_unknown_field_when_selector_omitted(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    import local_ai_hub.mcp_server as mcp_server

    calls = _stub_registered_mcp_tool(monkeypatch, "local_ai_status", {"success": True})
    response = asyncio.run(mcp_server.mcp.call_tool("local_ai_status", {"unexpected": "value"}))

    assert response[1]["status_code"] == 400
    assert "unexpected" in response[1]["error"]
    assert calls == []


def test_registered_mcp_dispatch_rejects_non_object_output_without_replaying_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    import local_ai_hub.mcp_server as mcp_server

    calls = _stub_registered_mcp_tool(monkeypatch, "local_ai_repo", "plain text")
    response = asyncio.run(mcp_server.mcp.call_tool("local_ai_repo", {"action": "search"}))

    assert response[1]["status_code"] == 500
    assert "output contract" in response[1]["error"]
    assert len(calls) == 1

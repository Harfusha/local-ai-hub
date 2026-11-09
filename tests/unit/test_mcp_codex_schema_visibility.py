"""Keep MCP argument fields visible to Codex while retaining JSON Schema rules."""

from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from local_ai_hub.features import FeatureSet
from local_ai_hub.operation_contracts import operation_tool_input_schema, validate_operation_call
from local_ai_hub import mcp_server


@pytest.mark.parametrize("tool", ["local_ai_repo", "local_ai_coord", "local_ai_task", "local_ai_artifact", "local_ai_work"])
def test_conditional_action_rules_do_not_hide_root_argument_types(tool):
    features = FeatureSet({"hardware": {"profile": "high"}})
    schema = operation_tool_input_schema(tool, features)
    assert schema["type"] == "object"
    assert "action" in schema["properties"]
    assert "allOf" not in schema
    assert schema["if"] == {}
    assert schema["then"]["allOf"]


@pytest.mark.parametrize("arguments, expected", [
    ({"action": "search", "query": "x", "limit": 2}, True),
    ({"action": "search", "query": "x", "paths": ["x"]}, False),
    ({"action": "search", "query": "x", "task": "irrelevant"}, False),
    ({"action": "context", "query": "x", "mode": "fast", "exclude_paths": ["x"]}, False),
])
def test_repo_action_constraints_remain_enforced(arguments, expected):
    schema = operation_tool_input_schema("local_ai_repo", FeatureSet({"hardware": {"profile": "high"}}))
    assert Draft202012Validator(schema).is_valid(arguments) is expected
    old_shape = deepcopy(schema)
    old_shape["allOf"] = old_shape.pop("then")["allOf"]
    old_shape.pop("if")
    assert Draft202012Validator(old_shape).is_valid(arguments) is expected


def test_registered_task_schema_keeps_async_id_scope_without_hiding_fields():
    schema = mcp_server._ALL_REGISTERED_TOOLS["local_ai_task"].parameters
    assert "allOf" not in schema
    assert "request_id" in schema["properties"]
    validator = Draft202012Validator(schema)
    assert not validator.is_valid({"action": "compress", "text": "x", "request_id": "id"})
    assert validator.is_valid({"action": "compress", "text": "x"})


def test_every_registered_tool_publishes_argument_properties_at_root():
    for name, tool in mcp_server._ALL_REGISTERED_TOOLS.items():
        if name.startswith("local_ai_"):
            assert tool.parameters.get("type") == "object", name
            assert tool.parameters.get("properties"), name
            assert "allOf" not in tool.parameters, name


def test_action_required_fields_are_visible_in_property_descriptions():
    features = FeatureSet({"hardware": {"profile": "high"}})
    repo = operation_tool_input_schema("local_ai_repo", features)
    coord = operation_tool_input_schema("local_ai_coord", features)
    assert "context" in repo["properties"]["query"]["description"]
    for name in ("root", "scope", "key", "value"):
        assert "memory_record" in coord["properties"][name]["description"]


def test_coord_scope_schema_names_canonical_values_and_empty_filter():
    schema = operation_tool_input_schema("local_ai_coord", FeatureSet({"hardware": {"profile": "high"}}))
    assert set(schema["properties"]["scope"]["enum"]) == {
        "", "global", "repository", "clone", "worktree", "branch", "task", "session"
    }


def test_checkpoint_action_advertises_and_requires_canonical_request_fields():
    features = FeatureSet({"hardware": {"profile": "high"}})
    schema = operation_tool_input_schema("local_ai_coord", features)
    for field in ("root", "task_id", "checkpoint"):
        assert "task_checkpoint" in schema["properties"][field]["description"]
    assert validate_operation_call("local_ai_coord", {"action": "task_checkpoint"}, features=features) is not None


def test_action_scoped_field_descriptions_show_available_actions():
    features = FeatureSet({"hardware": {"profile": "high"}})
    repo = operation_tool_input_schema("local_ai_repo", features)
    hint = repo["properties"]["path_hints"]["description"]
    assert "search" in hint and "context" in hint
    assert "adaptive" in hint
    coord = operation_tool_input_schema("local_ai_coord", features)
    assert "task_checkpoint" in coord["properties"]["checkpoint"]["description"]


@pytest.mark.parametrize("action", ["plan_get", "plan_validate"])
def test_plan_read_actions_advertise_and_require_plan_identity(action):
    features = FeatureSet({"hardware": {"profile": "high"}})
    schema = operation_tool_input_schema("local_ai_coord", features)
    assert action in schema["properties"]["plan_id"]["description"]
    error = validate_operation_call(
        "local_ai_coord", {"action": action, "root": str(Path.cwd())}, features=features,
    )
    assert error is not None and "plan_id" in error[1]


@pytest.mark.parametrize("action, required", [
    ("plan_create", {"root", "title"}),
    ("plan_update", {"root", "plan_id", "expected_revision"}),
    ("plan_task_edit", {"root", "plan_id", "task_id", "task_data", "expected_revision"}),
    ("plan_task_delete", {"root", "plan_id", "task_id", "expected_revision"}),
    ("plan_archive", {"root", "plan_id", "expected_revision"}),
    ("plan_bind_task", {"root", "task_id", "plan_id", "plan_task_id"}),
])
def test_plan_write_actions_advertise_sdk_required_fields(action, required):
    from local_ai_hub.operation_contracts import operation_contract

    features = FeatureSet({"hardware": {"profile": "high"}})
    metadata = operation_contract("local_ai_coord")["actions"][action]
    assert required <= set(metadata["required"])
    schema = operation_tool_input_schema("local_ai_coord", features)
    for field in required:
        assert action in schema["properties"][field]["description"]


def test_plan_task_edit_keeps_explicit_empty_patch_valid():
    features = FeatureSet({"hardware": {"profile": "high"}})
    args = {"action": "plan_task_edit", "root": str(Path.cwd()), "plan_id": "plan_existing",
            "task_id": "task_existing", "task_data": {}, "expected_revision": "revision"}
    assert validate_operation_call("local_ai_coord", args, features=features) is None
    assert Draft202012Validator(operation_tool_input_schema("local_ai_coord", features)).is_valid(args)


@pytest.mark.parametrize("explicit_id", [False, True])
def test_plan_create_allows_server_generated_id(explicit_id):
    features = FeatureSet({"hardware": {"profile": "high"}})
    args = {"action": "plan_create", "root": str(Path.cwd()), "title": "New plan"}
    if explicit_id:
        args["plan_id"] = ""
    assert validate_operation_call("local_ai_coord", args, features=features) is None
    assert Draft202012Validator(operation_tool_input_schema("local_ai_coord", features)).is_valid(args)


def test_receipt_fields_visible_and_passed_receipts_require_evidence():
    schema = operation_tool_input_schema("local_ai_coord")
    receipt = schema["properties"]["receipt"]
    assert receipt["type"] == "object"
    assert "allOf" not in receipt
    assert {"task_id", "criterion", "passed", "evidence_id"} <= set(receipt["properties"])
    validator = Draft202012Validator(receipt)
    assert validator.is_valid({"task_id": "task-1", "criterion": "tests", "passed": False})
    assert not validator.is_valid({"task_id": "task-1", "criterion": "tests", "passed": True})
    assert validator.is_valid({"task_id": "task-1", "criterion": "tests", "passed": True, "evidence_id": "E1"})


def test_registered_argument_shapes_have_no_type_hiding_composition():
    def visit(schema, path):
        if not isinstance(schema, dict):
            return
        assert not ("allOf" in schema and ("type" in schema or "properties" in schema)), path
        for key, value in schema.get("properties", {}).items():
            visit(value, f"{path}.{key}")
        if "items" in schema:
            visit(schema["items"], f"{path}[]")
        for keyword in ("oneOf", "anyOf"):
            for value in schema.get(keyword, []):
                visit(value, f"{path}.{keyword}")

    for name, tool in mcp_server._ALL_REGISTERED_TOOLS.items():
        if name.startswith("local_ai_"):
            visit(tool.parameters, name)


@pytest.mark.parametrize("tool, arguments, expected", [
    ("local_ai_artifact", {"action": "list", "artifact_id": "x"}, False),
    ("local_ai_artifact", {"action": "list"}, True),
    ("local_ai_coord", {"action": "memory_record", "root": "C:/repo", "scope": "repository", "key": "k"}, False),
    ("local_ai_coord", {"action": "memory_record", "root": "C:/repo", "scope": "repository", "key": "k", "value": "v"}, True),
])
def test_other_tool_action_requirements_remain_enforced(tool, arguments, expected):
    schema = operation_tool_input_schema(tool, FeatureSet({"hardware": {"profile": "high"}}))
    assert Draft202012Validator(schema).is_valid(arguments) is expected

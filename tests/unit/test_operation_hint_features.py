import pytest

from local_ai_hub.features import FeatureSet
from local_ai_hub.operation_contracts import operation_action_guide, operation_actions, operation_argument_hint, operation_parameters_schema


def test_coord_schema_documents_laya_scope_and_evidence_requirements():
    schema = operation_parameters_schema("local_ai_coord")
    description = schema["properties"]["laya_operation"]["description"]
    assert "canonical task/session identity" in description
    assert "authorized evidence provenance" in description
    assert "per-example consent receipts are not required" in description


@pytest.mark.parametrize("enabled", [False, True])
def test_hint_matches_active_feature_schema(enabled):
    features = FeatureSet({"hardware": {"profile": "high"}})
    features.search_summaries = enabled
    schema = operation_parameters_schema("local_ai_repo", features)
    hint = operation_argument_hint("local_ai_repo", "search", features)
    assert ("summarize_results" in schema["properties"]) is enabled
    assert ("summarize_results" in hint["allowed_arguments"]) is enabled


@pytest.mark.parametrize("enabled", [False, True])
def test_action_guide_matches_active_feature_schema(enabled):
    features = FeatureSet({"hardware": {"profile": "high"}})
    features.search_summaries = enabled
    guide = operation_action_guide("local_ai_repo", "search", features)
    assert guide["success"] is True
    assert ("summarize_results" in guide["input_schema"]["properties"]) is enabled


@pytest.mark.parametrize("enabled", [False, True])
def test_all_action_hints_never_advertise_fields_outside_tool_schema(enabled):
    features = FeatureSet({"hardware": {"profile": "high"}})
    features.search_summaries = enabled
    for tool in ("local_ai_status", "local_ai_repo", "local_ai_task", "local_ai_rag", "local_ai_coord", "local_ai_artifact", "local_ai_work"):
        properties = operation_parameters_schema(tool, features)["properties"]
        for action in operation_actions(tool, features):
            hint = operation_argument_hint(tool, action, features)
            assert set(hint.get("allowed_arguments", ())) <= set(properties), (tool, action)
            assert set(hint.get("required_arguments", ())) <= set(hint.get("allowed_arguments", ())), (tool, action)


@pytest.mark.parametrize("enabled", [False, True])
def test_all_action_guides_match_active_tool_schema(enabled):
    features = FeatureSet({"hardware": {"profile": "high"}})
    features.search_summaries = enabled
    for tool in ("local_ai_status", "local_ai_repo", "local_ai_task", "local_ai_rag", "local_ai_coord", "local_ai_artifact", "local_ai_work"):
        properties = operation_parameters_schema(tool, features)["properties"]
        for action in operation_actions(tool, features):
            guide = operation_action_guide(tool, action, features)
            assert guide["success"] is True, (tool, action)
            schema = guide["input_schema"]
            assert set(schema["properties"]) <= set(properties), (tool, action)
            assert set(schema.get("required", ())) <= set(schema["properties"]), (tool, action)

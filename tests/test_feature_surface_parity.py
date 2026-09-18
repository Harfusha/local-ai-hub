from pathlib import Path
import sys
import inspect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_ai_hub.features import FeatureSet
from local_ai_hub.generator import (
    generate_global_policy,
    generate_mcp_tool_schemas,
    generate_skill_markdown,
    generate_skill_references,
)
from local_ai_hub import mcp_server as local_ai_mcp


def _config(*, agent_os: bool = True, work_orchestrator: bool = False) -> dict:
    return {
        "features": {
            "agent_os": agent_os,
            "work_orchestrator": work_orchestrator,
            "tasks": True,
            "rag": True,
            "commands": True,
            "code_intelligence": True,
            "dashboard": True,
        },
        "server": {"auto_start_ollama": True},
        "commands": {"enabled": True},
        "coord": {"enabled": True},
        "work_orchestrator": {"enabled": work_orchestrator},
    }


def _actions(schema: dict) -> list[str]:
    return schema["parameters"]["properties"]["action"]["enum"]


def test_enabled_agent_os_and_tool_actions_are_discoverable():
    cfg = _config()
    features = FeatureSet.from_config(cfg)
    policy = generate_global_policy(cfg)
    skill = generate_skill_markdown(cfg)
    references = generate_skill_references(cfg)
    schemas = generate_mcp_tool_schemas(cfg)

    assert features.agent_os
    assert "Recipe — Durable execution" in policy
    assert "Create a task contract before edits" in skill
    assert "verify_completion" in skill
    assert "Agent OS trigger and lifecycle" in references["tools.md"]
    assert "Agent OS through `local_ai_coord`" in references["multi-agent.md"]
    assert "create an Agent OS task" in schemas["local_ai_coord"]["description"]
    for semantic_task in ("generation", "reasoning", "second opinion", "semantic compression"):
        assert semantic_task in policy.lower()
    assert "facts, symbols, diff and tests" in policy.lower()
    tools_reference = references["tools.md"].lower()
    workflows_reference = references["workflows.md"].lower()
    assert "semantic generation" in tools_reference
    assert "exact facts, symbols, diff and tests" in tools_reference
    assert "preserves one bounded local pass" in tools_reference
    assert 'local_ai_task(action="delegate")' in workflows_reference
    assert 'local_ai_task(action="explore")' in workflows_reference
    assert 'local_ai_task(action="reason")' in workflows_reference
    assert 'local_ai_task(action="review")' in workflows_reference
    assert 'local_ai_task(action="second_opinion")' in workflows_reference
    assert 'local_ai_task(action="compress")' in workflows_reference

    expected_actions = {
        "local_ai_repo": features.supported_repo_actions(),
        "local_ai_task": features.supported_task_actions(),
        "local_ai_rag": features.supported_rag_actions(),
        "local_ai_command": features.supported_command_actions(),
        "local_ai_coord": features.supported_coord_actions(),
    }
    for name, expected in expected_actions.items():
        assert _actions(schemas[name]) == expected
        assert all(action in schemas[name]["description"] for action in expected)

    task_properties = schemas["local_ai_task"]["parameters"]["properties"]
    assert {"prompt", "model", "format", "json_schema", "candidate_data", "evaluation_cohort", "job_id", "latency_budget_ms", "timeout_seconds", "extra_fields"}.issubset(task_properties)
    assert {"docset_index", "docset_search", "ingest_document", "ingest_diagram"}.issubset(_actions(schemas["local_ai_rag"]))
    assert {"contract", "checkpoint", "record", "tool_outcome", "target_scope"}.issubset(schemas["local_ai_coord"]["parameters"]["properties"])
    assert schemas["local_ai_artifact"]["parameters"]["required"] == ["artifact_id"]
    assert "id" not in schemas["local_ai_artifact"]["parameters"]["properties"]
    assert "agent_state" in schemas["local_ai_status"]["description"]
    assert "local_ai_work" not in schemas


def test_disabled_agent_os_is_omitted_from_generated_surfaces():
    cfg = _config(agent_os=False)
    features = FeatureSet.from_config(cfg)
    policy = generate_global_policy(cfg)
    skill = generate_skill_markdown(cfg)
    references = generate_skill_references(cfg)
    schemas = generate_mcp_tool_schemas(cfg)

    assert not features.agent_os
    assert "task_create" not in features.supported_coord_actions()
    assert "Agent OS" not in policy
    assert "Agent Operating System & Durable Execution" not in skill
    assert "Agent OS trigger and lifecycle" not in references["tools.md"]
    assert "Agent OS" not in references["multi-agent.md"]
    assert "Agent OS" not in schemas["local_ai_coord"]["description"]
    assert "task_create" not in _actions(schemas["local_ai_coord"])


def test_whole_task_tool_obeys_its_feature_gate():
    disabled = _config(work_orchestrator=False)
    enabled = _config(work_orchestrator=True)

    disabled_refs = generate_skill_references(disabled)
    disabled_schemas = generate_mcp_tool_schemas(disabled)
    enabled_refs = generate_skill_references(enabled)
    enabled_schemas = generate_mcp_tool_schemas(enabled)

    assert "local_ai_work" not in disabled_refs["tools.md"]
    assert "local_ai_work" not in disabled_refs["multi-agent.md"]
    assert "local_ai_work" not in disabled_schemas
    assert "local_ai_work" in enabled_refs["tools.md"]
    assert "local_ai_work" in enabled_refs["multi-agent.md"]
    assert "local_ai_work" in enabled_schemas


def test_guarded_context_extends_existing_repo_tool_without_duplicate_surface():
    parameters = inspect.signature(local_ai_mcp.local_ai_repo).parameters
    assert {
        "phase", "focus", "preload_profile", "changed_paths", "base", "staged",
        "task_id", "guarded", "since_hash", "approval", "override_reason", "token_budget",
    }.issubset(parameters)

    names = list(local_ai_mcp.mcp._tool_manager._tools)
    assert names.count("local_ai_repo") == 1
    assert not any(name in {"local_ai_context", "local_ai_context_pack"} for name in names)


def test_generated_repo_schema_declares_guarded_context_and_compact_controls():
    schema = generate_mcp_tool_schemas(_config())["local_ai_repo"]
    properties = schema["parameters"]["properties"]

    assert {
        "task", "task_id", "max_tokens", "token_budget", "workspace",
        "phase", "focus", "preload_profile", "guarded", "changed_paths",
        "since_hash", "approval", "override_reason", "max_response_tokens",
        "response_profile", "reuse_key", "extra_fields",
    }.issubset(properties)
    assert properties["focus"] == {"type": "array", "items": {"type": "string"}}
    assert properties["changed_paths"] == {"type": "array", "items": {"type": "string"}}
    assert properties["approval"]["type"] == ["boolean", "string"]

    guidance = schema["description"].lower()
    for phrase in (
        "default adaptive context pack",
        "planning, edit, review or test",
        "evidence ids",
        "reuse candidates first",
        "override_reason",
        "deterministic/indexed evidence is authoritative",
        "raw model/debug fields",
    ):
        assert phrase in guidance

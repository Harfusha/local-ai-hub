from local_ai_hub.features import FeatureSet
from local_ai_hub.generator import (
    generate_global_policy,
    generate_mcp_tool_schemas,
    generate_skill_markdown,
    generate_skill_references,
)


def config(*, agent_os: bool = True, work_orchestrator: bool = False) -> dict:
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


def actions(schema: dict) -> list[str]:
    return schema["parameters"]["properties"]["action"]["enum"]


def test_enabled_agent_os_is_discoverable_in_mcp_and_generated_instructions() -> None:
    cfg = config()
    features = FeatureSet.from_config(cfg)

    assert features.agent_os
    assert "task_create" in features.supported_coord_actions()
    assert "verify_completion" in features.supported_coord_actions()
    assert "- bounded health/cache/telemetry inspection (never poll): `local_ai_status`" in features.trigger_map_lines()
    assert any("multi-step" in line and "Agent OS" in line for line in features.trigger_map_lines())

    policy = generate_global_policy(cfg)
    skill = generate_skill_markdown(cfg)
    references = generate_skill_references(cfg)
    schemas = generate_mcp_tool_schemas(cfg)

    assert "Recipe — Durable execution" in policy
    assert "Create a task contract before edits" in skill
    assert "verify_completion" in skill
    assert "Agent OS trigger and lifecycle" in references["tools.md"]
    assert "Agent OS through `local_ai_coord`" in references["multi-agent.md"]
    assert "create an Agent OS task" in schemas["local_ai_coord"]["description"]
    assert set(features.supported_coord_actions()).issubset(actions(schemas["local_ai_coord"]))
    assert "local_ai_work" not in schemas
    assert "local_ai_work" not in skill
    assert "local_ai_work" not in references["tools.md"]


def test_disabled_agent_os_is_omitted_from_generated_surfaces() -> None:
    cfg = config(agent_os=False)
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
    assert "task_create" not in actions(schemas["local_ai_coord"])
    assert "local_ai_work" not in schemas
    assert "local_ai_work" not in skill


def test_whole_task_tool_is_emitted_only_when_its_feature_gate_is_on() -> None:
    disabled = config(work_orchestrator=False)
    enabled = config(work_orchestrator=True)

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


def test_enabled_action_schemas_and_specialized_routes_stay_in_parity() -> None:
    cfg = config()
    features = FeatureSet.from_config(cfg)
    schemas = generate_mcp_tool_schemas(cfg)
    policy = generate_global_policy(cfg)
    references = generate_skill_references(cfg)

    expected_actions = {
        "local_ai_repo": features.supported_repo_actions(),
        "local_ai_task": features.supported_task_actions(),
        "local_ai_rag": features.supported_rag_actions(),
        "local_ai_command": features.supported_command_actions(),
        "local_ai_coord": features.supported_coord_actions(),
    }
    for tool_name, expected in expected_actions.items():
        assert actions(schemas[tool_name]) == expected
        assert all(action in schemas[tool_name]["description"] for action in expected)

    task_properties = schemas["local_ai_task"]["parameters"]["properties"]
    assert {"prompt", "model", "format", "json_schema", "candidate_data", "evaluation_cohort", "job_id", "latency_budget_ms", "timeout_seconds", "extra_fields"}.issubset(task_properties)
    assert {"docset_index", "docset_search", "ingest_document", "ingest_diagram"}.issubset(actions(schemas["local_ai_rag"]))
    assert {"contract", "checkpoint", "record", "tool_outcome", "target_scope"}.issubset(schemas["local_ai_coord"]["parameters"]["properties"])
    expected_parameters = {
        "local_ai_repo": {"diff", "evidence", "receipt", "workspace", "extra_fields"},
        "local_ai_rag": {"workspace", "extra_fields"},
        "local_ai_command": {"cwd", "auto_fix", "max_attempts", "rollback_on_failure", "snapshot", "force", "extra_fields"},
        "local_ai_coord": {"root", "contract", "checkpoint", "record", "tool_outcome", "target_scope", "ttl_seconds", "lease_id", "fingerprint"},
        "local_ai_status": {"detail", "scope", "extra_fields"},
    }
    for tool_name, expected in expected_parameters.items():
        assert expected.issubset(schemas[tool_name]["parameters"]["properties"])

    artifact_schema = schemas["local_ai_artifact"]["parameters"]
    assert artifact_schema["required"] == ["artifact_id"]
    assert {"artifact_id", "max_chars", "offset", "extra_fields"}.issubset(artifact_schema["properties"])
    assert "id" not in artifact_schema["properties"]
    status_schema = schemas["local_ai_status"]
    assert "agent_state" in status_schema["parameters"]["properties"]["detail"]["enum"]
    assert "agent_state" in status_schema["description"]

    routes = "\n".join(features.specialized_trigger_lines())
    assert "vision" in routes and "transcribe" in routes
    assert "docset" in routes and "diagram" in routes
    assert "repair" in routes and "mock" in routes
    assert "/dashboard" in routes
    assert "local_ai_status(detail=\"agent_state\")" in routes
    assert "agent_state" in references["tools.md"]
    assert "image understanding" in policy
    assert "evaluation and drift checks" in references["tools.md"]
    assert "local_ai_work" not in schemas

from pathlib import Path

import pytest

from local_ai_hub.generator import (
    generate_antigravity_instructions,
    generate_global_policy,
    generate_mcp_tool_schemas,
    generate_skill_markdown,
    generate_skill_references,
    generate_token_economy_policy,
)


ROOT = Path(__file__).resolve().parents[1]


def test_generated_repository_rules_do_not_recommend_removed_command_tool():
    source = (ROOT / "src/local_ai_hub/deterministic.py").read_text(encoding="utf-8")
    assert "local_ai_command" not in source


def test_current_api_coverage_does_not_advertise_command_routes():
    coverage = (ROOT / "docs/API_COVERAGE.md").read_text(encoding="utf-8")
    assert "/api/command" not in coverage
    assert "local_ai_command" not in coverage


@pytest.mark.parametrize("generate", [
    generate_antigravity_instructions,
    generate_global_policy,
    generate_skill_markdown,
    generate_skill_references,
    generate_token_economy_policy,
])
def test_generated_agent_instructions_use_available_tools(generate):
    output = str(generate({}))
    assert "local_ai_command" not in output
    assert "/api/command" not in output


def test_generated_mcp_catalog_excludes_removed_command_tool():
    assert "local_ai_command" not in generate_mcp_tool_schemas({})


def test_generated_status_schema_matches_compact_runtime_contract():
    schema = generate_mcp_tool_schemas({})["local_ai_status"]
    properties = schema["parameters"]["properties"]
    assert set(properties["detail"]["enum"]) == {"brief", "models"}
    assert not {"scope", "adoption_signal", "target_tool", "target_action"} & properties.keys()
    assert "agent_state" not in schema["description"]


def test_active_sources_and_skills_do_not_contain_removed_command_tool():
    assert "local_ai_command" not in (ROOT / "skills/tool-orchestration/SKILL.md").read_text(encoding="utf-8")
    assert "local_ai_command" not in (ROOT / "skills/local-ai-orchestrator/agents/openai.yaml").read_text(encoding="utf-8")
    assert "local_ai_command" not in (ROOT / "src/local_ai_hub/token_accounting.py").read_text(encoding="utf-8")
    assert "local_ai_command" not in (ROOT / "src/local_ai_hub/token_economy.py").read_text(encoding="utf-8")
    assert "local_ai_command" not in (ROOT / "tools/setup.py").read_text(encoding="utf-8")
    assert "local_ai_command" not in (ROOT / "config.toml.example").read_text(encoding="utf-8")

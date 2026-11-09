"""Generated Agent OS calls must agree with the active MCP contract."""

import ast
import re
from pathlib import Path

import pytest

from local_ai_hub.features import FeatureSet
from local_ai_hub.generator import context_economy_contract, generate_skill_markdown
from local_ai_hub.operation_contracts import validate_operation_call


def test_agent_os_example_calls_match_mcp_contract():
    cfg = {"hardware": {"profile": "high"}}
    content = generate_skill_markdown(cfg)
    section = content.split("## Agent Operating System & Durable Execution", 1)[1].split("### Public contract notes", 1)[0]
    examples = re.findall(r'`(local_ai_coord\(action="[^"]+"[^`]*\))`', section)
    assert len(examples) >= 8
    for example in examples:
        call = ast.parse(example, mode="eval").body
        arguments = {keyword.arg: ast.literal_eval(keyword.value) for keyword in call.keywords}
        assert "root" in arguments, example
        arguments["root"] = str(Path.cwd().resolve())
        assert validate_operation_call("local_ai_coord", arguments, features=FeatureSet.from_config(cfg)) is None, example


@pytest.mark.parametrize("enabled", [False, True])
def test_batch_guidance_only_mentions_an_exposed_action(enabled):
    cfg = {"hardware": {"profile": "high"}, "features": {"local_semantic_analysis": enabled}}
    features = FeatureSet.from_config(cfg)
    assert ("local_ai_task(action=\"batch\")" in context_economy_contract(cfg)) == ("batch" in features.supported_task_actions())


def test_budget_guidance_avoids_assuming_128_fits_every_response():
    guidance = context_economy_contract({"hardware": {"profile": "high"}})
    assert "omit `max_response_tokens`" in guidance
    assert "task responses" in guidance


@pytest.mark.parametrize("enabled", [False, True])
def test_advisory_profile_example_requires_delegate_action(enabled):
    cfg = {"hardware": {"profile": "high"}, "features": {"local_semantic_analysis": enabled}}
    features = FeatureSet.from_config(cfg)
    content = generate_skill_markdown(cfg)
    assert ("## Local advisory subagents" in content) == ("delegate" in features.supported_task_actions())

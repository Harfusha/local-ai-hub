from pathlib import Path

from local_ai_hub.features import FeatureSet
from local_ai_hub.generator import context_pack_guidance, generate_global_policy, generate_mcp_tool_schemas


def test_context_guidance_reuses_fresh_evidence_before_adaptive_retrieval() -> None:
    guidance = context_pack_guidance()

    assert "Reuse fresh sufficient repository evidence" in guidance
    assert "bounded indexed/source lookup directly" in guidance
    assert 'action="context", mode="adaptive"' in guidance
    assert "root is unindexed or its evidence is stale" in guidance
    assert "CALL `local_ai_repo(action=\"context\")` FIRST" not in guidance
    assert "preprocess once" not in guidance
    assert "context first for quality" not in generate_mcp_tool_schemas({})["local_ai_repo"]["description"]


def test_generated_policy_configures_and_registers_repository_on_first_contact() -> None:
    features = FeatureSet({"features": {"repo": True, "preprocessing": True}})
    recipe = "\n".join(features.recipe_lines())
    policy = generate_global_policy({})

    expected = (
        "on first work in a stable root, inspect project config and register with one idempotent preprocess call; "
        "use bounded indexed/source lookup for exact file or symbol facts and adaptive context when evidence is insufficient"
    )
    assert expected in recipe
    assert expected in policy
    assert "CALL `local_ai_repo(action=\"context\")` FIRST" not in policy
    assert "never force-refresh or poll preprocessing" in recipe
    assert "`.local-ai.toml`" in policy
    assert "pinned documentation" in policy
    assert "call the hub first" not in policy


def test_mcp_repository_descriptions_have_no_mandatory_context_gate() -> None:
    source_path = Path(__file__).resolve().parents[2] / "src" / "local_ai_hub" / "mcp_server.py"
    source = source_path.read_text(encoding="utf-8")

    assert "Call this before broad repository reads/searches" not in source
    assert "Call this before broad repository reads" not in source
    assert "MANDATORY GATE" not in source
    assert "Preprocess once per stable absolute root" not in source
    assert "Reuse fresh evidence and bounded indexed/source lookup for exact facts" in source


def test_orchestration_skill_reuses_fresh_evidence_before_context() -> None:
    skills_root = Path(__file__).resolve().parents[2] / "skills"
    tool_orchestration = (skills_root / "tool-orchestration" / "SKILL.md").read_text(encoding="utf-8")
    orchestrator_agent = (skills_root / "local-ai-orchestrator" / "agents" / "openai.yaml").read_text(encoding="utf-8")

    assert "Reuse fresh repository evidence" in tool_orchestration
    assert "mandatory first repository step" not in tool_orchestration
    assert "`.local-ai.toml`" in tool_orchestration
    assert "evidence-backed exclusions" in tool_orchestration
    assert "Reuse fresh repository evidence" in orchestrator_agent
    assert "inspect project config" in orchestrator_agent
    assert "preprocess once" in orchestrator_agent

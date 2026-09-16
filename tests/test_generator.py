"""tests/test_generator.py - Unit tests for dynamic generator and feature toggles."""
from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TOOLS = ROOT / "tools"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from local_ai_hub.generator import (
    generate_skill_markdown,
    generate_skill_references,
    generate_global_policy,
    generate_mcp_tool_schemas,
    write_all_generated,
)
from local_ai_hub.features import FeatureSet


class TestSkillGeneration:
    def test_default_skill_contains_all_core_components(self):
        skill = generate_skill_markdown({})
        assert "local_ai_repo" in skill
        assert "local_ai_command" in skill
        assert "local_ai_task" in skill
        assert "local_ai_rag" in skill
        assert "local_ai_coord" in skill
        assert "local_ai_artifact" in skill
        assert "local_ai_work" in skill
        assert "Agent Operating System & Durable Execution" in skill
        assert "Ollama advisory subagents" in skill

    def test_skill_without_rag(self):
        cfg = {"features": {"rag": False}}
        skill = generate_skill_markdown(cfg)
        assert "local_ai_rag" not in skill
        assert "Recipe — Retrieve" not in skill

    def test_skill_without_commands(self):
        cfg = {"features": {"commands": False}}
        skill = generate_skill_markdown(cfg)
        assert "local_ai_command" not in skill
        assert "route repeatable commands through `local_ai_command`" not in skill
        assert "Validate natively" in skill or "run validation commands natively" in skill or "bounded native test/lint" in skill

    def test_skill_without_tasks_or_models(self):
        cfg = {"features": {"tasks": False}}
        skill = generate_skill_markdown(cfg)
        assert "local_ai_task" not in skill
        assert "Ollama advisory subagents" not in skill
        assert "Local model inference is disabled" in skill

    def test_skill_with_custom_models(self):
        cfg = {
            "models": {
                "fast_code": "deepseek-coder:6.7b",
                "heavy_code": "deepseek-coder:33b",
            }
        }
        skill = generate_skill_markdown(cfg)
        assert "deepseek-coder:6.7b" in skill
        assert "deepseek-coder:33b" in skill
        assert "qwen2.5-coder:7b" not in skill

    def test_default_model_tiers_match_generated_routing_policy(self):
        cfg = tomllib.loads((ROOT / "defaults.toml").read_text(encoding="utf-8"))
        features = FeatureSet(cfg)
        skill = generate_skill_markdown(cfg)
        policy = generate_global_policy(cfg)

        assert features.background_model == "qwen2.5-coder:0.5b"
        assert features.fast_model == "qwen2.5-coder:1.5b"
        assert features.general_model == "qwen2.5-coder:3b"
        assert features.smart_model == "qwen2.5-coder:3b"
        assert features.reasoning_model == "qwen2.5-coder:7b"
        for generated in (skill, policy):
            assert "qwen2.5-coder:1.5b` only for quick/simple requests" in generated
            assert "qwen2.5-coder:3b` for ordinary tasks" in generated
            assert "qwen2.5-coder:7b` for the hardest reasoning" in generated
            assert "for ordinary local reasoning" not in generated

    def test_general_model_falls_back_to_smart_tier(self):
        features = FeatureSet({"models": {"fast_code": "fast", "heavy_code": "smart"}})
        assert features.general_model == "smart"

    def test_skill_without_coord(self):
        cfg = {"features": {"coord": False}}
        skill = generate_skill_markdown(cfg)
        assert "local_ai_coord" not in skill
        assert "claim `local_ai_coord` leases" not in skill
        assert "Agent Operating System & Durable Execution" not in skill

    def test_skill_without_agent_os(self):
        cfg = {"features": {"agent_os": False}}
        skill = generate_skill_markdown(cfg)
        assert "local_ai_coord" in skill  # leases still on
        assert "Agent Operating System & Durable Execution" not in skill

    def test_skill_without_preprocessing(self):
        cfg = {"features": {"preprocessing": False}}
        skill = generate_skill_markdown(cfg)
        assert 'action="preprocess"' not in skill


class TestSkillReferences:
    def test_references_default(self):
        refs = generate_skill_references({})
        assert "tools.md" in refs
        assert "workflows.md" in refs
        assert "multi-agent.md" in refs
        assert "preprocessing.md" in refs
        assert "local_ai_repo" in refs["tools.md"]

    def test_references_omits_disabled_tools(self):
        refs = generate_skill_references({
            "features": {"rag": False, "commands": False, "preprocessing": False}
        })
        assert "local_ai_rag" not in refs["tools.md"]
        assert "local_ai_command" not in refs["tools.md"]
        assert "preprocessing.md" not in refs


class TestGlobalPolicyGeneration:
    def test_policy_markers_and_content(self):
        policy = generate_global_policy({})
        assert "<!-- BEGIN LOCAL AI HUB TOOL POLICY -->" in policy
        assert "<!-- END LOCAL AI HUB TOOL POLICY -->" in policy
        assert "local_ai_repo" in policy
        assert "local_ai_command" in policy
        assert "local_ai_task" in policy
        assert "local_ai_rag" in policy

    def test_policy_without_commands_and_rag(self):
        policy = generate_global_policy({"features": {"commands": False, "rag": False}})
        assert "local_ai_command" not in policy
        assert "local_ai_rag" not in policy
        assert "local_ai_repo" in policy

    def test_policy_preserves_batch_replace_safety_rules(self):
        policy = generate_global_policy({})
        assert "batch_replace" in policy
        assert "dry_run=true" in policy
        assert "exact-match once" in policy
        assert "rolls back write failures" in policy
        assert "no auto-commit" in policy


class TestMcpSchemasGeneration:
    def test_default_schemas_contain_all_tools(self):
        schemas = generate_mcp_tool_schemas({})
        assert set(schemas.keys()) == {
            "local_ai_status", "local_ai_repo", "local_ai_task", "local_ai_rag",
            "local_ai_command", "local_ai_coord", "local_ai_artifact", "local_ai_work",
        }

    def test_schemas_omit_disabled_tools(self):
        schemas = generate_mcp_tool_schemas({"features": {"rag": False, "tasks": False}})
        assert "local_ai_rag" not in schemas
        assert "local_ai_task" not in schemas
        assert "local_ai_repo" in schemas

    def test_repo_schema_actions_dynamically_filtered(self):
        schemas_full = generate_mcp_tool_schemas({})
        repo_actions_full = schemas_full["local_ai_repo"]["parameters"]["properties"]["action"]["enum"]
        assert "semantic" in repo_actions_full
        assert "graph" in repo_actions_full
        assert "preprocess" in repo_actions_full
        assert "verify_receipt" in repo_actions_full

        schemas_trimmed = generate_mcp_tool_schemas({
            "code_intelligence": {"enabled": False},
            "features": {"preprocessing": False, "agent_os": False},
        })
        repo_actions_trimmed = schemas_trimmed["local_ai_repo"]["parameters"]["properties"]["action"]["enum"]
        assert "semantic" not in repo_actions_trimmed
        assert "graph" not in repo_actions_trimmed
        assert "preprocess" not in repo_actions_trimmed
        assert "verify_receipt" not in repo_actions_trimmed
        assert "solve" in repo_actions_trimmed

    def test_repo_schema_exposes_batch_replace_edits_and_dry_run(self):
        properties = generate_mcp_tool_schemas({})["local_ai_repo"]["parameters"]["properties"]
        assert properties["edits"] == {"type": "array", "items": {"type": "object"}}
        assert properties["dry_run"] == {"type": "boolean", "default": False}


class TestWriteAllGenerated:
    def test_writes_expected_tree(self, tmp_path: Path):
        cfg = {
            "models": {"fast_code": "test-model:7b"},
            "features": {"rag": False},
        }
        res = write_all_generated(cfg, tmp_path)
        assert len(res["skill"]) >= 4
        assert len(res["instructions"]) >= 1
        assert len(res["mcp"]) == 2
        assert len(res["schemas"]) >= 5

        skill_md = (tmp_path / "skills" / "local-ai-orchestrator" / "SKILL.md").read_text(encoding="utf-8")
        assert "test-model:7b" in skill_md
        assert "local_ai_rag" not in skill_md

        assert not (tmp_path / "generated" / "schemas" / "local_ai_rag.json").exists()
        assert (tmp_path / "generated" / "schemas" / "local_ai_repo.json").exists()


class TestMcpServerDynamicRegistration:
    def test_mcp_server_unregisters_disabled_tools(self, monkeypatch):
        import local_ai_hub.mcp_server as mcp_mod

        # Verify disabled_tools logic
        fs_no_rag = FeatureSet({"features": {"rag": False, "commands": False}})
        assert "local_ai_rag" in fs_no_rag.disabled_tools
        assert "local_ai_command" in fs_no_rag.disabled_tools
        assert "local_ai_repo" in fs_no_rag.enabled_tools


class TestCliEntrypoints:
    def test_generator_module_main(self, tmp_path: Path):
        from local_ai_hub.generator import main as gen_main
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text("[features]\nrag = false\n", encoding="utf-8")
        out_dir = tmp_path / "out"

        code = gen_main(["--config", str(cfg_file), "--output-dir", str(out_dir)])
        assert code == 0
        assert (out_dir / "generated" / "schemas" / "local_ai_repo.json").exists()
        assert not (out_dir / "generated" / "schemas" / "local_ai_rag.json").exists()

    def test_package_main_generate(self, tmp_path: Path):
        from local_ai_hub.__main__ import main as pkg_main
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text("[features]\ncommands = false\n", encoding="utf-8")
        out_dir = tmp_path / "out2"

        code = pkg_main(["--config", str(cfg_file), "--generate", "--output-dir", str(out_dir)])
        assert code == 0
        assert (out_dir / "generated" / "schemas" / "local_ai_repo.json").exists()
        assert not (out_dir / "generated" / "schemas" / "local_ai_command.json").exists()


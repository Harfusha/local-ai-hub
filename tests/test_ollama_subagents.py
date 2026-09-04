from __future__ import annotations

from pathlib import Path
import tomllib
from types import SimpleNamespace

import pytest

from local_ai_hub.ollama_subagents import OllamaSubagentCatalog
from local_ai_hub.tool_agent import TOOLS, ToolAwareLocalAgent
from local_ai_hub.config import ConfigError, validate_config
from local_ai_hub.services import LocalAIServices


def _catalog(extra: dict | None = None) -> OllamaSubagentCatalog:
    config = {
        "models": {"fast_code": "qwen2.5-coder:7b"},
        "ollama_subagents": {
            "enabled": True,
            "profiles": {
                "qwen-explorer": {"model": "qwen2.5-coder:7b", "role": "explorer"},
                "qwen-drafter": {"model": "qwen2.5-coder:7b", "role": "drafter"},
                "qwen-critic": {"model": "qwen2.5-coder:7b", "role": "critic"},
            },
        },
    }
    if extra:
        config["ollama_subagents"].update(extra)
    return OllamaSubagentCatalog(config)


def test_default_profiles_are_advisory_and_use_fast_model() -> None:
    catalog = _catalog()

    assert catalog.resolve("qwen-explorer").role == "explorer"
    assert catalog.resolve("qwen-drafter").model == "qwen2.5-coder:7b"
    assert catalog.resolve("qwen-critic").advisory_only is True


def test_aliases_and_unknown_profiles_are_deterministic() -> None:
    catalog = _catalog()

    assert catalog.resolve("explorer").name == "qwen-explorer"
    with pytest.raises(ValueError, match="qwen-explorer"):
        catalog.resolve("writer")


def test_model_resolution_does_not_select_unavailable_model() -> None:
    catalog = _catalog({"profiles": {"qwen-explorer": {"model": "missing:99b"}}})

    resolved = catalog.resolve("qwen-explorer", available_models={"qwen2.5-coder:7b"})

    assert resolved.model == "qwen2.5-coder:7b"
    assert resolved.model_fallback is True


def test_profile_tool_allowlist_excludes_mutation_and_commands() -> None:
    catalog = _catalog()

    for name in ("qwen-explorer", "qwen-drafter", "qwen-critic"):
        profile = catalog.resolve(name)
        assert "file_slice" in profile.tools
        assert "local_ai_command" not in profile.tools
        assert "write_file" not in profile.tools
        assert profile.advisory_only is True


def test_system_contract_requires_hub_tools_advisory_mode_and_matching_language() -> None:
    contract = _catalog().system_contract(_catalog().resolve("qwen-explorer"), "Najdi příčinu chyby")

    assert "Local AI Hub" in contract
    assert "ADVISORY_ONLY" in contract
    assert "same language as TASK" in contract
    assert "deterministic facts" in contract


def test_profile_docs_describe_hub_tools_and_advisory_boundary() -> None:
    text = Path("skills/local-ai-orchestrator/SKILL.md").read_text(encoding="utf-8")

    assert "qwen-explorer" in text
    assert "qwen-drafter" in text
    assert "qwen-critic" in text
    assert "advisory" in text.lower()
    assert "local_ai_repo" in text
    assert "local_ai_artifact" in text


def test_default_config_declares_three_advisory_profiles() -> None:
    with Path("src/local_ai_hub/defaults.toml").open("rb") as handle:
        config = tomllib.load(handle)

    profiles = config["ollama_subagents"]["profiles"]
    assert set(profiles) == {"qwen-explorer", "qwen-drafter", "qwen-critic"}
    assert all(profile["model"] == "qwen2.5-coder:7b" for profile in profiles.values())


def test_profile_limits_are_validated_at_config_load() -> None:
    with pytest.raises(ConfigError, match="max_steps"):
        validate_config({
            "ollama_subagents": {
                "profiles": {"qwen-explorer": {"max_steps": 0}},
            },
        })


def test_profile_tool_loop_uses_only_hub_read_tools() -> None:
    agent = object.__new__(ToolAwareLocalAgent)
    profile = _catalog().resolve("qwen-explorer")

    schemas = agent._tools_for_profile(profile)
    schema_names = {schema["function"]["name"] for schema in schemas}

    assert schema_names <= set(profile.tools)
    assert "local_ai_command" not in schema_names
    assert "write_file" not in schema_names
    assert {schema["function"]["name"] for schema in TOOLS} >= schema_names


def test_profile_system_contract_detects_czech_and_marks_advisory_only() -> None:
    catalog = _catalog()
    profile = catalog.resolve("qwen-drafter")

    contract = catalog.system_contract(profile, "Navrhni opravu chyby v souboru")

    assert "Detected task language: cs" in contract
    assert "ADVISORY_ONLY" in contract


def test_run_profile_routes_resolved_profile_and_metadata() -> None:
    agent = object.__new__(ToolAwareLocalAgent)
    agent.profile_catalog = _catalog()
    agent.services = SimpleNamespace(runtime=SimpleNamespace(installed_models=lambda: ["qwen2.5-coder:7b"]))
    captured = {}

    def fake_run(model, role, task, root, tenant, max_tokens, priority, **kwargs):
        captured.update({"model": model, "role": role, "task": task, "root": root, "tenant": tenant, "max_tokens": max_tokens, "profile": kwargs["profile"]})
        return {"success": True, "text": "návrh"}

    agent.run = fake_run
    result = agent.run_profile("drafter", "Navrhni opravu", "C:\\repo", "tenant-a")

    assert captured["model"] == "qwen2.5-coder:7b"
    assert captured["role"] == "drafter"
    assert captured["profile"].name == "qwen-drafter"
    assert result["profile"] == "qwen-drafter"
    assert result["language"] == "cs"
    assert result["advisory_only"] is True


def test_run_profile_rejects_unavailable_model_without_fallback() -> None:
    config = {
        "ollama_subagents": {
            "enabled": True,
            "profiles": {
                "qwen-explorer": {
                    "model": "missing-model",
                    "role": "explorer",
                },
            },
        },
        "models": {"fast_code": "also-missing"},
    }
    agent = object.__new__(ToolAwareLocalAgent)
    agent.enabled = True
    agent.profile_catalog = OllamaSubagentCatalog(config)
    agent.services = SimpleNamespace(runtime=SimpleNamespace(installed_models=lambda: ["other-model"]))
    agent.run = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("run must not start"))

    result = agent.run_profile("qwen-explorer", "inspect", "C:\\repo", "tenant")

    assert result["success"] is False
    assert result["unsupported"] is True
    assert "unavailable" in result["error"]


def test_services_route_repo_profile_to_read_only_tool_agent() -> None:
    services = object.__new__(LocalAIServices)
    services.profile_catalog = _catalog()
    services.runtime = SimpleNamespace(installed_models=lambda: ["qwen2.5-coder:7b"])
    calls = {}

    class Agent:
        def run_profile(self, *args, **kwargs):
            calls["args"] = args
            calls["kwargs"] = kwargs
            return {"success": True, "profile": args[0], "advisory_only": True}

    services.tool_agent = Agent()
    result = services.delegate_profile({"profile": "qwen-explorer", "root": "C:\\repo", "task": "Najdi vstup"}, "tenant-a")

    assert result["success"] is True
    assert calls["args"][:4] == ("qwen-explorer", "Najdi vstup", "C:\\repo", "tenant-a")

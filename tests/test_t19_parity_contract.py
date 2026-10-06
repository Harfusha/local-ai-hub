from __future__ import annotations

import tomllib
from pathlib import Path

from local_ai_hub.generator import (
    T19_RUNTIME_PARITY_CONTRACT,
    T21_HANDOFF_CONTRACT,
    generate_global_policy,
    generate_skill_markdown,
    write_all_generated,
)
from local_ai_hub.hardware import profile_overrides

ROOT = Path(__file__).resolve().parents[1]


def test_change_verification_workflow_records_receipt_before_completion():
    sdk = (ROOT / "docs" / "PYTHON_SDK.md").read_text(encoding="utf-8")
    row = next(line for line in sdk.splitlines() if line.startswith("| Verify"))

    assert "verify_receipt" in row
    assert "verify_completion" in row


def test_current_runtime_contract_matches_between_canonical_prompts(tmp_path: Path):
    install = (ROOT / "docs" / "INSTALL_PROMPT.md").read_text(encoding="utf-8")
    update = (ROOT / "docs" / "UPDATE_PROMPT.md").read_text(encoding="utf-8")
    sdk = (ROOT / "docs" / "PYTHON_SDK.md").read_text(encoding="utf-8")
    config = {"models": {"fast_code": "qwen2.5-coder:7b"}}
    generated = generate_skill_markdown(config)
    write_all_generated(config, tmp_path)
    written_skill = (tmp_path / "skills" / "local-ai-orchestrator" / "SKILL.md").read_text(encoding="utf-8")

    def current_contract(prompt: str) -> str:
        start = prompt.index("### Adaptive context and supported capabilities")
        end = prompt.index("### Document and diagram ingestion", start)
        return prompt[start:end]

    install_contract = current_contract(install)
    update_contract = current_contract(update)
    assert install_contract == update_contract
    expected = (
        "Feature-specific schemas expose only enabled tools/actions and applicable fields",
        "HTTP `/api/context/pack` accepts `path_hints`, `directory_hints`, `exclude_paths`, and `force_include_paths` in `adaptive` mode and validates lists. T14 owns that contract.",
        "Inspect installed generated schemas before using public wire fields.",
        "Overlay order is defaults, primary-worktree `.local-ai.toml`",
        "`required_commands` is not a global switch",
        "Cross-worktree Agent OS memory sharing remains HOLD",
        "`/api/context/pack`",
        "Operational modes are `active`, `gaming`, and `maintenance`",
        "`maintenance` must reject every agent MCP/API action before Agent OS database access",
        "offline `mode` and `status` read that persisted state",
        "repository-scoped memory requires provenance tied to the trusted project root",
        "`state_data.memory_audit`",
        "CodeGraph remains optional external standalone tooling outside Hub setup/runtime",
        "If Hub is unavailable, make one bounded health/retry attempt, then use one native fallback",
    )
    assert all(item in install_contract for item in expected)
    assert T19_RUNTIME_PARITY_CONTRACT in generated
    assert T19_RUNTIME_PARITY_CONTRACT in written_skill
    assert "CodeGraphContext" not in sdk
    assert "pip install \"codegraphcontext" not in install + update
    assert T21_HANDOFF_CONTRACT in generated
    assert T21_HANDOFF_CONTRACT not in install_contract


def test_profile_routing_summary_matches_between_canonical_prompts():
    install = (ROOT / "docs" / "INSTALL_PROMPT.md").read_text(encoding="utf-8")
    update = (ROOT / "docs" / "UPDATE_PROMPT.md").read_text(encoding="utf-8")
    install_routing = next(
        line for line in install.splitlines()
        if line.startswith("Local model routing starts")
    )
    update_routing = next(
        line for line in update.splitlines()
        if line.startswith("Local model routing starts")
    )

    assert install_routing == update_routing
    for profile in ("integrated", "balanced", "high", "max"):
        models = profile_overrides(profile)["models"]
        route_keys = ("background_code", "fast_code", "general", "heavy_code", "reasoning", "vision")
        assert all(models[key] in install_routing for key in route_keys), profile
    resolved_routes = (
        "Model routes above are resolved from active config. Keep hard and extreme reasoning "
        "as distinct tiers; see `docs/MODEL_CAPABILITIES.md` for the full matrix."
    )
    assert resolved_routes not in install
    assert "Profile overrides: high raises general/reasoning/vision routes to 9b" not in install
    default_config = tomllib.loads(
        (ROOT / "src" / "local_ai_hub" / "defaults.toml").read_text(encoding="utf-8")
    )
    default_config["llama_cpp"]["mode"] = "on"
    assert resolved_routes in generate_global_policy(default_config)


def test_generated_policy_routes_match_each_supported_hardware_profile():
    for profile in ("integrated", "balanced", "high", "max"):
        models = profile_overrides(profile)["models"]
        config = {
            "server": {"auto_start_ollama": True},
            "models": models,
        }

        generated = generate_skill_markdown(config)
        expected_tiers = (
            f"- **Tiered local models:** `{models['background_code']}` for preprocessing, "
            f"`{models['fast_code']}` for quick/simple requests, "
            f"`{models['general']}` for ordinary tasks, "
            f"`{models['heavy_code']}` for more involved work, and "
            f"`{models['reasoning']}` for the hardest or highest-risk reasoning."
        )

        assert expected_tiers in generated, profile
        assert f"`{models['vision']}`" in generated, profile

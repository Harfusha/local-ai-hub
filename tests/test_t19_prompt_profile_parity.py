from pathlib import Path

from local_ai_hub.hardware import profile_overrides


ROOT = Path(__file__).resolve().parents[1]


def test_prompt_role_matrix_matches_hardware_profiles() -> None:
    install = (ROOT / "docs" / "INSTALL_PROMPT.md").read_text(encoding="utf-8")
    update = (ROOT / "docs" / "UPDATE_PROMPT.md").read_text(encoding="utf-8")
    model_doc = (ROOT / "docs" / "MODEL_CAPABILITIES.md").read_text(encoding="utf-8")
    install_routing = next(line for line in install.splitlines() if line.startswith("Local model routing starts"))
    update_routing = next(line for line in update.splitlines() if line.startswith("Local model routing starts"))

    assert install_routing == update_routing
    assert '[hardware].profile="auto"' in install_routing
    assert "Model `qwen2.5-coder:1.5b` remains preprocessing-only" in install_routing
    assert any(line.startswith("Keep generated contracts aligned:") for line in install.splitlines())
    routes = {
        "cpu": ("qwen2.5-coder:3b", "qwen2.5-coder:3b", "qwen2.5-coder:7b", "qwen3.5:9b", "qwen2.5-coder:7b", "qwen3-vl:4b"),
        "integrated": ("qwen2.5-coder:3b", "qwen2.5-coder:3b", "qwen2.5-coder:7b", "qwen3.5:9b", "qwen2.5-coder:7b", "qwen3-vl:4b"),
        "low": ("qwen2.5-coder:3b", "qwen2.5-coder:3b", "qwen2.5-coder:7b", "qwen3.5:9b", "qwen2.5-coder:7b", "qwen3-vl:4b"),
        "balanced": ("qwen2.5-coder:3b", "qwen2.5-coder:3b", "qwen2.5-coder:7b", "qwen3.5:9b", "qwen2.5-coder:7b", "minicpm-v:8b"),
        "high": ("qwen2.5-coder:3b", "qwen2.5-coder:7b", "qwen2.5-coder:14b", "qwen3.5:9b", "qwen3.5:9b", "minicpm-v:8b"),
        "max": ("qwen2.5-coder:7b", "qwen2.5-coder:7b", "qwen2.5-coder:32b", "qwen3.5:9b", "qwen3.5:9b", "minicpm-v:8b"),
    }
    for profile, models in routes.items():
        role_order = ("background_code", "fast_code", "heavy_code", "reasoning", "general", "vision")
        configured = profile_overrides(profile)["models"]
        assert models == tuple(configured[role] for role in role_order), profile
        route = "/".join(models)
        assert f"{profile}={route}" in install_routing
        expected_row = "| " + " | ".join(f"`{value}`" for value in (profile, *models)) + " |"
        assert expected_row in model_doc

    for prompt in (install, update):
        assert "Ordinary reasoning uses `heavy_code`; only heavy reasoning uses `reasoning`." in prompt
        assert "Semantic delegation is on-demand under the active schema and quality gates" in prompt
        assert "Delegation is the default" not in prompt
        assert "In balanced," not in prompt

    stale_routes = (
        "`qwen2.5-coder:1.5b` for quick/simple tasks, `qwen2.5-coder:3b` for ordinary and more involved work",
        "`qwen2.5-coder:1.5b` for bounded extraction/simple work",
        "`qwen2.5-coder:3b` for ordinary bounded reasoning",
        "`qwen2.5-coder:1.5b` only for quick/simple microtasks",
        "`qwen2.5-coder:3b` for ordinary and more involved work",
    )
    assert not any(route in install for route in stale_routes)

    for prompt in (install, update):
        assert "response_budget.returned_tokens" in prompt
        assert "baseline_evidence_id" in prompt
        assert "max_response_tokens" in prompt
        assert "Load `local-ai-orchestrator` for full ownership, scope" in prompt


def test_agents_profile_routes_match_hardware() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    routing = next(line for line in agents.splitlines() if line.startswith("Local model policy:"))

    assert "Model routing follows the active hardware profile and user overrides" in routing
    assert "consult `docs/MODEL_CAPABILITIES.md` for foreground role targets" in routing
    assert "Routing targets do not prove installed-model availability" in routing

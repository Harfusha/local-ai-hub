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
    assert "`qwen2.5-coder:1.5b` is preprocessing-only" in install_routing
    assert any(line.startswith("Keep generated contracts aligned:") for line in install.splitlines())
    routes = {
        "cpu": ("qwen2.5-coder:3b", "qwen2.5-coder:3b", "qwen2.5-coder:7b", "qwen3.5:9b", "qwen2.5-coder:7b", "qwen3-vl:4b"),
        "integrated": ("qwen2.5-coder:3b", "qwen2.5-coder:3b", "qwen2.5-coder:7b", "qwen3.5:9b", "qwen2.5-coder:7b", "qwen3-vl:4b"),
        "low": ("qwen2.5-coder:3b", "qwen2.5-coder:3b", "qwen2.5-coder:7b", "qwen3.5:9b", "qwen2.5-coder:7b", "qwen3-vl:4b"),
        "balanced": ("qwen2.5-coder:3b", "qwen2.5-coder:3b", "qwen2.5-coder:7b", "qwen3.5:9b", "qwen2.5-coder:7b", "qwen3.5:9b"),
        "high": ("qwen2.5-coder:3b", "qwen2.5-coder:3b", "qwen2.5-coder:7b", "qwen3.5:9b", "qwen3.5:9b", "qwen3.5:9b"),
        "max": ("qwen2.5-coder:3b", "qwen2.5-coder:3b", "qwen3.5:9b", "qwen3.5:9b", "qwen3.5:9b", "qwen3.5:9b"),
    }
    for profile, models in routes.items():
        role_order = ("background_code", "fast_code", "heavy_code", "reasoning", "general", "vision")
        configured = profile_overrides(profile)["models"]
        assert models == tuple(configured[role] for role in role_order), profile
        route = "/".join(models)
        assert f"{profile}=`{route}`" in install_routing
        expected_row = "| " + " | ".join(f"`{value}`" for value in (profile, *models)) + " |"
        assert expected_row in model_doc

    for prompt in (install, update):
        assert "Ordinary reasoning uses `heavy_code`; only heavy reasoning uses `reasoning`." in prompt
        assert "Semantic delegation is on-demand and optional" in prompt
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

    response_budget_contract = (
        "`response_budget.returned_tokens` measures the final serialized response envelope in `estimated_tokens` and stays at or below the requested budget.",
        "Preserve protected status, error, evidence, and context-identity fields; keep exact detail artifact-backed.",
        "Claim savings only with a current `baseline_evidence_id`; report signed `token_savings_delta_est`, including negative values; keep `protocol_tokens_est`, `schema_tokens_est`, and `local_compute_reused_tokens_est` separate.",
        "Reject `max_response_tokens` below 128; never raise the request silently.",
        "For Hub outages, native fallback requires explicit `terminal=true` and `retryable=false`; for Hub-unknown commands, require `native_fallback_allowed=true` plus native-tool authorization.",
        "On `outcome_unknown` or `in_progress`, do independent work; never poll or repeat the identical operation.",
    )
    for sentence in response_budget_contract:
        assert sentence in install
        assert sentence in update


def test_agents_profile_routes_match_hardware() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    routing = next(line for line in agents.splitlines() if line.startswith("Local model policy:"))

    assert "Model routing follows the active hardware profile and user overrides" in routing
    assert "consult `docs/MODEL_CAPABILITIES.md` for foreground role targets" in routing
    assert "Routing targets do not prove installed-model availability" in routing

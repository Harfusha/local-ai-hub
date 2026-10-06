from pathlib import Path

from local_ai_hub.hardware import profile_overrides


ROOT = Path(__file__).resolve().parents[1]


def test_install_prompt_balanced_routes_match_profile_and_update_prompt() -> None:
    install = (ROOT / "docs" / "INSTALL_PROMPT.md").read_text(encoding="utf-8")
    update = (ROOT / "docs" / "UPDATE_PROMPT.md").read_text(encoding="utf-8")
    install_routing = next(
        line for line in install.splitlines()
        if line.startswith("Local model routing starts from")
    )
    update_routing = next(
        line for line in update.splitlines()
        if line.startswith("Local model routing starts from")
    )
    assert install_routing == update_routing
    role_order = ("background_code", "fast_code", "heavy_code", "reasoning", "general", "vision")
    for profile in ("integrated", "balanced", "high", "max"):
        models = profile_overrides(profile)["models"]
        expected_route = "/".join(models[role] for role in role_order)
        assert f"{profile}=`{expected_route}`" in install_routing
    assert "Ordinary reasoning uses `heavy_code`; only heavy reasoning uses `reasoning`." in install_routing

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
        "Native fallback requires an explicit `terminal=true` and `retryable=false` result.",
        "On `outcome_unknown` or `in_progress`, do independent work; never poll or repeat the identical operation.",
    )
    for sentence in response_budget_contract:
        assert sentence in install
        assert sentence in update

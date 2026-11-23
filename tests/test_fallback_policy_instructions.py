from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FALLBACK_POLICY = (
    "terminal=true` alone is insufficient",
    "`native_fallback_allowed=false`",
    "`native_fallback_allowed=true`",
    "unknown command",
    "dangerous command",
    "native tool must authorize the fallback",
)
OBSOLETE_FALLBACK_POLICY = (
    "permitted ONLY when Local AI Hub is unavailable",
    "a policy denial must never be retried through native shell",
)
HOST_COMMAND_POLICY = (
    "If the live schema has no action for an operation",
    "use the authorized native tool directly",
    "native fallback requires explicit `terminal=true` and `retryable=false`",
)


def test_native_fallback_policy_distinguishes_unknown_commands_and_is_synced() -> None:
    for relative_path in (
        "docs/INSTALL_PROMPT.md",
        "docs/UPDATE_PROMPT.md",
    ):
        contents = (ROOT / relative_path).read_text(encoding="utf-8")
        for required_text in FALLBACK_POLICY:
            assert required_text in contents, f"{relative_path} is missing: {required_text}"
        for obsolete_text in OBSOLETE_FALLBACK_POLICY:
            assert obsolete_text not in contents, f"{relative_path} retains: {obsolete_text}"

    project_policy = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "Load the always-loaded `local-ai-orchestrator` skill" in project_policy
    assert "complete Hub ownership, scope, MCP contract, lifecycle, memory, budget, GPU, and receipt rules" in project_policy

    from local_ai_hub.generator import generate_skill_markdown

    skill = generate_skill_markdown({})
    for required_text in HOST_COMMAND_POLICY:
        assert required_text in skill, f"local-ai-orchestrator is missing: {required_text}"

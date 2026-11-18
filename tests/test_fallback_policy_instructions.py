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
    "If active MCP schema exposes no action",
    "skip Hub and run one bounded host command directly",
    "This needs no Hub failure result",
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
    for required_text in HOST_COMMAND_POLICY:
        assert required_text in project_policy, f"AGENTS.md is missing: {required_text}"

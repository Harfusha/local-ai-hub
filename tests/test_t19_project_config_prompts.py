from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_install_and_update_prompts_share_current_project_config_policy() -> None:
    prompt_paths = (
        ROOT / "docs" / "INSTALL_PROMPT.md",
        ROOT / "docs" / "UPDATE_PROMPT.md",
    )
    sections = []
    required = (
        "Project configuration and PathHint core are integrated in current source",
        "resolve_project_context(root, state_dir)",
        "Overlay order is defaults, primary-worktree `.local-ai.toml`",
        "explicit excludes and hard boundaries take precedence over force includes",
        "`verification_rules` maps exact task acceptance-criterion names",
        "`required_commands` is not a global switch",
        "Cross-worktree Agent OS memory sharing remains HOLD",
        "`ProjectContext.prioritize_paths(...)` ranks the complete candidate list",
        "HTTP `/api/context/pack` accepts `path_hints`, `directory_hints`, `exclude_paths`, and `force_include_paths` in `adaptive` mode and validates lists. T14 owns that contract.",
        "Inspect installed generated schemas before using public wire fields.",
        "Hints are repository-relative paths beneath the trusted project root",
        "repository-scoped memory requires provenance tied to the trusted project root",
        "`state_data.memory_audit`",
    )

    for path in prompt_paths:
        prompt = path.read_text(encoding="utf-8")
        for tool_name in (
            "local_ai_status", "local_ai_task", "local_ai_repo", "local_ai_rag",
            "local_ai_coord", "local_ai_work", "local_ai_artifact",
        ):
            assert f"`{tool_name}`" in prompt, f"{path.name} missing tool: {tool_name}"
        assert "installed generated schema" in prompt
        assert "features.code_intelligence" in prompt
        assert "code_intelligence.serena_enabled" in prompt
        assert "Local model routing starts from `[hardware].profile=\"auto\"`" in prompt
        start = prompt.index("### Project configuration, verification, and PathHints")
        end = prompt.index("\n### Document and diagram ingestion", start)
        section = prompt[start:end]
        for contract in required:
            assert contract in section, f"{path.name} missing: {contract}"
        assert "consumers are not integrated or shipped in this T19 checkout" not in section
        assert "path_hints` is not a public MCP/API request field until T03" not in section
        assert "`/api/context/pack` does not accept or use hints" not in section
        sections.append(section)

    assert sections[0] == sections[1]

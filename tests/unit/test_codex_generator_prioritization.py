from pathlib import Path
import tempfile
from local_ai_hub.generator import generate_autosetup_policy, generate_global_policy, generate_token_economy_policy
from tools.setup import codex_hub_plugin_enabled, codex_mcp_merge, merge_autosetup_policy


def test_generated_policy_contains_codex_prioritization_directive() -> None:
    policy = generate_global_policy({})
    assert "LOCAL AI HUB TOOL PRIORITY" in policy
    assert "native command tool" in policy
    assert "local_ai_command(action=\"run\"" not in policy
    assert "local_ai_repo" in policy
    assert "local_ai_coord" in policy
    assert "Single-owner and repository scope contract" in policy
    assert len(policy.encode("utf-8")) < 23_900


def test_generated_token_economy_policy_includes_orchestrator() -> None:
    tok_policy = generate_token_economy_policy({})
    assert "local-ai-orchestrator" in tok_policy
    assert "code_index" in tok_policy and "search" in tok_policy


def test_codex_mcp_merge_defaults_to_prompt_approval() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "config.toml"
        servers = {
            "local-ai": {
                "command": "python",
                "args": ["-m", "local_ai_hub.mcp_server"],
                "cwd": tmpdir,
                "env": {"TEST": "1"},
            }
        }
        codex_mcp_merge(config_path, servers, backup_enabled=False)
        content = config_path.read_text(encoding="utf-8")
        assert '[mcp_servers.local-ai]' in content
        assert 'default_tools_approval_mode = "prompt"' in content


def test_codex_mcp_merge_preserves_explicit_approval_choice() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "config.toml"
        servers = {"local-ai": {"url": "http://127.0.0.1:11436/mcp"}}

        codex_mcp_merge(config_path, servers, backup_enabled=False)
        content = config_path.read_text(encoding="utf-8")
        config_path.write_text(
            content.replace('default_tools_approval_mode = "prompt"',
                            'default_tools_approval_mode = "approve"'),
            encoding="utf-8",
        )
        codex_mcp_merge(config_path, servers, backup_enabled=False)

        content = config_path.read_text(encoding="utf-8")
        assert 'default_tools_approval_mode = "approve"' in content


def test_codex_hub_plugin_state_is_read_from_native_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[plugins."local-ai-hub@local-ai-hub"]\nenabled = true\n',
        encoding="utf-8",
    )

    assert codex_hub_plugin_enabled(config_path) is True

    config_path.write_text(
        '[plugins."local-ai-hub@local-ai-hub"]\nenabled = false\n',
        encoding="utf-8",
    )
    assert codex_hub_plugin_enabled(config_path) is False


def test_autosetup_policy_merges_orchestrator_and_token_economizer() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        agents_doc = Path(tmpdir) / "AGENTS.md"
        skills_dir = Path(tmpdir) / "skills"
        merge_autosetup_policy(agents_doc, backup_enabled=False, skills_dir=skills_dir)
        content = agents_doc.read_text(encoding="utf-8")
        assert "<!-- BEGIN TOKEN ECONOMIZER AUTOSETUP -->" in content
        assert "local-ai-orchestrator" in content
        assert "token-economizer" in content
        assert "missing optional setup helpers do not block" in content
        assert "ensure-tools.ps1" not in content
        assert "<!-- END TOKEN ECONOMIZER AUTOSETUP -->" in content
        assert generate_autosetup_policy(skills_dir) in content

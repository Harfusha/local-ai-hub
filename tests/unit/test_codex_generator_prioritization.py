from pathlib import Path
import tempfile
from local_ai_hub.generator import generate_global_policy, generate_token_economy_policy
from tools.setup import codex_mcp_merge, merge_autosetup_policy


def test_generated_policy_contains_codex_prioritization_directive() -> None:
    policy = generate_global_policy({})
    assert "MANDATORY LOCAL AI HUB PRIORITIZATION IN CODEX" in policy
    assert "native command tool" in policy
    assert "local_ai_command(action=\"run\"" not in policy
    assert "local_ai_repo" in policy
    assert "local_ai_coord" in policy
    assert "Semantic delegation is on-demand" in policy


def test_generated_token_economy_policy_includes_orchestrator() -> None:
    tok_policy = generate_token_economy_policy({})
    assert "local-ai-orchestrator" in tok_policy
    assert 'local_ai_repo(action="code_index"|"search")' in tok_policy


def test_codex_mcp_merge_writes_auto_approval_mode() -> None:
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
        assert 'default_tools_approval_mode = "auto"' in content


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

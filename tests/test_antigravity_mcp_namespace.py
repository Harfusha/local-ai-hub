from pathlib import Path

from local_ai_hub.antigravity_hook import handle_pre_tool_use, handle_session_start
from local_ai_hub.generator import (
    generate_antigravity_skill_policy,
    generate_global_policy,
    generate_skill_markdown,
)


ROOT = Path(__file__).resolve().parents[1]
ANTIGRAVITY_SERVER = "local-ai-hub_local-ai"


def test_generated_guidance_uses_antigravity_plugin_namespace_only_where_needed():
    generated_skill = generate_skill_markdown({})
    global_policy = generate_global_policy({})
    antigravity_policy = generate_antigravity_skill_policy()

    assert 'ServerName="local-ai"' not in generated_skill
    assert "Antigravity may list Hub tools" not in generated_skill
    assert f'ServerName="{ANTIGRAVITY_SERVER}"' in global_policy
    assert f'ServerName="{ANTIGRAVITY_SERVER}"' in antigravity_policy
    assert 'ServerName="local-ai"' not in antigravity_policy


def test_antigravity_hook_guidance_uses_plugin_namespace():
    message = handle_session_start({"workspacePaths": ["C:/workspace"]})[
        "injectSteps"
    ][0]["systemMessage"]["systemMessage"]
    assert f'ServerName="{ANTIGRAVITY_SERVER}"' in message

    read_denial = handle_pre_tool_use({
        "toolCall": {
            "name": "read_file",
            "args": {"Path": "src/large.py", "StartLine": 1, "EndLine": 100},
        }
    })
    assert read_denial["decision"] == "deny"
    assert f'ServerName="{ANTIGRAVITY_SERVER}"' in read_denial["reason"]


def test_provider_skill_snapshots_do_not_publish_a_wrong_lazy_server_alias():
    for provider_dir in (ROOT / "plugins").iterdir():
        skill = (
            provider_dir / "local-ai-hub" / "skills" / "local-ai-orchestrator" / "SKILL.md"
        )
        if skill.is_file():
            content = skill.read_text(encoding="utf-8")
            assert 'ServerName="local-ai"' not in content, skill

    antigravity_rules = (
        ROOT / "plugins" / "antigravity" / "local-ai-hub" / "rules" / "AGENTS.md"
    ).read_text(encoding="utf-8")
    assert f'ServerName="{ANTIGRAVITY_SERVER}"' in antigravity_rules

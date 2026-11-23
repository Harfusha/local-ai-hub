from __future__ import annotations

import json
from local_ai_hub.client_adapters.registry import (
    get_adapter,
)

from local_ai_hub.client_adapters.adapters.antigravity import (
    AntigravityAdapter,
)

from local_ai_hub.client_adapters.adapters.codex import (
    CodexAdapter,
)

from local_ai_hub.client_adapters.adapters.claude import (
    ClaudeAdapter,
)

from local_ai_hub.client_adapters.adapters.cursor import (
    CursorAdapter,
)

from local_ai_hub.client_adapters.adapters.vscode import (
    VSCodeCopilotAdapter,
)

from local_ai_hub.client_adapters.adapters.gemini_cli import (
    GeminiCliAdapter,
)

from local_ai_hub.client_adapters.base import (
    InstructionTarget,
)


def test_antigravity_adapter_post_tool_use_parsing():
    adapter = get_adapter("antigravity")
    assert isinstance(adapter, AntigravityAdapter)
    # Test unrecognized payload returns None gracefully
    assert adapter.parse_hook_event({"invalid": "data"}) is None


def test_codex_token_usage_extraction():
    adapter = get_adapter("codex")
    assert isinstance(adapter, CodexAdapter)
    sample_payload = {
        "params": {
            "tokenUsage": {
                "total": {
                    "inputTokens": 1200,
                    "outputTokens": 450,
                    "cachedInputTokens": 800,
                    "reasoningOutputTokens": 300,
                    "totalTokens": 1650,
                }
            }
        }
    }
    extracted = adapter.extract_token_usage(sample_payload)
    assert extracted is not None
    assert extracted["input_tokens"] == 1200
    assert extracted["output_tokens"] == 450
    assert extracted["cache_read_tokens"] == 800
    assert extracted["thinking_tokens"] == 300
    assert extracted["total_tokens"] == 1650


def test_claude_instructions_contain_claude_header():
    adapter = get_adapter("claude")
    assert isinstance(adapter, ClaudeAdapter)
    instructions = adapter.get_instructions(InstructionTarget.CLAUDE_MD)
    assert "# Local AI Hub Integration" in instructions
    assert "local-ai" in instructions


def test_cursor_rules_clean_markdown():
    adapter = get_adapter("cursor")
    assert isinstance(adapter, CursorAdapter)
    rules = adapter.get_instructions(InstructionTarget.CURSORRULES)
    assert "<!-- BEGIN LOCAL AI HUB PLANNER -->" not in rules
    assert "<!-- END LOCAL AI HUB PLANNER -->" not in rules
    assert "## Local AI Hub Project Planner" in rules


def test_vscode_mcp_config():
    adapter = get_adapter("vscode")
    assert isinstance(adapter, VSCodeCopilotAdapter)
    config = adapter.generate_vscode_mcp_config("python.exe", "C:/Hub")
    servers = config.get("mcpServers", {})
    assert "local-ai" in servers
    assert servers["local-ai"]["command"] == "python.exe"
    assert servers["local-ai"]["cwd"] == "C:/Hub"


def test_gemini_cli_capabilities():
    adapter = get_adapter("gemini_cli")
    assert isinstance(adapter, GeminiCliAdapter)
    assert adapter.capabilities.hook_support.value == "full"


def test_adapter_capability_reports():
    for client_id in ["antigravity", "codex", "claude", "opencode", "cursor", "vscode", "gemini_cli"]:
        adapter = get_adapter(client_id)
        report = adapter.capability_report()
        assert report["client_id"] == client_id
        assert "hook_support" in report
        assert "instruction_targets" in report
        assert "has_token_tracking" in report

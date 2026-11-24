from __future__ import annotations

import os
from unittest.mock import patch
import pytest

from local_ai_hub.client_adapters.registry import (
    ClientRegistry,
    detect_client,
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

from local_ai_hub.client_adapters.adapters.opencode import (
    OpenCodeAdapter,
)

from local_ai_hub.client_adapters.adapters.cursor import (
    CursorAdapter,
    WindsurfAdapter,
)

from local_ai_hub.client_adapters.adapters.devin import DevinAdapter

from local_ai_hub.client_adapters.adapters.vscode import (
    VSCodeCopilotAdapter,
)

from local_ai_hub.client_adapters.adapters.gemini_cli import (
    GeminiCliAdapter,
)

from local_ai_hub.client_adapters.adapters.generic_mcp import (
    GenericMcpAdapter,
)


def test_registry_contains_all_default_adapters():
    clients = ClientRegistry.all_clients()
    expected = {
        "antigravity", "gemini_antigravity", "codex", "claude",
        "opencode", "cursor", "windsurf", "devin", "vscode", "copilot",
        "gemini_cli", "generic_mcp"
    }
    assert expected.issubset(set(clients))
    assert VSCodeCopilotAdapter.capabilities.hook_support.value == "pre_post_tool"


def test_detect_client_from_header():
    assert detect_client(agent_header="antigravity/1.0") == "antigravity"
    assert detect_client(agent_header="codex-cli") == "codex"
    assert detect_client(agent_header="claude/3.7") == "claude"
    assert detect_client(agent_header="opencode-local") == "opencode"
    assert detect_client(agent_header="cursor-ide") == "cursor"
    assert detect_client(agent_header="windsurf-cascade") == "windsurf"
    assert detect_client(agent_header="devin-local") == "devin"
    assert detect_client(agent_header="copilot-chat") == "vscode"
    assert detect_client(agent_header="vscode/1.96") == "vscode"
    assert detect_client(agent_header="gemini-cli") == "gemini_cli"


def test_detect_client_from_env():
    with patch.dict(os.environ, {"CLAUDE_ENV": "1"}, clear=True):
        assert detect_client() == "claude"

    with patch.dict(os.environ, {"CODEX_HOME": "/some/path"}, clear=True):
        assert detect_client() == "codex"

    with patch.dict(os.environ, {"ANTIGRAVITY_ENV": "1"}, clear=True):
        assert detect_client() == "antigravity"

    with patch.dict(os.environ, {"OPENCODE_SESSION": "123"}, clear=True):
        assert detect_client() == "opencode"

    with patch.dict(os.environ, {"CURSOR_PROJECT_DIR": "/proj"}, clear=True):
        assert detect_client() == "cursor"

    with patch.dict(os.environ, {}, clear=True):
        assert detect_client() == "generic_mcp"


def test_get_adapter_resolution():
    adapter_ag = get_adapter("antigravity")
    assert isinstance(adapter_ag, AntigravityAdapter)
    assert adapter_ag.capabilities.has_token_tracking is True

    adapter_codex = get_adapter("codex")
    assert isinstance(adapter_codex, CodexAdapter)
    assert adapter_codex.capabilities.has_reasoning_tokens is True

    adapter_claude = get_adapter(agent_header="claude/1.0")
    assert isinstance(adapter_claude, ClaudeAdapter)

    adapter_opencode = get_adapter("opencode")
    assert isinstance(adapter_opencode, OpenCodeAdapter)
    assert "local_ai_work" in adapter_opencode.capabilities.tool_filter
    assert "local_ai_status" in adapter_opencode.capabilities.tool_filter

    adapter_cursor = get_adapter("cursor")
    assert isinstance(adapter_cursor, CursorAdapter)

    adapter_windsurf = get_adapter("windsurf")
    assert isinstance(adapter_windsurf, WindsurfAdapter)
    assert adapter_windsurf.capabilities.hook_support.value == "pre_post_tool"

    assert isinstance(get_adapter("devin"), DevinAdapter)

    adapter_vscode = get_adapter("vscode")
    assert isinstance(adapter_vscode, VSCodeCopilotAdapter)

    adapter_gemini = get_adapter("gemini_cli")
    assert isinstance(adapter_gemini, GeminiCliAdapter)

    adapter_fallback = get_adapter("unknown_client_xyz")
    assert isinstance(adapter_fallback, GenericMcpAdapter)


def test_opencode_tool_filtering():
    adapter = get_adapter("opencode")
    tools = [
        {"name": "local_ai_status", "description": "..."},
        {"name": "local_ai_repo", "description": "..."},
        {"name": "local_ai_work", "description": "..."},
    ]
    filtered = adapter.filter_tools(tools)
    names = [t["name"] for t in filtered]
    assert names == ["local_ai_status", "local_ai_repo", "local_ai_work"]

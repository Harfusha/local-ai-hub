from __future__ import annotations

import json
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from uninstall import (
    clean_codex,
    clean_json,
    clean_policy,
    expand,
    is_managed_mcp_server,
    MARKER_BEGIN,
    MARKER_END,
    POLICY_BEGIN,
    POLICY_END,
)


def test_uninstall_expand_null_bytes() -> None:
    # Null bytes or invalid values in expand should not raise ValueError
    res = expand("~/.local\x00ai")
    assert ".local-ai-hub" in str(res)

    res_none = expand(None)  # type: ignore[arg-type]
    assert ".local-ai-hub" in str(res_none)


def test_uninstall_clean_json_array_payload(tmp_path: Path) -> None:
    # Non-dict JSON payload must not raise AttributeError
    json_file = tmp_path / "test.json"
    json_file.write_text("[1, 2, 3]", encoding="utf-8")
    clean_json(json_file)
    assert json.loads(json_file.read_text(encoding="utf-8")) == [1, 2, 3]

    # Valid mcpServers dict gets cleaned
    config = {
        "mcpServers": {
            "local-ai": {"command": "python"},
            "serena-local": {"command": "serena"},
            "keep-me": {"command": "other"},
        }
    }
    json_file.write_text(json.dumps(config), encoding="utf-8")
    clean_json(json_file)
    cleaned = json.loads(json_file.read_text(encoding="utf-8"))
    assert "local-ai" not in cleaned["mcpServers"]
    assert "serena-local" not in cleaned["mcpServers"]
    assert "keep-me" in cleaned["mcpServers"]

    # Non-existent file
    clean_json(tmp_path / "absent.json")


def test_uninstall_clean_codex_and_policy(tmp_path: Path) -> None:
    codex_file = tmp_path / "config.toml"
    codex_file.write_text(
        f"before\n{MARKER_BEGIN}\nsome managed content\n{MARKER_END}\nafter\n",
        encoding="utf-8",
    )
    clean_codex(codex_file)
    content = codex_file.read_text(encoding="utf-8")
    assert "some managed content" not in content
    assert "before" in content
    assert "after" in content

    # Policy cleaning
    policy_file = tmp_path / "AGENTS.md"
    policy_file.write_text(
        f"Intro\n{POLICY_BEGIN}\nManaged policy\n{POLICY_END}\nOutro\n",
        encoding="utf-8",
    )
    clean_policy(policy_file)
    policy_content = policy_file.read_text(encoding="utf-8")
    assert "Managed policy" not in policy_content
    assert "Intro" in policy_content
    assert "Outro" in policy_content


def test_uninstall_is_managed_mcp_server() -> None:
    assert is_managed_mcp_server("local-ai") is True
    assert is_managed_mcp_server("serena-local") is True
    assert is_managed_mcp_server("github") is False
    assert is_managed_mcp_server(None) is False
    assert is_managed_mcp_server(123) is False

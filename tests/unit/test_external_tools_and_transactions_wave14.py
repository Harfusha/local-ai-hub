import math
import pytest
from pathlib import Path

from local_ai_hub.external_tools import ExternalCodeIntelligence, MCPStdioClient
from local_ai_hub.command_transactions import TransactionStashHook, is_valid_transaction_write_path


def test_mcp_stdio_client_null_byte_rejection():
    with pytest.raises(ValueError, match="embedded null byte"):
        MCPStdioClient(["python\x00", "-V"])

    with pytest.raises(ValueError, match="embedded null byte"):
        MCPStdioClient(["python", "-V"], cwd="/bad/\x00/dir")


def test_mcp_stdio_client_timeout_hardening():
    # Booleans (isinstance(True, int)) or non-finite values should fall back safely to defaults
    client = MCPStdioClient(["python", "-V"], startup_timeout=True, call_timeout=float("nan"))
    assert client.startup_timeout >= 2.0
    assert client.call_timeout >= 1.0

    client2 = MCPStdioClient(["python", "-V"], startup_timeout=float("inf"), call_timeout=-10.0)
    assert client2.startup_timeout >= 2.0
    assert client2.call_timeout >= 1.0


def test_external_code_intelligence_none_sections():
    # When config contains explicit None for sections
    cfg = {"code_intelligence": None, "setup": None}
    ci = ExternalCodeIntelligence(cfg)
    assert ci.enabled is True
    assert ci.serena_enabled is True
    assert ci.cfg == {}
    assert ci.install_root.exists()


def test_git_ignored_directory_names_invalid_roots():
    assert ExternalCodeIntelligence._git_ignored_directory_names("") == set()
    assert ExternalCodeIntelligence._git_ignored_directory_names("bad\x00dir") == set()
    assert ExternalCodeIntelligence._git_ignored_directory_names(None) == set()


def test_transaction_stash_hook_null_byte_rejection(tmp_path: Path):
    with pytest.raises(ValueError, match="invalid transaction root path"):
        TransactionStashHook(f"{tmp_path}\x00bad")

    with pytest.raises(ValueError, match="invalid transaction stash message"):
        TransactionStashHook(tmp_path, message="stash\x00msg")


def test_is_valid_transaction_write_path():
    assert is_valid_transaction_write_path("src/module.py") is True
    assert is_valid_transaction_write_path("nested/dir/file.txt") is True

    # Invalid paths
    assert is_valid_transaction_write_path("") is False
    assert is_valid_transaction_write_path(None) is False
    assert is_valid_transaction_write_path("/abs/path.py") is False
    assert is_valid_transaction_write_path("C:/abs/path.py") is False
    assert is_valid_transaction_write_path("path/\x00/file.py") is False
    assert is_valid_transaction_write_path("../parent.py") is False
    assert is_valid_transaction_write_path("dir/../sibling.py") is False
    assert is_valid_transaction_write_path("NUL") is False
    assert is_valid_transaction_write_path("dir/CON") is False
    assert is_valid_transaction_write_path("trailing_dot./file.py") is False

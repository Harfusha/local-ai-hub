import pytest
from pathlib import Path
from local_ai_hub.token_economy import (
    generate_repo_map,
    strip_ansi,
    is_allowed_trim_command,
    count_tokens,
)


def test_generate_repo_map_hardening():
    # Invalid root_dir should return ([], 0) without raising
    assert generate_repo_map(None) == ([], 0)
    assert generate_repo_map(True) == ([], 0)
    assert generate_repo_map(False) == ([], 0)
    assert generate_repo_map(12345) == ([], 0)
    assert generate_repo_map("path/with\x00null") == ([], 0)
    assert generate_repo_map("   ") == ([], 0)
    assert generate_repo_map("non_existent_directory_xyz_123") == ([], 0)

    # Invalid limits and extension containers must fail closed without scanning.
    assert generate_repo_map(Path.cwd(), max_lines=True) == ([], 0)
    assert generate_repo_map(Path.cwd(), max_lines=0) == ([], 0)
    assert generate_repo_map(Path.cwd(), max_lines=50, exts=True) == ([], 0)
    assert generate_repo_map(Path.cwd(), max_lines=50, exts=(ext for ext in (".py",))) == ([], 0)


def test_strip_ansi_and_is_allowed_command_hardening():
    assert strip_ansi(True) == ""
    assert strip_ansi(None) == ""
    assert strip_ansi("hello\x1b[31mworld\x1b[0m\x00") == "helloworld"

    assert not is_allowed_trim_command(True)
    assert not is_allowed_trim_command(False)
    assert not is_allowed_trim_command(None)
    assert not is_allowed_trim_command("rg\x00malicious")
    assert is_allowed_trim_command("rg")
    assert is_allowed_trim_command("tokcount")


def test_count_tokens_hardening():
    for value in (True, False, None):
        with pytest.raises(TypeError):
            count_tokens(value)
    lines, words, chars, o200k, cl100k = count_tokens("hello world")
    assert words == 2

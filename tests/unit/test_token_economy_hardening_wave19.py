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
    assert generate_repo_map("non_existent_directory_xyz_123") == ([], 0)

    # Valid root with boolean/invalid max_lines and exts
    lines, total_files = generate_repo_map(Path.cwd(), max_lines=True, exts=True)
    assert isinstance(lines, list)
    assert isinstance(total_files, int)


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

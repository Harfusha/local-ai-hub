"""Deferred integration cases for reviewed gemini/wave-8-task-81 hunks."""
import tracemalloc

import pytest

from local_ai_hub import token_economy


def test_strip_ansi_extended_sequences():
    assert token_economy.strip_ansi("\x1b[?25hVisible\x1b[?25l") == "Visible"
    assert token_economy.strip_ansi("\x1b]0;Title\x07Clean Text") == "Clean Text"
    assert token_economy.strip_ansi("\x1b]8;;https://example.com\x1b\\Click Here\x1b]8;;\x1b\\") == "Click Here"
    assert token_economy.strip_ansi("\x1b(BNormal") == "Normal"


@pytest.mark.parametrize("limit, expected", [
    (0, []), (1, [0]), (5, [0, 1, 2, 18, 19]), (20, list(range(20))),
])
def test_trim_preserves_exact_head_tail_count(capsys, limit, expected):
    token_economy.filter_and_print_trimmed((f"line {number}\n" for number in range(20)), limit)
    output = capsys.readouterr().out
    assert [line for line in output.splitlines() if line.startswith("line ")] == [f"line {number}" for number in expected]
    assert ("truncated by trim-run" in output) == (limit < 20)


def test_trim_rejects_negative_limit():
    with pytest.raises(ValueError, match="max_lines must be a non-negative integer"):
        token_economy.filter_and_print_trimmed((f"line {number}\n" for number in range(20)), -1)


def test_trim_consumes_large_stream_without_retaining_all_lines(capsys):
    tracemalloc.start()
    try:
        token_economy.filter_and_print_trimmed((f"{number}:" + "x" * 1024 for number in range(10000)), 5)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 2_000_000
    assert "9,995 lines truncated" in capsys.readouterr().out


def test_repo_map_ignores_mixed_case_generated_directories(tmp_path):
    for directory in ("Build", "Node_Modules"):
        ignored = tmp_path / directory
        ignored.mkdir()
        (ignored / "ignored.py").write_text("class ShouldBeIgnored: pass\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("class Visible: pass\n", encoding="utf-8")
    lines, _total = token_economy.generate_repo_map(tmp_path, max_lines=100)
    assert "Visible" in "\n".join(lines)
    assert "ShouldBeIgnored" not in "\n".join(lines)

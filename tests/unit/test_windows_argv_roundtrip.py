"""Deferred native Windows argv regressions without launching a process."""
import os
import subprocess

import pytest

from local_ai_hub.commands import CommandBroker
from local_ai_hub.windows_argv import parse_windows_command_line


@pytest.mark.skipif(os.name != "nt", reason="native Windows parser")
@pytest.mark.parametrize("argv", [
    ["python", '--junitxml=C:/path with spaces/results.xml'],
    ["C:/Program Files/Python/python.exe", "", "žluťoučký", "a&b", "x|y"],
    ["python", "--flag=C:/plain.xml", 'embedded"quote', "trailing\\"],
    ["python", "--output=C:\\path with spaces\\", "  "],
])
def test_list2cmdline_roundtrip_preserves_argument_values(argv):
    command = subprocess.list2cmdline(argv)
    assert parse_windows_command_line(command) == argv
    assert CommandBroker._tokens(command) == argv


@pytest.mark.skipif(os.name != "nt", reason="native Windows parser")
def test_inline_option_quotes_do_not_become_filename_characters():
    assert CommandBroker._tokens('python -m pytest --junitxml="C:/path with spaces/report.xml"') == [
        "python", "-m", "pytest", "--junitxml=C:/path with spaces/report.xml",
    ]


@pytest.mark.parametrize(
    "command",
    ["python\x00ignored", "x" * 32768, None],
    ids=["nul-byte", "oversize-command", "non-string"],
)
def test_invalid_windows_command_lines_are_rejected_before_allocation(command):
    with pytest.raises(ValueError):
        parse_windows_command_line(command)


def test_empty_windows_command_does_not_resolve_current_executable():
    assert parse_windows_command_line("   ") == []

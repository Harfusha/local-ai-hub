from local_ai_hub.command_shell import (
    classify_raw_shell_subshell,
    is_powershell_command,
    needs_shell,
    split_shell_command,
    strip_null_redirections,
    tokenize_command,
)


def test_rejects_unquoted_shell_subshell_syntax():
    expected = {
        "class": "unknown",
        "cacheable": False,
        "allowed": False,
        "reason": "shell subshells are not accepted",
    }

    assert classify_raw_shell_subshell("echo $(whoami)", structured=False) == expected
    assert classify_raw_shell_subshell("echo `whoami`", structured=False) == expected


def test_ignores_subshell_syntax_inside_quotes():
    assert classify_raw_shell_subshell("echo '$(literal)'", structured=False) is None
    assert classify_raw_shell_subshell('echo "`literal`"', structured=False) is None


def test_structured_argv_does_not_apply_raw_shell_subshell_check():
    assert classify_raw_shell_subshell(["echo", "$(literal)"], structured=True) is None


def test_split_shell_command_ignores_delimiters_inside_quotes():
    assert split_shell_command(
        'echo "a;b|c" && pytest -q', ("&&", "|", ";")
    ) == [("", 'echo "a;b|c"'), ("&&", "pytest -q")]


def test_shell_detection_and_redirection_stripping():
    assert is_powershell_command("Get-ChildItem C:\\\\") is True
    assert is_powershell_command("$HOME") is True
    assert is_powershell_command("echo $HOME") is False
    assert is_powershell_command("cmd.exe /c echo hi") is False
    assert needs_shell("echo 'a;b'") is False
    assert needs_shell("pytest -q && python -m compileall") is True
    assert needs_shell("Get-ChildItem .") is True
    assert strip_null_redirections("pytest -q 2>&1") == "pytest -q"
    assert strip_null_redirections("pytest -q 2>&1   ") == "pytest -q"
    assert strip_null_redirections("echo hi > NUL") == "echo hi"


def test_tokenize_command_preserves_quoted_argument():
    assert tokenize_command('python -c "print(1 + 1)"') == [
        "python",
        "-c",
        "print(1 + 1)",
    ]
    assert tokenize_command("") == []

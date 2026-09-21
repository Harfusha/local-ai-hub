from local_ai_hub.commands import build_invocation, validate_invocation


def test_raw_shell_expansion_is_not_accepted():
    result = validate_invocation("powershell -Command Write-Host $HOME")
    assert result["safe"] is False
    assert result["reason"] == "unstructured_shell_text"
    assert result["terminal"] is True


def test_shell_true_and_nul_are_rejected():
    assert validate_invocation({"argv": ["python", "-c", "print(1)"], "shell": True})["safe"] is False
    assert validate_invocation(["python", "bad\x00arg"])["reason"] == "nul_in_argv"


def test_unicode_and_spaces_stay_in_argv():
    invocation = build_invocation("python", ["-c", "print('žluťoučký a b')"], cwd="C:\\repo with space")
    assert invocation.argv == ["python", "-c", "print('žluťoučký a b')"]
    assert invocation.shell is False

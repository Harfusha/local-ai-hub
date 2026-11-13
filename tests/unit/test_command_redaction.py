from local_ai_hub.command_redaction import redact_secrets
from local_ai_hub.commands import _redact_secrets


def test_command_redaction_wrapper_preserves_all_secret_patterns():
    raw = (
        "--password=password-value-1 --token token-value-2 Bearer bearer-value-3 "
        "Basic abcdefghijklmnop sk-1234567890abcdef123456 ghp_"
        "123456789012345678901234567890123456 AKIA1234567890ABCDEF "
        "aws_secret_access_key=aws-secret"
    )

    direct = redact_secrets(raw)

    assert _redact_secrets(raw) == direct
    for secret in (
        "password-value-1",
        "token-value-2",
        "bearer-value-3",
        "abcdefghijklmnop",
        "sk-1234567890abcdef123456",
        "ghp_123456789012345678901234567890123456",
        "AKIA1234567890ABCDEF",
        "aws-secret",
    ):
        assert secret not in direct
    assert "***" in direct


def test_empty_command_output_stays_empty():
    assert redact_secrets("") == ""

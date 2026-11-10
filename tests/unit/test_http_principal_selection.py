"""Retired HTTP identity configuration is rejected without weakening auth."""

from pathlib import Path

import pytest

from local_ai_hub import http_server
from local_ai_hub.config import ConfigError, validate_config


@pytest.mark.parametrize("retired", ["users", "api_token_tenant", "api_token_principal"])
@pytest.mark.parametrize("value", [None, False, ""])
def test_retired_security_identity_config_rejects_presence(retired, value):
    with pytest.raises(ConfigError, match=retired):
        validate_config({"security": {retired: value}})


def test_http_identity_module_is_removed():
    package_dir = Path(__file__).parents[2] / "src" / "local_ai_hub"
    assert not (package_dir / "http_identity.py").exists()


def test_api_token_and_permissions_are_retired():
    with pytest.raises(ConfigError, match="security.api_token was removed"):
        validate_config({"security": {"api_token": "secret"}})
    with pytest.raises(ConfigError, match="security.api_token_permissions was removed"):
        validate_config({"security": {"api_token_permissions": ["read", "write"]}})


def test_agent_header_fallback_does_not_recurse():
    handler = object.__new__(http_server.Handler)
    handler.headers = {"X-LocalAI-Agent": "codex"}

    assert handler._agent() == "codex"

"""Retired HTTP identity configuration is rejected without weakening auth."""

from pathlib import Path

import pytest

from local_ai_hub.config import ConfigError, validate_config


@pytest.mark.parametrize("retired", ["users", "api_token_tenant", "api_token_principal"])
@pytest.mark.parametrize("value", [None, False, ""])
def test_retired_security_identity_config_rejects_presence(retired, value):
    with pytest.raises(ConfigError, match=retired):
        validate_config({"security": {"api_token": "secret", retired: value}})


def test_http_identity_module_is_removed():
    package_dir = Path(__file__).parents[2] / "src" / "local_ai_hub"
    assert not (package_dir / "http_identity.py").exists()


def test_api_token_and_permissions_remain_supported():
    validate_config({"security": {"api_token": "secret", "api_token_permissions": ["read", "write"]}})

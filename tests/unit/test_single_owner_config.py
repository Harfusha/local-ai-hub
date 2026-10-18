"""Retired tenancy settings must reject without weakening credential protection."""

import pytest

from local_ai_hub.config import ConfigError, validate_config


@pytest.mark.parametrize(
    ("section", "field"),
    (
        ("security", "api_token_tenant"),
        ("security", "api_token_principal"),
        ("security", "tenant_derivation_key"),
        ("browser_bridge", "tenant"),
        ("scheduler", "max_queued_per_tenant"),
        ("scheduler", "max_inflight_per_tenant"),
    ),
)
@pytest.mark.parametrize("value", (None, "", "retired", False))
def test_retired_tenancy_settings_reject_by_presence(section, field, value):
    with pytest.raises(ConfigError, match="removed.*single local owner"):
        validate_config({section: {field: value}})


@pytest.mark.parametrize("value", (None, "", "retired", False))
def test_removed_security_users_setting_rejects_by_presence(value):
    with pytest.raises(ConfigError, match="removed.*single local owner"):
        validate_config({"security": {"users": value}})


def test_single_owner_keeps_api_tokens_and_resource_permissions():
    validate_config({
        "security": {
            "api_token": "a" * 32,
            "api_token_permissions": ["read", "write"],
            "supervisor_token": "s" * 32,
            "action_tokens": {"admin": "b" * 32},
        },
    })

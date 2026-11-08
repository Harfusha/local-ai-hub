"""Retired tenancy and Hub token settings must reject explicitly."""

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


@pytest.mark.parametrize("field", ("api_token", "supervisor_token", "action_tokens", "api_token_permissions"))
@pytest.mark.parametrize("value", (None, "", "retired", False, {}))
def test_removed_hub_api_token_settings_reject_by_presence(field, value):
    with pytest.raises(ConfigError, match=rf"security\.{field}.*removed"):
        validate_config({"security": {field: value}})


def test_non_loopback_server_bind_is_rejected():
    with pytest.raises(ConfigError, match="server.bind.*127.0.0.1"):
        validate_config({"server": {"bind": "0.0.0.0"}})

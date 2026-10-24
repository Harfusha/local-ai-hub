from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub import http_server


BOOLEAN_SETTINGS = (
    "debug_traces.enabled",
    "preprocessing.enabled",
    "code_intelligence.enabled",
    "code_intelligence.serena_enabled",
    "monitoring.dashboard_enabled",
    "features.status",
    "features.repo",
    "features.tasks",
    "features.rag",
    "features.commands",
    "features.coord",
    "features.artifacts",
    "features.code_intelligence",
    "features.preprocessing",
    "features.subagents",
    "features.agent_os",
    "features.dashboard",
    "features.work_orchestrator",
)
HARDWARE_PROFILES = ("auto", "cpu", "integrated", "low", "balanced", "high", "max")
NON_BOOLEAN_JSON_VALUES = (0, 1, 1.0, None, "true", [], {})
NON_PROFILE_JSON_VALUES = (True, False, 0, 1, 1.0, None, [], {}, "unsupported")


def test_type_matrix_covers_the_canonical_dashboard_setting_catalog():
    from local_ai_hub import dashboard_contracts

    assert set(BOOLEAN_SETTINGS) == dashboard_contracts._BOOLEAN_SETTINGS
    assert set(HARDWARE_PROFILES) == dashboard_contracts._PROFILES


def _dispatch_settings_update(monkeypatch, tmp_path: Path, setting: str, value, *, write_error=None):
    config = {"_config_path": str(tmp_path / "config.toml"), "security": {}}
    original_config = copy.deepcopy(config)
    app = SimpleNamespace(config=config, debug_traces=SimpleNamespace(enabled=True))
    writes = []
    responses = []

    def capture_write(config_path, patch, *, reset=False):
        writes.append((config_path, copy.deepcopy(patch), reset))
        if write_error is not None:
            raise write_error
        return Path(config_path).with_name("config.runtime.toml")

    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server, "save_runtime_overrides", capture_write)
    handler = object.__new__(http_server.Handler)
    handler.headers = {}
    handler.command = "POST"
    handler.path = "/api/config/update"
    handler._begin_trace = lambda *_args: None
    handler._validate_host_and_origin = lambda: True
    handler._require_authorized = lambda *_args, **_kwargs: True
    handler._read_json = lambda: json.loads(json.dumps({"settings": {setting: value}}))
    handler._validate_payload = lambda *_args: None
    handler._send = lambda status, payload: responses.append((status, payload))
    http_server.Handler.do_POST(handler)
    return responses, app, original_config, writes


def test_failed_setting_persistence_does_not_publish_live_toggle(monkeypatch, tmp_path):
    responses, app, original_config, writes = _dispatch_settings_update(
        monkeypatch, tmp_path, 'debug_traces.enabled', False,
        write_error=OSError('injected setting publication failure'),
    )
    assert responses[0][0] == 400
    assert responses[0][1]['error_code'] == 'config_update_rejected'
    assert len(writes) == 1
    assert app.debug_traces.enabled is True
    assert app.config == original_config
    assert not (tmp_path / 'config.runtime.toml').exists()


@pytest.mark.parametrize("setting", BOOLEAN_SETTINGS)
@pytest.mark.parametrize("value", NON_BOOLEAN_JSON_VALUES)
def test_dashboard_boolean_settings_reject_non_boolean_json_without_publication(
    monkeypatch, tmp_path, setting, value
):
    responses, app, original_config, writes = _dispatch_settings_update(
        monkeypatch, tmp_path, setting, value
    )

    assert responses[0][0] == 400
    assert writes == []
    assert app.config == original_config
    assert not (tmp_path / "config.runtime.toml").exists()


@pytest.mark.parametrize("setting", BOOLEAN_SETTINGS)
@pytest.mark.parametrize("value", (False, True))
def test_dashboard_boolean_settings_preserve_boolean_values(
    monkeypatch, tmp_path, setting, value
):
    responses, app, original_config, writes = _dispatch_settings_update(
        monkeypatch, tmp_path, setting, value
    )

    assert responses[0][0] == 200
    assert len(writes) == 1
    table, name = setting.split(".", 1)
    persisted_value = writes[0][1][table][name]
    assert type(persisted_value) is bool
    assert persisted_value is value
    assert app.config == original_config
    assert not (tmp_path / "config.runtime.toml").exists()


@pytest.mark.parametrize("value", NON_PROFILE_JSON_VALUES)
def test_hardware_profile_rejects_non_enum_json_values_without_publication(
    monkeypatch, tmp_path, value
):
    responses, app, original_config, writes = _dispatch_settings_update(
        monkeypatch, tmp_path, "hardware.profile", value
    )

    assert responses[0][0] == 400
    assert writes == []
    assert app.config == original_config
    assert not (tmp_path / "config.runtime.toml").exists()


@pytest.mark.parametrize("value", HARDWARE_PROFILES)
def test_hardware_profile_preserves_supported_enum_strings(
    monkeypatch, tmp_path, value
):
    responses, app, original_config, writes = _dispatch_settings_update(
        monkeypatch, tmp_path, "hardware.profile", value
    )

    assert responses[0][0] == 200
    assert len(writes) == 1
    persisted_value = writes[0][1]["hardware"]["profile"]
    assert type(persisted_value) is str
    assert persisted_value == value
    assert app.config == original_config
    assert not (tmp_path / "config.runtime.toml").exists()

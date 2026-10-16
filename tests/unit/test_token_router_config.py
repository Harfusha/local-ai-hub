import pytest

import local_ai_hub.state_paths as state_paths
import local_ai_hub.token_router as token_router


@pytest.fixture
def router_factory(monkeypatch, tmp_path):
    monkeypatch.setattr(state_paths, "configured_state_dir", lambda _config: tmp_path)
    monkeypatch.setattr(token_router, "SQLiteCache", lambda *args, **kwargs: object())
    monkeypatch.setattr(token_router, "TieredCache", lambda *args, **kwargs: object())

    def build(config):
        return token_router.LosslessTokenRouter(config, services=object())

    return build


@pytest.mark.parametrize("enabled", [True, False])
def test_router_preserves_boolean_enabled_setting(router_factory, enabled):
    router = router_factory({"lossless_router": {"enabled": enabled}})

    assert router.is_enabled() is enabled


@pytest.mark.parametrize("enabled", ["false", "true", 0, 1, None, [], {}])
def test_router_disables_on_non_boolean_enabled_setting(router_factory, enabled):
    router = router_factory({"lossless_router": {"enabled": enabled}})

    assert router.is_enabled() is False


def test_router_defaults_to_enabled_when_setting_is_absent(router_factory):
    router = router_factory({"lossless_router": {}})

    assert router.is_enabled() is True

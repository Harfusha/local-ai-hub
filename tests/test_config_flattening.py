from __future__ import annotations

from local_ai_hub.config_flattening import flatten_config_values
from local_ai_hub.deterministic import DeterministicEngine


def test_flatten_config_preserves_nested_paths_and_duplicate_list_keys():
    value = {
        "service": {
            "database": {"url": "sqlite"},
            "servers": [{"host": "a", "port": 1}, {"host": "b"}],
        },
        "enabled": True,
    }

    assert flatten_config_values(value) == [
        "service",
        "service.database",
        "service.database.url",
        "service.servers",
        "service.servers.host",
        "service.servers.port",
        "service.servers.host",
        "enabled",
    ]


def test_flatten_config_respects_existing_output_and_recursive_limit():
    out = ["existing"]

    result = flatten_config_values({"a": {"b": 1}, "c": 2}, out=out, limit=3)

    assert result is out
    assert out == ["existing", "a", "a.b"]
    assert flatten_config_values({"ignored": 1}, limit=0) == []


def test_flatten_config_keeps_eight_item_list_bound():
    value = [{"name": index} for index in range(10)]

    assert flatten_config_values(value, prefix="nodes") == ["nodes.name"] * 8


def test_deterministic_engine_static_wrapper_preserves_signature_and_output():
    assert DeterministicEngine._flatten_config({"database": {"url": "sqlite"}}) == [
        "database",
        "database.url",
    ]

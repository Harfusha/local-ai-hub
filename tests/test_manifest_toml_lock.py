from __future__ import annotations

import tomllib

import pytest

from local_ai_hub.manifest_toml_lock import parse_toml_lock_manifest


@pytest.mark.parametrize("name", ["uv.lock", "poetry.lock", "cargo.lock"])
def test_supported_toml_locks_keep_package_order_and_versions(name):
    raw = b'''[[package]]\nname = "first"\nversion = "1.0"\n\n[[package]]\nname = "second"\nversion = "2.0"\n'''

    assert parse_toml_lock_manifest(name, raw) == (
        [("first", "1.0", "lock"), ("second", "2.0", "lock")],
        [],
    )


def test_unsupported_names_and_malformed_toml_keep_existing_boundary():
    assert parse_toml_lock_manifest("pipfile", b"") is None
    with pytest.raises(tomllib.TOMLDecodeError):
        parse_toml_lock_manifest("uv.lock", b"package = [")

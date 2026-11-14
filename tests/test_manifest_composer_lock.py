from __future__ import annotations

import json

import pytest

from local_ai_hub.manifest_composer_lock import parse_composer_lock_manifest


def test_composer_lock_preserves_package_sections_and_order():
    raw = b'''{"packages":[{"name":"vendor/runtime","version":"1.0"},{"name":"vendor/next","version":"2.0"}],"packages-dev":[{"name":"vendor/test","version":"3.0"}]}'''

    assert parse_composer_lock_manifest("composer.lock", raw) == (
        [
            ("vendor/runtime", "1.0", "lock"),
            ("vendor/next", "2.0", "lock"),
            ("vendor/test", "3.0", "lock-dev"),
        ],
        [],
    )


def test_unsupported_name_and_malformed_json():
    assert parse_composer_lock_manifest("composer.json", b"{}") is None
    with pytest.raises(json.JSONDecodeError):
        parse_composer_lock_manifest("composer.lock", b"{")

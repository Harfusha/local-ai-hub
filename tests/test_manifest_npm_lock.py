from __future__ import annotations

import json

import pytest

from local_ai_hub.manifest_npm_lock import parse_npm_lock_manifest


def test_package_lock_prefers_flat_packages_and_preserves_nested_names():
    raw = json.dumps({
        "packages": {
            "": {"name": "app"},
            "node_modules/@scope/pkg": {"version": "1.2.0"},
            "node_modules/parent/node_modules/child": {"version": "2.0.0"},
        },
        "dependencies": {"ignored-fallback": {"version": "0.1"}},
    }).encode()

    assert parse_npm_lock_manifest("package-lock.json", raw) == (
        [("@scope/pkg", "1.2.0", "lock"), ("parent/node_modules/child", "2.0.0", "lock")],
        [],
    )


def test_old_package_lock_falls_back_to_dependencies_mapping():
    raw = b'''{"dependencies":{"first":{"version":"1.0"},"second":{}}}'''

    assert parse_npm_lock_manifest("package-lock.json", raw) == (
        [("first", "1.0", "lock"), ("second", "", "lock")],
        [],
    )


def test_pnpm_lock_extracts_scoped_and_unscoped_package_versions():
    raw = b"""lockfileVersion: '9.0'
  /@scope/pkg@1.2.0:
  plain@2.3.4(peer@5):
"""

    assert parse_npm_lock_manifest("pnpm-lock.yaml", raw) == (
        [("@scope/pkg", "1.2.0", "lock"), ("plain", "2.3.4", "lock")],
        [],
    )


def test_unsupported_names_and_invalid_json_keep_existing_boundary():
    assert parse_npm_lock_manifest("yarn.lock", b"") is None
    with pytest.raises(json.JSONDecodeError):
        parse_npm_lock_manifest("package-lock.json", b"{")

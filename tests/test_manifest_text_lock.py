from __future__ import annotations

import pytest

from local_ai_hub.manifest_text_lock import parse_text_lock_manifest


@pytest.mark.parametrize(
    ("name", "raw", "expected"),
    [
        (
            "yarn.lock",
            b'''pkg@^1, pkg@^2:\n  version "1.4.0"\n@scope/pkg@^3:\n  version "3.2.0"\n''',
            [("pkg", "1.4.0", "lock"), ("pkg", "1.4.0", "lock"), ("@scope/pkg", "3.2.0", "lock")],
        ),
        (
            "Gemfile.lock",
            b'''GEM\n  specs:\n    rack (3.0.8)\n    sidekiq (7.1.0)\n  dependencies:\n    rack\n''',
            [("rack", "3.0.8", "lock"), ("sidekiq", "7.1.0", "lock")],
        ),
    ],
)
def test_supported_text_lockfiles_keep_dependency_order(name, raw, expected):
    assert parse_text_lock_manifest(name, raw) == (expected, [])


def test_unsupported_names_return_none():
    assert parse_text_lock_manifest("package.json", b"{}") is None

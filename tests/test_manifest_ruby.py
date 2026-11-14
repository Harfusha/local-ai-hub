from __future__ import annotations

import re

from local_ai_hub.manifest_ruby import parse_gemfile_manifest


def test_gemfile_keeps_gem_order_and_optional_version():
    gem_pattern = re.compile(r"^\s*gem\s+['\"]([^'\"]+)['\"](?:\s*,\s*['\"]([^'\"]+)['\"])?")
    raw = b'''source "https://rubygems.org"\ngem "rails", "~> 7.1"\ngem 'rack'\n'''

    assert parse_gemfile_manifest("Gemfile", raw, gem_pattern) == (
        [("rails", "~> 7.1", "gem"), ("rack", "", "gem")],
        [],
    )


def test_unsupported_names_return_none():
    assert parse_gemfile_manifest("Gemfile.lock", b"", re.compile(".")) is None

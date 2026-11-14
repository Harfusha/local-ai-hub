from __future__ import annotations

import tomllib

import pytest

from local_ai_hub.manifest_gradle import parse_gradle_catalog_manifest


def test_catalog_preserves_string_and_structured_library_rows():
    raw = b'''[versions]\ncoroutines = "1.8.0"\n\n[libraries]\nplain = "org.example:plain:2.0"\nmodule = { module = "org.example:module", version = "3.0" }\nparts = { group = "org.example", name = "parts", version = { ref = "coroutines" } }\nlookup = { group = "org.example", name = "lookup", version.ref = "coroutines" }\n'''

    assert parse_gradle_catalog_manifest("libs.versions.toml", raw) == (
        [
            ("plain", "org.example:plain:2.0", "gradle-catalog"),
            ("org.example:module", "3.0", "gradle-catalog"),
            ("org.example:parts", "1.8.0", "gradle-catalog"),
            ("org.example:lookup", "1.8.0", "gradle-catalog"),
        ],
        [],
    )


def test_catalog_unsupported_name_and_malformed_toml():
    assert parse_gradle_catalog_manifest("gradle.properties", b"") is None
    with pytest.raises(tomllib.TOMLDecodeError):
        parse_gradle_catalog_manifest("libs.versions.toml", b"[libraries\n")

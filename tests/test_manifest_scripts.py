from __future__ import annotations

import re

import pytest

from local_ai_hub.manifest_scripts import parse_build_scripts_manifest


@pytest.mark.parametrize(
    ("name", "pattern", "raw", "runner"),
    [
        ("Makefile", re.compile(r"^([A-Za-z0-9_.-]+):"), b"build:\n.test:\n\nclean:\n", "make"),
        ("justfile", re.compile(r"^([A-Za-z0-9_-]+):"), b"build:\n.test:\nclean:\n", "just"),
    ],
)
def test_supported_script_manifests_keep_targets_and_purpose(name, pattern, raw, runner):
    assert parse_build_scripts_manifest(name, raw, pattern, lambda target: f"purpose:{target}") == (
        [],
        [("build", f"{runner} build", "purpose:build"), ("clean", f"{runner} clean", "purpose:clean")],
    )


def test_unsupported_names_return_none():
    assert parse_build_scripts_manifest("package.json", b"", re.compile("."), lambda target: "unused") is None

from __future__ import annotations

import tomllib

import pytest

from local_ai_hub.manifest_project import parse_project_manifest


def test_pyproject_keeps_pep621_poetry_rows_and_script_purpose():
    raw = b'''[project]\ndependencies = ["requests>=2", "rich"]\n[project.optional-dependencies]\ntest = ["pytest>=8"]\n[project.scripts]\ncli = "pkg:main"\n[tool.poetry.dependencies]\npython = "^3.11"\nflask = "^3"\n[tool.poetry.scripts]\ntool = "pkg:tool"\n'''

    assert parse_project_manifest("pyproject.toml", raw, lambda name: f"purpose:{name}") == (
        [
            ("requests", "requests>=2", "project"),
            ("rich", "rich", "project"),
            ("pytest", "pytest>=8", "optional:test"),
            ("flask", "^3", "poetry"),
        ],
        [("cli", "pkg:main", "purpose:cli"), ("tool", "pkg:tool", "purpose:tool")],
    )


def test_cargo_toml_keeps_dependency_sections_and_order():
    raw = b'''[dependencies]\nserde = "1"\n[dev-dependencies]\npretty_assertions = "1"\n[build-dependencies]\ncc = "1"\n'''

    assert parse_project_manifest("cargo.toml", raw, lambda name: "unused") == (
        [
            ("serde", "1", "dependencies"),
            ("pretty_assertions", "1", "dev-dependencies"),
            ("cc", "1", "build-dependencies"),
        ],
        [],
    )


def test_unsupported_name_and_malformed_toml():
    assert parse_project_manifest("uv.lock", b"", lambda name: "unused") is None
    with pytest.raises(tomllib.TOMLDecodeError):
        parse_project_manifest("pyproject.toml", b"[project\n", lambda name: "unused")

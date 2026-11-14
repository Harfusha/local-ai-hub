from __future__ import annotations

import pytest
import tomllib

from local_ai_hub.manifest_python import parse_python_manifest


def test_requirements_skips_options_comments_and_remote_references():
    raw = b"""# comment
pytest>=8
-r base.txt
--constraint constraints.txt
git+https://example.invalid/pkg
local-package[extra]==1.2 # note
"""

    assert parse_python_manifest("requirements-dev.txt", raw, lambda name: name) == (
        [("pytest", "pytest>=8", "requirements"), ("local-package", "local-package[extra]==1.2", "requirements")],
        [],
    )


def test_pipfile_keeps_dependency_and_script_purpose_order():
    raw = b'''[packages]\nrequests = "*"\n[dev-packages]\npytest = "*"\n[scripts]\ntest = "pytest"\n'''

    assert parse_python_manifest("pipfile", raw, lambda name: f"purpose:{name}") == (
        [("requests", "*", "packages"), ("pytest", "*", "dev-packages")],
        [("test", "pytest", "purpose:test")],
    )


def test_other_manifest_names_are_not_handled():
    assert parse_python_manifest("pyproject.toml", b"{}", lambda name: name) is None


def test_invalid_pipfile_propagates_to_existing_error_boundary():
    with pytest.raises(tomllib.TOMLDecodeError):
        parse_python_manifest("pipfile", b"packages = [", lambda name: name)

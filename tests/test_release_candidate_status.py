from __future__ import annotations

import json
from pathlib import Path
import tomllib


def test_unpublished_source_version_is_marked_as_a_release_candidate():
    release = json.loads(Path("RELEASE.json").read_text(encoding="utf-8"))
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert release["status"] == "release-candidate"
    assert "Development Status :: 4 - Beta" in project["classifiers"]
    assert "Development Status :: 5 - Production/Stable" not in project["classifiers"]

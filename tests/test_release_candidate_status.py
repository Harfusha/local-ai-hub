from __future__ import annotations

import json
import os
import re
from pathlib import Path
import tomllib


def test_unpublished_source_version_is_marked_as_a_release_candidate():
    release = json.loads(Path("RELEASE.json").read_text(encoding="utf-8"))
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]

    if os.environ.get("GITHUB_REF_TYPE") == "tag":
        expected_tag = f"v{release['version']}"
        tag = os.environ["GITHUB_REF_NAME"]
        if os.environ.get("HUB_CI_DRAFT_RELEASE") == "true":
            assert re.fullmatch(re.escape(expected_tag) + r"-qa\.[0-9]+", tag)
        else:
            assert tag == expected_tag
        assert release["status"] == "production-ready"
    else:
        assert release["status"] == "release-candidate"
    assert "Development Status :: 4 - Beta" in project["classifiers"]
    assert "Development Status :: 5 - Production/Stable" not in project["classifiers"]

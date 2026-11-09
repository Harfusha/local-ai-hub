from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_readme_feature_defaults_match_defaults_toml():
    defaults_path = REPO_ROOT / "defaults.toml"
    readme_path = REPO_ROOT / "README.md"

    with open(defaults_path, "rb") as f:
        defaults = tomllib.load(f)

    features = defaults.get("features", {})
    assert features.get("enriched_search") is True
    assert features.get("batch_replacement") is True
    assert features.get("diagnostic_artifacts") is True
    assert features.get("local_diagnostic_dispatch") is False

    readme_text = readme_path.read_text(encoding="utf-8")

    # README must not claim cost-bearing capabilities like enriched_search or batch_replacement are disabled by default
    assert "Cost-bearing adoption capabilities are disabled by default: `features.enriched_search`" not in readme_text

    # README must accurately document that enriched_search, batch_replacement, and diagnostic_artifacts are enabled by default
    assert "`features.enriched_search`, `features.batch_replacement`, and `features.diagnostic_artifacts` are enabled" in readme_text
    assert "`features.local_diagnostic_dispatch` is disabled by default" in readme_text

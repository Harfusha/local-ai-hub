import json
import tomllib
from datetime import date

import pytest

from tools.prepare_release import prepare_release


def make_source(root):
    package = root / "src/local_ai_hub"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('__version__ = "6.1.0"\n', encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "local-ai-hub"\nversion = "6.1.0"\n', encoding="utf-8"
    )
    (root / "RELEASE.json").write_text(
        json.dumps({"version": "6.1.0", "status": "release-candidate"}), encoding="utf-8"
    )
    (root / "README.md").write_text(
        "# Local AI Hub\n\n**Release status:** source version **6.1.0** is a release candidate.\n\n"
        "Local AI Hub **6.1.0** is a local tool.\n", encoding="utf-8",
    )
    (root / "CHANGELOG.md").write_text("# Changelog\n\n## 6.1.0 — 2026-11-15\n\n- Prior changes.\n", encoding="utf-8")
    return package / "__init__.py"


@pytest.mark.parametrize(("bump", "expected"), [("patch", "6.10.3"), ("minor", "6.11.0"), ("major", "7.0.0")])
def test_prepare_release_uses_highest_version_and_aligns_metadata(tmp_path, bump, expected):
    init = make_source(tmp_path)
    tag = prepare_release(tmp_path, bump, ["v6.1", "v6.9.9", "v6.10.2", "v9.0.0-rc.1"], date(2026, 11, 19))

    assert tag == f"v{expected}"
    assert tomllib.loads((tmp_path / "pyproject.toml").read_text())["project"]["version"] == expected
    assert init.read_text() == f'__version__ = "{expected}"\n'
    release = json.loads((tmp_path / "RELEASE.json").read_text())
    assert (release["version"], release["status"], release["release_date"]) == (expected, "production-ready", "2026-11-19")
    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    changelog = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"Local AI Hub **{expected}**" in readme
    assert "release candidate" not in readme
    assert f"## {expected} — 2026-11-19" in changelog
    assert "## 6.1.0 — 2026-11-15\n\n- Prior changes." in changelog


def test_prepare_release_rejects_inconsistent_metadata_without_writes(tmp_path):
    init = make_source(tmp_path)
    init.write_text('__version__ = "6.0.0"\n', encoding="utf-8")
    files = [init, tmp_path / "pyproject.toml", tmp_path / "RELEASE.json"]
    original = [path.read_bytes() for path in files]

    with pytest.raises(ValueError, match="inconsistent"):
        prepare_release(tmp_path, "patch", [], date(2026, 11, 19))

    assert [path.read_bytes() for path in files] == original

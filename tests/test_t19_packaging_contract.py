from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_source_distribution_excludes_internal_superpowers_plans() -> None:
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")

    assert "recursive-include docs *.md" in manifest
    assert "prune docs/superpowers" in manifest

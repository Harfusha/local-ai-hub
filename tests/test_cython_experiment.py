from __future__ import annotations

from pathlib import Path


def test_cython_experiment_source_is_isolated_and_not_production_enabled():
    root = Path(__file__).parents[1]
    source = root / "experiments" / "cython_simhash_votes.pyx"

    assert source.exists()
    assert "production_enabled" not in source.read_text(encoding="utf-8")
    assert "simhash_votes" in source.read_text(encoding="utf-8")

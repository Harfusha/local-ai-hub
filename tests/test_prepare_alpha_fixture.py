"""The reusable alpha seed must not copy runtime state or overwrite a root."""

from pathlib import Path
import runpy

import pytest


def test_alpha_builder_copies_only_seed_and_refuses_existing_root(tmp_path):
    script = Path(__file__).resolve().parents[1] / "docs/agent-evaluation/fixtures/prepare_alpha.py"
    builder = runpy.run_path(str(script))
    target = tmp_path / "alpha"
    builder["prepare"](str(target))
    actual = {p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()}
    assert actual == set(builder["FILES"])
    assert all((target / f).read_bytes() == (builder["SEED"] / f).read_bytes() for f in actual)
    assert not (target / ".serena").exists()
    sentinel = target / "foreign.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    with pytest.raises(ValueError, match="new directory"):
        builder["prepare"](str(target))
    assert sentinel.read_text(encoding="utf-8") == "preserve"

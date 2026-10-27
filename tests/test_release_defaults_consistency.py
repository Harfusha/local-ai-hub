from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_packaged_defaults_match_repository_defaults_and_keep_concise_output_opt_in():
    repository_defaults = tomllib.loads((ROOT / "defaults.toml").read_text(encoding="utf-8"))
    packaged_defaults = tomllib.loads(
        (ROOT / "src" / "local_ai_hub" / "defaults.toml").read_text(encoding="utf-8")
    )

    assert packaged_defaults == repository_defaults
    assert repository_defaults["token_saving"]["concise_local_output"] is False

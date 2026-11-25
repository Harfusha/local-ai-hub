from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRANSFORMERS_CONSTRAINT = "transformers>=4.57.4,<4.58"


def test_nlp_and_openvino_dependencies_use_fast_supported_transformers():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = project["project"]["optional-dependencies"]

    assert TRANSFORMERS_CONSTRAINT in extras["local-nlp"]
    assert TRANSFORMERS_CONSTRAINT in extras["intel-accelerators"]
    assert TRANSFORMERS_CONSTRAINT in (ROOT / "requirements-local-nlp.txt").read_text(encoding="utf-8")
    assert TRANSFORMERS_CONSTRAINT in (ROOT / "requirements-openvino.txt").read_text(encoding="utf-8")

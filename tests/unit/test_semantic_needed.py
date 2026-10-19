from __future__ import annotations

from pathlib import Path
from local_ai_hub.code_index import CodeIndex
from local_ai_hub.deterministic import DeterministicEngine


def test_semantic_needed_filters_low_value_and_noise_files(tmp_path: Path):
    engine = DeterministicEngine({}, code_index=None)

    # Declarative data files
    assert not engine.semantic_needed(str(tmp_path), "package.json")
    assert not engine.semantic_needed(str(tmp_path), "pyproject.toml")
    assert not engine.semantic_needed(str(tmp_path), "data.csv")

    # Minified files and bundles
    assert not engine.semantic_needed(str(tmp_path), "assets/hls.min.js")
    assert not engine.semantic_needed(str(tmp_path), "dist/vendor.bundle.js")
    assert not engine.semantic_needed(str(tmp_path), "styles/app.min.css")

    # Env templates and configs
    assert not engine.semantic_needed(str(tmp_path), ".env.example")
    assert not engine.semantic_needed(str(tmp_path), "config.sample")
    assert not engine.semantic_needed(str(tmp_path), ".env.local")

    # Legal / license boilerplates
    assert not engine.semantic_needed(str(tmp_path), "LICENSE")
    assert not engine.semantic_needed(str(tmp_path), "LICENSE.txt")
    assert not engine.semantic_needed(str(tmp_path), "NOTICE")

    # Changelogs
    assert not engine.semantic_needed(str(tmp_path), "CHANGELOG.md")
    assert not engine.semantic_needed(str(tmp_path), "history.md")

    # Test snapshots & fixtures
    assert not engine.semantic_needed(str(tmp_path), "tests/__snapshots__/ui.snap")
    assert not engine.semantic_needed(str(tmp_path), "fixtures/test_input.txt")

    # Real source code remains semantic
    assert engine.semantic_needed(str(tmp_path), "src/app.py")
    assert engine.semantic_needed(str(tmp_path), "lib/controller.ts")
    assert engine.semantic_needed(str(tmp_path), "models/user.go")

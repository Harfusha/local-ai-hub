from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub.config import ConfigError, load_config
from local_ai_hub.embeddings import EmbeddingModel
from local_ai_hub.reranker import Reranker


@pytest.mark.parametrize("kind", ["embedding", "reranker"])
@pytest.mark.parametrize("opt_in", [None, False, True, "true"])
@pytest.mark.parametrize("cache_present", [False, True])
def test_cache_loading_requires_explicit_network_opt_in(tmp_path, monkeypatch, kind, opt_in, cache_present):
    calls = []
    model = SimpleNamespace(config=SimpleNamespace(_commit_hash="a" * 40))

    def constructor(name, **kwargs):
        calls.append((name, kwargs.get("local_files_only", False)))
        if kwargs.get("local_files_only") and not cache_present:
            raise OSError("model absent from local cache")
        return model

    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(
        SentenceTransformer=constructor, CrossEncoder=constructor))
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(get_num_threads=lambda: 1))
    settings = {kind: "BAAI/bge-small-en-v1.5" if kind == "embedding" else "cached-reranker",
                f"{kind}_backend": "sentence-transformers" if kind == "embedding" else "torch",
                f"{kind}_device": "cpu"}
    if opt_in is not None:
        settings["allow_hf_downloads"] = opt_in
    instance = (EmbeddingModel if kind == "embedding" else Reranker)(
        {"server": {"state_dir": str(tmp_path)}, "models": settings})
    try:
        assert instance._load_candidate(0) is (cache_present or opt_in is True)
        expected = [True, False] if not cache_present and opt_in is True else [True]
        assert [local for _, local in calls] == expected
    finally:
        if instance._model is not None:
            assert instance.release()


@pytest.mark.parametrize("literal", ['"true"', "1", "[]"])
def test_download_opt_in_rejects_non_boolean_config(tmp_path, literal):
    config = tmp_path / "config.toml"
    config.write_text(f"[models]\nallow_hf_downloads={literal}\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="models.allow_hf_downloads must be boolean"):
        load_config(config, probe_hardware=False)


def test_download_default_is_off_in_source_and_packaged_defaults(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text("", encoding="utf-8")
    assert load_config(config, probe_hardware=False)["models"]["allow_hf_downloads"] is False
    root = Path(__file__).resolve().parents[1]
    for path in (root / "defaults.toml", root / "src/local_ai_hub/defaults.toml"):
        with path.open("rb") as source:
            assert tomllib.load(source)["models"]["allow_hf_downloads"] is False

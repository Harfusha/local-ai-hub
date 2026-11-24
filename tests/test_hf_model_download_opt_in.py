from __future__ import annotations

import sys
import tomllib
import hashlib
import re
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


def test_download_default_is_on_in_source_and_packaged_defaults(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text("", encoding="utf-8")
    assert load_config(config, probe_hardware=False)["models"]["allow_hf_downloads"] is True
    root = Path(__file__).resolve().parents[1]
    for path in (root / "defaults.toml", root / "src/local_ai_hub/defaults.toml"):
        with path.open("rb") as source:
            defaults = tomllib.load(source)
        assert defaults["models"]["allow_hf_downloads"] is True
        assert all(re.fullmatch(r"[0-9a-f]{64}", digest)
                   for digest in defaults["laya"]["runtime"]["hf_sha256"].values())


@pytest.mark.parametrize("allow_download", [False, True])
def test_trained_model_uses_local_cache_unless_download_is_opted_in(tmp_path, monkeypatch, allow_download):
    from local_ai_hub.trained_models import download_trained_model

    payload = b"pinned test model"
    model_file = tmp_path / "model.safetensors"
    model_file.write_bytes(payload)
    calls = []

    def snapshot_download(**kwargs):
        calls.append(kwargs)
        return str(tmp_path)

    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=snapshot_download))
    result = download_trained_model(
        "Harfusha/local-ai-hub-laya-run-expanded",
        "a" * 40,
        {"model.safetensors": hashlib.sha256(payload).hexdigest()},
        allow_download=allow_download,
    )

    assert result == tmp_path
    assert calls[0]["local_files_only"] is (not allow_download)


@pytest.mark.parametrize("allow_download", [False, True])
def test_laya_checkpoint_resolution_obeys_global_download_opt_in(tmp_path, monkeypatch, allow_download):
    from local_ai_hub import trained_models

    requested = []
    expected = {"model.safetensors": "a" * 64}

    def resolve(repo_id, revision, digests, *, allow_download):
        requested.append((repo_id, revision, digests, allow_download))
        return tmp_path

    monkeypatch.setattr(trained_models, "download_trained_model", resolve)
    runtime = {
        "checkpoint_path": "",
        "hf_repo_id": "Harfusha/local-ai-hub-laya-run-expanded",
        "hf_revision": "b" * 40,
        "hf_sha256": expected,
    }

    path, revision, hashes = trained_models.resolve_laya_checkpoint(
        runtime, {"allow_hf_downloads": allow_download}
    )

    assert path == str(tmp_path)
    assert revision == "b" * 40
    assert hashes == expected
    assert requested == [(runtime["hf_repo_id"], runtime["hf_revision"], expected, allow_download)]

from __future__ import annotations

import json
from pathlib import Path

from local_ai_hub import embeddings


def _write_export(path: Path) -> None:
    module = path / "0_Transformer"
    ir = module / "openvino"
    ir.mkdir(parents=True)
    (path / "modules.json").write_text(
        json.dumps([{"name": "0", "path": "0_Transformer"}]), encoding="utf-8"
    )
    (ir / "openvino_model.xml").write_text("<net />", encoding="utf-8")
    (ir / "openvino_model.bin").write_bytes(b"ir")


def test_openvino_export_cache_requires_manifest_and_ir(tmp_path: Path) -> None:
    assert not embeddings._openvino_export_cache_ready(tmp_path)
    _write_export(tmp_path)
    assert embeddings._openvino_export_cache_ready(tmp_path)


def test_openvino_export_cache_accepts_first_module_saved_in_root(tmp_path: Path) -> None:
    (tmp_path / "modules.json").write_text(
        json.dumps([{"name": "0", "path": ""}]), encoding="utf-8"
    )
    ir = tmp_path / "openvino"
    ir.mkdir()
    (ir / "openvino_model.xml").write_text("<net />", encoding="utf-8")
    (ir / "openvino_model.bin").write_bytes(b"ir")

    assert embeddings._openvino_export_cache_ready(tmp_path)


def test_openvino_export_persists_complete_model_atomically(tmp_path: Path) -> None:
    target = tmp_path / "cache" / "model"

    class FakeModel:
        def save(self, path: str, *, create_model_card: bool) -> None:
            assert create_model_card is False
            _write_export(Path(path))

    assert embeddings._persist_openvino_export(FakeModel(), target)
    assert embeddings._openvino_export_cache_ready(target)
    assert not list(target.parent.glob(".model.tmp-*"))
    assert embeddings._persist_openvino_export(FakeModel(), target)


def test_openvino_export_cache_path_tracks_runtime_and_model(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(embeddings, "configured_state_dir", lambda *_args, **_kwargs: tmp_path)
    monkeypatch.setattr(embeddings.importlib.metadata, "version", lambda _package: "1.0")

    first = embeddings._openvino_export_cache_path(
        {}, "model-a", revision="rev", max_seq_length=128, device="NPU"
    )
    same = embeddings._openvino_export_cache_path(
        {}, "model-a", revision="rev", max_seq_length=128, device="npu"
    )
    changed = embeddings._openvino_export_cache_path(
        {}, "model-a", revision="rev", max_seq_length=256, device="NPU"
    )

    assert first == same
    assert first != changed
    assert first.parent == tmp_path / "openvino-models"

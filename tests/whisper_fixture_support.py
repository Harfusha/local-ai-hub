"""Task-owned model cache for Whisper service contract tests."""

import hashlib
from pathlib import Path

import pytest

from local_ai_hub import whisper_policy


@pytest.fixture(autouse=True)
def _verified_whisper_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Exercise real cache verification with fixture bytes, never user models."""
    cache_dir = tmp_path / "whisper-cache"
    cache_dir.mkdir()
    model_bytes = b"isolated transcription contract model fixture"
    digest = hashlib.sha256(model_bytes).hexdigest()
    for model, filename in whisper_policy.MODEL_FILENAMES.items():
        (cache_dir / filename).write_bytes(model_bytes)
        monkeypatch.setitem(whisper_policy.MODEL_SHA256, model, digest)
    monkeypatch.setattr(whisper_policy, "default_cache_dir", lambda: cache_dir)
    return cache_dir

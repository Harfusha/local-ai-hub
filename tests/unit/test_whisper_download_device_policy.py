from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from local_ai_hub import whisper_policy
from local_ai_hub.services import LocalAIServices


def _cache_with_model(root: Path, model: str = "base", payload: bytes = b"verified model") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{model}.pt"
    path.write_bytes(payload)
    return path


def test_missing_model_fails_closed_unless_downloads_are_strictly_enabled(tmp_path: Path) -> None:
    denied = whisper_policy.prepare_whisper_model("base", cache_dir=tmp_path)
    assert not denied.ok
    assert denied.reason == "model_missing"

    truthy_but_not_boolean = whisper_policy.prepare_whisper_model(
        "base", cache_dir=tmp_path, allow_downloads=1
    )
    assert not truthy_but_not_boolean.ok

    allowed = whisper_policy.prepare_whisper_model(
        "base", cache_dir=tmp_path, allow_downloads=True
    )
    assert allowed.ok
    assert allowed.cached_model is None
    assert allowed.model_dir == str(tmp_path.resolve())


def test_cache_entry_must_match_official_digest_and_cpu_is_explicit(tmp_path: Path) -> None:
    payload = b"verified model bytes"
    path = _cache_with_model(tmp_path, payload=payload)
    with patch.dict(whisper_policy.MODEL_SHA256, {"base": hashlib.sha256(payload).hexdigest()}):
        accepted = whisper_policy.prepare_whisper_model("base", cache_dir=tmp_path)
    assert accepted.ok
    assert accepted.cached_model == str(path.resolve())
    assert accepted.device == "cpu"

    path.write_bytes(b"corrupt")
    rejected = whisper_policy.prepare_whisper_model("base", cache_dir=tmp_path)
    assert not rejected.ok
    assert rejected.reason == "model_corrupt"


def test_gpu_unknown_models_and_cancelled_verification_are_rejected(tmp_path: Path) -> None:
    unsupported_gpu = whisper_policy.prepare_whisper_model(
        "base", cache_dir=tmp_path, device="cuda"
    )
    assert unsupported_gpu.reason == "unsupported_device"

    unknown = whisper_policy.prepare_whisper_model("../base.pt", cache_dir=tmp_path)
    assert unknown.reason == "unsupported_model"

    _cache_with_model(tmp_path)
    cancelled = threading.Event()
    cancelled.set()
    with patch.dict(whisper_policy.MODEL_SHA256, {"base": "0" * 64}):
        result = whisper_policy.prepare_whisper_model(
            "base", cache_dir=tmp_path, cancel_event=cancelled
        )
    assert result.reason == "cancelled"


def test_oversized_cache_entries_are_rejected_before_hashing(tmp_path: Path) -> None:
    _cache_with_model(tmp_path, payload=b"too large")
    with patch.object(whisper_policy, "_MAX_MODEL_FILE_BYTES", 4):
        result = whisper_policy.prepare_whisper_model("base", cache_dir=tmp_path)
    assert result.reason == "model_too_large"


def test_aliases_use_the_official_canonical_cache_filenames(tmp_path: Path) -> None:
    payload = b"canonical model"
    cases = (("large", "large-v3.pt"), ("turbo", "large-v3-turbo.pt"))
    for alias, filename in cases:
        model_path = tmp_path / filename
        model_path.write_bytes(payload)
        with patch.dict(whisper_policy.MODEL_SHA256, {alias: hashlib.sha256(payload).hexdigest()}):
            result = whisper_policy.prepare_whisper_model(alias, cache_dir=tmp_path)
        assert result.ok
        assert result.cached_model == str(model_path.resolve())


def test_default_cache_honors_xdg_cache_home(tmp_path: Path) -> None:
    with patch.dict("os.environ", {"XDG_CACHE_HOME": str(tmp_path)}):
        assert whisper_policy.default_cache_dir() == tmp_path / "whisper"


def test_invalid_cache_dir_type_fails_closed() -> None:
    result = whisper_policy.prepare_whisper_model("base", cache_dir=42)  # type: ignore[arg-type]
    assert result.reason == "cache_unavailable"


def test_transcribe_passes_verified_model_path_and_explicit_cpu_flags(tmp_path: Path) -> None:
    payload = b"verified model bytes"
    cache = tmp_path / "cache"
    model_path = _cache_with_model(cache, payload=payload)
    audio = tmp_path / "input.wav"
    audio.write_bytes(b"audio")
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {"transcription": {"cache_dir": str(cache)}}
    seen: list[str] = []

    def fake_run_hidden(command: list[str], **kwargs: object) -> SimpleNamespace:
        seen.extend(command)
        output_dir = Path(command[command.index("--output_dir") + 1])
        (output_dir / "input.json").write_text(json.dumps({"text": "hello"}), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with (
        patch.dict(whisper_policy.MODEL_SHA256, {"base": hashlib.sha256(payload).hexdigest()}),
        patch("local_ai_hub.services.shutil.which", return_value="fake-whisper"),
        patch("local_ai_hub.process_utils.run_hidden", side_effect=fake_run_hidden),
    ):
        result = service.transcribe({"audio": str(audio)}, "test")

    assert result["success"] is True
    assert result["text"] == "hello"
    assert seen[seen.index("--model") + 1] == str(model_path.resolve())
    assert seen[seen.index("--model_dir") + 1] == str(cache.resolve())
    assert seen[seen.index("--device") + 1] == "cpu"


def test_transcribe_does_not_invoke_cli_for_missing_model_without_opt_in(tmp_path: Path) -> None:
    audio = tmp_path / "input.wav"
    audio.write_bytes(b"audio")
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {"transcription": {"cache_dir": str(tmp_path / "cache")}}
    with (
        patch("local_ai_hub.services.shutil.which", return_value="fake-whisper"),
        patch("local_ai_hub.process_utils.run_hidden") as run_hidden,
    ):
        result = service.transcribe({"audio": str(audio)}, "test")
    assert result["reason"] == "model_missing"
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert result["request_not_sent"] is True
    run_hidden.assert_not_called()

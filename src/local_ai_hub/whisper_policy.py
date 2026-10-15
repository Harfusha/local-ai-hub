"""Fail-closed cache and device policy for the optional OpenAI Whisper CLI."""

from __future__ import annotations

import hashlib
import os
import stat
import threading
import time
from dataclasses import dataclass
from pathlib import Path


# SHA-256 values are from OpenAI Whisper's official registry at immutable
# upstream commit 04f449b8a437f1bbd3dba5c9f826aca972e7709a.
MODEL_SHA256: dict[str, str] = {
    "tiny.en": "d3dd57d32accea0b295c96e26691aa14d8822fac7d9d27d5dc00b4ca2826dd03",
    "tiny": "65147644a518d12f04e32d6f3b26facc3f8dd46e5390956a9424a650c0ce22b9",
    "base.en": "25a8566e1d0c1e2231d1c762132cd20e0f96a85d16145c3a00adf5d1ac670ead",
    "base": "ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e",
    "small.en": "f953ad0fd29cacd07d5a9eda5624af0f6bcf2258be67c92b79389873d91e0872",
    "small": "9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794",
    "medium.en": "d7440d1dc186f76616474e0ff0b3b6b879abc9d1a4926b7adfa41db2d497ab4f",
    "medium": "345ae4da62f9b3d59415adc60127b97c714f32e89e936602e85993674d08dcb1",
    "large-v1": "e4b87e7e0bf463eb8e6956e646f1e277e901512310def2c24bf0e11bd3c28e9a",
    "large-v2": "81f7c96c852ee8fc832187b0132e569d6c3065a3252ed18e56effd0b6a73e524",
    "large-v3": "e5b1a55b89c1367dacf97e3e19bfd829a01529dbfdeefa8caeb59b3f1b81dadb",
    "large": "e5b1a55b89c1367dacf97e3e19bfd829a01529dbfdeefa8caeb59b3f1b81dadb",
    "large-v3-turbo": "aff26ae408abcba5fbf8813c21e62b0941638c5f6eebfb145be0c9839262a19a",
    "turbo": "aff26ae408abcba5fbf8813c21e62b0941638c5f6eebfb145be0c9839262a19a",
}
MODEL_FILENAMES: dict[str, str] = {
    **{name: f"{name}.pt" for name in MODEL_SHA256},
    "large": "large-v3.pt",
    "turbo": "large-v3-turbo.pt",
}

_CHUNK_SIZE = 1024 * 1024
_HASH_DEADLINE_SECONDS = 30.0
_MAX_MODEL_FILE_BYTES = 5 * 1024 * 1024 * 1024


@dataclass(frozen=True)
class WhisperModelPolicy:
    ok: bool
    model: str
    model_dir: str
    device: str = "cpu"
    cached_model: str | None = None
    reason: str | None = None
    error: str | None = None


def default_cache_dir() -> Path:
    """Return the canonical upstream OpenAI Whisper cache location."""
    cache_root = os.environ.get("XDG_CACHE_HOME")
    base = Path(cache_root).expanduser() if cache_root else Path.home() / ".cache"
    return base / "whisper"


def _file_signature(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _sha256_file(
    path: Path,
    *,
    cancel_event: threading.Event | None,
    deadline: float,
    expected_info: os.stat_result,
) -> str:
    digest = hashlib.sha256()
    bytes_read = 0
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    try:
        opened_info = os.fstat(fd)
        current_path_info = path.lstat()
        if (
            not stat.S_ISREG(opened_info.st_mode)
            or not stat.S_ISREG(current_path_info.st_mode)
            or _file_signature(opened_info) != _file_signature(expected_info)
            or _file_signature(current_path_info) != _file_signature(expected_info)
        ):
            raise OSError("Whisper cache entry changed before it could be verified")
        source = os.fdopen(fd, "rb", closefd=True)
        fd = -1
        with source:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise InterruptedError("cancelled")
                if time.monotonic() >= deadline:
                    raise TimeoutError("hash deadline exceeded")
                chunk = source.read(_CHUNK_SIZE)
                if time.monotonic() >= deadline:
                    raise TimeoutError("hash deadline exceeded")
                if not chunk:
                    break
                bytes_read += len(chunk)
                if bytes_read > _MAX_MODEL_FILE_BYTES:
                    raise ValueError("model cache entry exceeds the maximum supported size")
                digest.update(chunk)
            final_fd_info = os.fstat(source.fileno())
            final_path_info = path.lstat()
            if (
                _file_signature(final_fd_info) != _file_signature(expected_info)
                or _file_signature(final_path_info) != _file_signature(expected_info)
            ):
                raise OSError("Whisper cache entry changed while it was verified")
        return digest.hexdigest()
    finally:
        if fd >= 0:
            os.close(fd)


def prepare_whisper_model(
    model: str,
    *,
    cache_dir: str | os.PathLike[str] | None = None,
    allow_downloads: object = False,
    device: object = "cpu",
    cancel_event: threading.Event | None = None,
) -> WhisperModelPolicy:
    """Validate model/device and require an official-hash cache hit by default."""
    if model not in MODEL_SHA256:
        return WhisperModelPolicy(
            False, model, "", reason="unsupported_model", error="Unsupported Whisper model name."
        )
    if not isinstance(device, str) or device.strip().casefold() != "cpu":
        return WhisperModelPolicy(
            False,
            model,
            "",
            reason="unsupported_device",
            error="Only the explicitly configured CPU device is admitted.",
        )
    if cache_dir is None:
        root = default_cache_dir()
    elif isinstance(cache_dir, (str, os.PathLike)):
        if not str(cache_dir).strip():
            return WhisperModelPolicy(
                False, model, "", reason="cache_unavailable", error="Whisper cache path is invalid."
            )
        try:
            root = Path(cache_dir).expanduser()
        except (OSError, RuntimeError, TypeError, ValueError):
            return WhisperModelPolicy(
                False, model, "", reason="cache_unavailable", error="Whisper cache path is invalid."
            )
    else:
        return WhisperModelPolicy(
            False, model, "", reason="cache_unavailable", error="Whisper cache path is invalid."
        )
    try:
        root = root.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return WhisperModelPolicy(
            False, model, str(root), reason="cache_unavailable", error="Whisper cache path is invalid."
        )

    candidate = root / MODEL_FILENAMES[model]
    try:
        info = candidate.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise OSError("symbolic links are not accepted as model cache entries")
    except FileNotFoundError:
        if type(allow_downloads) is bool and allow_downloads:
            return WhisperModelPolicy(True, model, str(root))
        return WhisperModelPolicy(
            False,
            model,
            str(root),
            reason="model_missing",
            error="Verified Whisper model is not present in the local cache.",
        )
    except OSError:
        return WhisperModelPolicy(
            False,
            model,
            str(root),
            reason="model_unavailable",
            error="Whisper cache entry is not an accessible regular file.",
        )

    if info.st_size <= 0:
        return WhisperModelPolicy(
            False,
            model,
            str(root),
            reason="model_corrupt",
            error="Cached Whisper model failed the official SHA-256 check.",
        )
    if info.st_size > _MAX_MODEL_FILE_BYTES:
        return WhisperModelPolicy(
            False,
            model,
            str(root),
            reason="model_too_large",
            error="Cached Whisper model exceeds the maximum supported size.",
        )
    try:
        actual = _sha256_file(
            candidate,
            cancel_event=cancel_event,
            deadline=time.monotonic() + _HASH_DEADLINE_SECONDS,
            expected_info=info,
        )
    except InterruptedError:
        return WhisperModelPolicy(
            False, model, str(root), reason="cancelled", error="Whisper cache verification was cancelled."
        )
    except TimeoutError:
        return WhisperModelPolicy(
            False,
            model,
            str(root),
            reason="model_verify_timeout",
            error="Whisper cache verification exceeded its time limit.",
        )
    except ValueError:
        return WhisperModelPolicy(
            False,
            model,
            str(root),
            reason="model_too_large",
            error="Cached Whisper model exceeds the maximum supported size.",
        )
    except OSError:
        return WhisperModelPolicy(
            False,
            model,
            str(root),
            reason="model_unavailable",
            error="Whisper cache entry could not be verified.",
        )
    if actual != MODEL_SHA256[model]:
        if type(allow_downloads) is bool and allow_downloads:
            # Upstream Whisper replaces an invalid entry; this is permitted only
            # by the explicit boolean opt-in above.
            return WhisperModelPolicy(True, model, str(root))
        return WhisperModelPolicy(
            False,
            model,
            str(root),
            reason="model_corrupt",
            error="Cached Whisper model failed the official SHA-256 check.",
        )
    return WhisperModelPolicy(True, str(candidate), str(root), cached_model=str(candidate))

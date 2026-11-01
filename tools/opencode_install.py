"""Verified, non-destructive installation of the pinned OpenCode Windows CLI.

This module provisions the executable only. It does not configure providers,
MCP, network isolation, or user PATH, and does not imply a complete setup.
"""
from __future__ import annotations

import hashlib
import io
import os
import stat
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path


VERSION = "2.2.5"
WINDOWS_X64_URL = (
    "https://github.com/anomalyco/opencode/releases/download/v2.2.5/"
    "opencode-windows-x64.zip"
)
WINDOWS_X64_ARCHIVE_SHA256 = "2f3bfd6b3527c60c2a882557b20ddc9ba6bdff4b5a8fe61c853da8fcfb3076e8"
WINDOWS_X64_EXECUTABLE_SHA256 = "0c346fdaf519d2f23a31d3b6cb9d65e369a72d77cac6f027b5e0a06376ec3a43"
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_EXECUTABLE_BYTES = 400 * 1024 * 1024


class InstallError(RuntimeError):
    """The binary could not be verified or installed safely."""


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download() -> bytes:
    request = urllib.request.Request(WINDOWS_X64_URL, headers={"User-Agent": "Local-AI-Hub"})
    deadline = time.monotonic() + 300
    data = bytearray()
    with urllib.request.urlopen(request, timeout=30) as response:
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("download deadline exceeded")
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > MAX_ARCHIVE_BYTES:
                raise ValueError("download exceeds size limit")
    return bytes(data)


def install_windows_x64(directory: Path) -> Path:
    """Install the exact pinned binary without replacing an existing file."""
    directory = Path(directory)
    target = directory / "opencode.exe"
    if target.exists() or target.is_symlink():
        try:
            if (target.is_file() and not target.is_symlink() and target.stat().st_size <= MAX_EXECUTABLE_BYTES
                    and _file_digest(target) == WINDOWS_X64_EXECUTABLE_SHA256):
                return target
        except OSError as exc:
            raise InstallError(f"existing OpenCode executable cannot be checked: {exc}") from exc
        raise InstallError("existing OpenCode executable is not the pinned binary; refusing to overwrite")
    try:
        data = _download()
    except (OSError, ValueError) as exc:
        raise InstallError(f"OpenCode download failed: {exc}") from exc
    if _digest(data) != WINDOWS_X64_ARCHIVE_SHA256:
        raise InstallError("OpenCode archive checksum mismatch")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) != 1 or entries[0].filename != "opencode.exe":
                raise InstallError("OpenCode archive has unexpected members")
            entry = entries[0]
            if entry.is_dir() or stat.S_ISLNK(entry.external_attr >> 16) or entry.file_size > MAX_EXECUTABLE_BYTES:
                raise InstallError("OpenCode archive executable is invalid")
            executable = archive.read(entry)
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        if isinstance(exc, InstallError):
            raise
        raise InstallError(f"OpenCode archive is invalid: {exc}") from exc
    if _digest(executable) != WINDOWS_X64_EXECUTABLE_SHA256:
        raise InstallError("OpenCode executable checksum mismatch")
    temporary = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".opencode-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(executable)
            stream.flush()
            os.fsync(stream.fileno())
        # Hard-link creation fails if another installer or user created target.
        os.link(temporary, target)
    except OSError as exc:
        raise InstallError(f"OpenCode installation failed without overwriting existing files: {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target

"""Provision one pinned, verified Microsoft MXC Windows x64 executor.

Provisioning alone does not enable or prove an OpenCode sandbox.
"""
from __future__ import annotations

import base64
import hashlib
import io
import os
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

VERSION = "1.0.1"
ARCHIVE_URL = "https://registry.npmjs.org/@microsoft/mxc-sdk/-/mxc-sdk-1.0.1.tgz"
ARCHIVE_SHA512 = "2cP925G5+lQyKzjBVha8uNtVd7XESgDBtgi1yCYYSo9M3xiFyZWtCO4SWPGTk509rdI6nqjyGcZxvEP3t6l8Hg=="
EXECUTABLE_SHA256 = "090f5d1f7bb93104ab08dcd4e8034ef954aeefcdaf6658dde5f7dff4cfc12f3a"
_MEMBER = "package/bin/x64/wxc-exec.exe"
_MAX_ARCHIVE = 64 * 1024 * 1024
_MAX_EXECUTABLE = 64 * 1024 * 1024


class InstallError(RuntimeError):
    """The sandbox executable could not be verified or installed."""


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download() -> bytes:
    request = urllib.request.Request(ARCHIVE_URL, headers={"User-Agent": "Local-AI-Hub"})
    deadline = time.monotonic() + 300
    data = bytearray()
    with urllib.request.urlopen(request, timeout=30) as response:
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("sandbox download deadline exceeded")
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > _MAX_ARCHIVE:
                raise ValueError("sandbox archive exceeds size limit")
    return bytes(data)


def install_windows_x64(directory: Path) -> Path:
    target = Path(directory) / "wxc-exec.exe"
    if target.exists() or target.is_symlink():
        try:
            if target.is_file() and not target.is_symlink() and target.stat().st_size <= _MAX_EXECUTABLE and _file_digest(target) == EXECUTABLE_SHA256:
                return target
        except OSError as exc:
            raise InstallError("existing sandbox executor cannot be verified") from exc
        raise InstallError("existing sandbox executor does not match; refusing to overwrite")
    try:
        data = _download()
    except (OSError, ValueError) as exc:
        raise InstallError("sandbox archive download failed") from exc
    if base64.b64encode(hashlib.sha512(data).digest()).decode("ascii") != ARCHIVE_SHA512:
        raise InstallError("sandbox archive checksum mismatch")
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as package:
            matches = [member for member in package if member.name == _MEMBER]
            if len(matches) != 1 or not matches[0].isfile() or matches[0].size > _MAX_EXECUTABLE:
                raise InstallError("sandbox archive member is missing or invalid")
            stream = package.extractfile(matches[0])
            if stream is None:
                raise InstallError("sandbox archive member is unreadable")
            executable = stream.read(_MAX_EXECUTABLE + 1)
    except (OSError, tarfile.TarError, EOFError) as exc:
        raise InstallError("sandbox archive is invalid") from exc
    if len(executable) > _MAX_EXECUTABLE or hashlib.sha256(executable).hexdigest() != EXECUTABLE_SHA256:
        raise InstallError("sandbox executable checksum mismatch")
    temporary = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".mxc-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(executable)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, target)
    except OSError as exc:
        raise InstallError("sandbox installation failed without overwriting existing files") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target

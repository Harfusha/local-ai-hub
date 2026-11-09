from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import re
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any, Callable


DEFAULT_MAX_ARCHIVE_BYTES = 8 * 1024 * 1024 * 1024
DEFAULT_MAX_SOURCE_BYTES = 64 * 1024 * 1024 * 1024
_COPY_CHUNK_SIZE = 64 * 1024
_CORE_DATABASES = {"telemetry.sqlite3", "endpoint_stats.sqlite3", "debug_traces.sqlite3"}
_DATABASE_SUFFIXES = {".sqlite", ".sqlite3", ".db"}
_STATE_TEXT_SUFFIXES = {".log", ".jsonl"}
_SOURCE_SUFFIXES = {
    ".py", ".md", ".toml", ".txt", ".json", ".jsonl", ".yaml", ".yml", ".sql",
    ".html", ".js", ".ts", ".tsx", ".css", ".sh", ".ps1", ".lock", ".in",
}
_MODEL_SUFFIXES = {".bin", ".gguf", ".ggml", ".safetensors", ".onnx", ".pt", ".pth", ".tflite", ".mlx"}
_SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "node_modules", "dist", "build",
    "models", "model", "model-cache", "model_cache", "downloads", "hf_cache",
    "ollama-models", "llama-models", "openvino-cache", "diagnostic-exports",
}
_SECRET_KEY_PARTS = (
    "api_key", "access_key", "secret", "password", "passphrase", "credential", "token",
    "authorization", "bearer", "private_key",
)
_URL_CREDENTIALS = re.compile(r"(?i)(https?://)[^/@\s]+:[^/@\s]+@")
_QUERY_CREDENTIALS = re.compile(r"(?i)([?&](?:api[_-]?key|access[_-]?token|token|password|secret)=)[^&\s]+")


class DiagnosticArchive:
    """Temporary encrypted archive. Caller must close after sending it."""

    def __init__(self, temp: tempfile.TemporaryDirectory[str], path: Path, password: str, manifest: dict[str, Any]):
        self._temp = temp
        self.path = path
        self.password = password
        self.manifest = manifest
        self.size = path.stat().st_size
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._temp.cleanup()

    def __enter__(self) -> DiagnosticArchive:
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


def _cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise RuntimeError("diagnostic export cancelled")


def _is_secret_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
    return any(
        normalized == part
        or normalized.endswith("_" + part)
        or normalized.startswith(part + "_")
        for part in _SECRET_KEY_PARTS
    )


def _redact_config(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _is_secret_key(str(key)) else _redact_config(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_config(item) for item in value]
    if isinstance(value, str):
        value = _URL_CREDENTIALS.sub(r"\1[REDACTED]@", value)
        return _QUERY_CREDENTIALS.sub(r"\1[REDACTED]", value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _repository_root(module_path: Path) -> Path | None:
    for parent in module_path.resolve().parents:
        if (parent / "pyproject.toml").is_file() and (parent / "src" / "local_ai_hub").is_dir():
            return parent
    return None


def _source_files(source_root: Path | str | None) -> list[tuple[Path, str]]:
    module_path = Path(__file__).resolve()
    root = Path(source_root).expanduser().resolve() if source_root is not None else _repository_root(module_path)
    if source_root is not None and (root is None or not root.is_dir()):
        return []
    if root is not None and root.is_dir() and (root / "src" / "local_ai_hub").is_dir():
        allowed_roots = [
            root / item for item in (
                ".github", ".local-ai-hub-superpowers", "benchmarks", "browser_bridge", "data",
                "docs", "experiments", "generated", "skills", "src/local_ai_hub", "tests", "tools",
            )
        ]
        candidates: list[tuple[Path, str]] = []
        root_files = [
            path for path in root.iterdir()
            if path.is_file()
            and not path.is_symlink()
            and path.name not in {".local-ai.toml", "config.toml"}
            and (path.suffix.lower() in _SOURCE_SUFFIXES or path.name == "config.toml.example")
        ]
        root_files.extend(root.glob("requirements*.txt"))
        root_files.extend(root.glob("*.lock"))
        for path in root_files:
            if path.is_file() and not path.is_symlink():
                candidates.append((path, "hub/" + path.relative_to(root).as_posix()))
        for allowed in allowed_roots:
            if not allowed.is_dir() or allowed.is_symlink():
                continue
            for directory, dirs, names in os.walk(allowed, followlinks=False):
                base = Path(directory)
                dirs[:] = [name for name in dirs if name not in _SKIP_DIRS and not (base / name).is_symlink()]
                if base == root / "docs" / "agent-evaluation":
                    dirs[:] = [name for name in dirs if name != "fixtures"]
                for name in names:
                    path = base / name
                    if path.is_symlink() or path.suffix.lower() not in _SOURCE_SUFFIXES:
                        continue
                    relative = path.relative_to(root).as_posix()
                    if any(part in _SKIP_DIRS for part in Path(relative).parts):
                        continue
                    candidates.append((path, "hub/" + relative))
        unique = {archive_name: (path, archive_name) for path, archive_name in candidates}
        return sorted(unique.values(), key=lambda entry: entry[1])

    package_root = module_path.parent
    candidates = []
    for path in package_root.rglob("*"):
        if path.is_symlink() or not path.is_file() or path.suffix.lower() not in _SOURCE_SUFFIXES:
            continue
        if any(part in _SKIP_DIRS for part in path.relative_to(package_root).parts):
            continue
        candidates.append((path, "hub/package/" + path.relative_to(package_root).as_posix()))
    return sorted(candidates, key=lambda entry: entry[1])


def _state_inventory(state_dir: Path) -> tuple[list[Path], list[Path]]:
    databases: list[Path] = []
    text_files: list[Path] = []
    for directory, dirs, names in os.walk(state_dir, followlinks=False):
        base = Path(directory)
        dirs[:] = [name for name in dirs if name not in _SKIP_DIRS and not (base / name).is_symlink()]
        for name in names:
            path = base / name
            if path.is_symlink() or not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix in _DATABASE_SUFFIXES:
                databases.append(path)
            elif suffix in _STATE_TEXT_SUFFIXES or ".log." in name:
                text_files.append(path)
    return sorted(databases), sorted(text_files)


def _runtime_manifest(config: dict[str, Any] | None) -> dict[str, Any]:
    versions: dict[str, str] = {}
    for distribution in ("local-ai-hub", "pyzipper", "cryptography", "pydantic", "fastapi"):
        try:
            versions[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            continue
    return {
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "sqlite_version": sqlite3.sqlite_version,
        "packages": versions,
        "configured_model_routes": _redact_config((config or {}).get("models", {})),
    }


def _check_limits(size: int, *, max_source_bytes: int, category: str) -> None:
    if size < 0 or size > max_source_bytes:
        raise ValueError(f"diagnostic {category} exceeds configured source limit ({max_source_bytes} bytes)")


def _snapshot_database(path: Path, destination: Path, *, cancelled: Callable[[], bool] | None) -> None:
    source = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=1.0)
    snapshot = sqlite3.connect(destination)
    started = time.monotonic()

    def progress(status: int, remaining: int, total: int) -> None:
        _cancelled(cancelled)
        if time.monotonic() - started > 300.0:
            raise TimeoutError(f"SQLite snapshot timed out: {path.name}")

    try:
        source.backup(snapshot, pages=256, progress=progress, sleep=0.01)
        snapshot.commit()
    finally:
        snapshot.close()
        source.close()


def _write_member(archive: Any, archive_path: Path, name: str, source_path: Path | None, data: bytes | None,
                  *, max_archive_bytes: int, cancelled: Callable[[], bool] | None) -> int:
    written = 0
    with archive.open(name, "w", force_zip64=True) as output:
        if data is not None:
            output.write(data)
            written = len(data)
        elif source_path is not None:
            with source_path.open("rb") as source:
                while True:
                    _cancelled(cancelled)
                    chunk = source.read(_COPY_CHUNK_SIZE)
                    if not chunk:
                        break
                    output.write(chunk)
                    written += len(chunk)
                    if archive_path.stat().st_size > max_archive_bytes:
                        raise ValueError(f"diagnostics archive exceeds configured limit ({max_archive_bytes} bytes)")
    if archive_path.stat().st_size > max_archive_bytes:
        raise ValueError(f"diagnostics archive exceeds configured limit ({max_archive_bytes} bytes)")
    return written


def create_diagnostics_archive(
    state_dir: Path | str,
    *,
    config: dict[str, Any] | None = None,
    source_root: Path | str | None = None,
    max_archive_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES,
    telemetry_flush_complete: bool = True,
    temp_dir: Path | str | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> DiagnosticArchive:
    """Build an installation-wide, encrypted, streamed support ZIP in temporary storage."""
    import pyzipper

    root = Path(state_dir).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("diagnostic state directory is unavailable")
    if isinstance(max_archive_bytes, bool) or not isinstance(max_archive_bytes, int) or max_archive_bytes < 1024:
        raise ValueError("diagnostics archive limit must be at least 1024 bytes")
    if isinstance(max_source_bytes, bool) or not isinstance(max_source_bytes, int) or max_source_bytes < 1:
        raise ValueError("diagnostics source limit must be positive")

    databases, state_files = _state_inventory(root)
    source_files = _source_files(source_root)
    for path in (*databases, *state_files, *(item[0] for item in source_files)):
        resolved = path.resolve(strict=True)
        expected_root = root if _inside(root, resolved) else (Path(source_root).resolve() if source_root else _repository_root(Path(__file__)))
        if expected_root is None or not _inside(expected_root, resolved):
            raise ValueError(f"diagnostic input escapes approved root: {path.name}")

    database_source_bytes = sum(
        path.stat().st_size
        + (path.with_name(path.name + "-wal").stat().st_size if path.with_name(path.name + "-wal").is_file() else 0)
        for path in databases
    )
    state_source_bytes = sum(path.stat().st_size for path in state_files)
    hub_source_bytes = sum(path.stat().st_size for path, _ in source_files)
    estimated_source_bytes = database_source_bytes + state_source_bytes + hub_source_bytes
    _check_limits(estimated_source_bytes, max_source_bytes=max_source_bytes, category="source data")

    temp = tempfile.TemporaryDirectory(prefix="local-ai-hub-export-", dir=str(temp_dir) if temp_dir else None)
    temp_root = Path(temp.name)
    archive_path = temp_root / "local-ai-hub-support.zip"
    try:
        free = shutil.disk_usage(temp_root).free
        snapshot_reserve = database_source_bytes
        archive_reserve = min(max_archive_bytes, estimated_source_bytes + 64 * 1024 * 1024)
        if free < snapshot_reserve + archive_reserve + 16 * 1024 * 1024:
            raise OSError("insufficient temporary disk space for complete diagnostics archive")

        password = __import__("secrets").token_urlsafe(32)
        entries: list[dict[str, Any]] = []
        source_total = 0
        with pyzipper.AESZipFile(
            archive_path,
            mode="w",
            compression=pyzipper.ZIP_BZIP2,
            compresslevel=9,
            allowZip64=True,
        ) as archive:
            archive.setpassword(password.encode("ascii"))
            archive.setencryption(pyzipper.WZ_AES, nbits=256)

            seen_core = set()
            for index, path in enumerate(databases):
                _cancelled(cancelled)
                relative = path.relative_to(root).as_posix()
                snapshot = temp_root / f"snapshot-{index}.sqlite3"
                _snapshot_database(path, snapshot, cancelled=cancelled)
                size = snapshot.stat().st_size
                source_total += size
                _check_limits(source_total, max_source_bytes=max_source_bytes, category="source data")
                archive_name = "state/" + relative
                member_bytes = _write_member(
                    archive, archive_path, archive_name, snapshot, None,
                    max_archive_bytes=max_archive_bytes, cancelled=cancelled,
                )
                entries.append({"name": archive_name, "category": "state_database", "status": "included", "bytes": member_bytes})
                snapshot.unlink(missing_ok=True)
                if path.name in _CORE_DATABASES:
                    seen_core.add(path.name)
            for filename in sorted(_CORE_DATABASES - seen_core):
                entries.append({"name": "state/" + filename, "category": "state_database", "status": "unavailable"})

            for path in state_files:
                _cancelled(cancelled)
                resolved = path.resolve(strict=True)
                if not _inside(root, resolved):
                    continue
                size = resolved.stat().st_size
                source_total += size
                _check_limits(source_total, max_source_bytes=max_source_bytes, category="source data")
                archive_name = "state/" + resolved.relative_to(root).as_posix()
                member_bytes = _write_member(
                    archive, archive_path, archive_name, resolved, None,
                    max_archive_bytes=max_archive_bytes, cancelled=cancelled,
                )
                entries.append({"name": archive_name, "category": "state_log_or_manifest", "status": "included", "bytes": member_bytes})

            config_bytes = json.dumps(_redact_config(config or {}), ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
            source_total += len(config_bytes)
            _check_limits(source_total, max_source_bytes=max_source_bytes, category="source data")
            config_name = "config/effective_config.redacted.json"
            _write_member(archive, archive_path, config_name, None, config_bytes,
                          max_archive_bytes=max_archive_bytes, cancelled=cancelled)
            entries.append({"name": config_name, "category": "redacted_effective_config", "status": "included", "bytes": len(config_bytes)})

            for path, archive_name in source_files:
                _cancelled(cancelled)
                resolved = path.resolve(strict=True)
                source_base = Path(source_root).resolve() if source_root is not None else _repository_root(Path(__file__))
                if source_base is None or not _inside(source_base, resolved):
                    continue
                size = resolved.stat().st_size
                source_total += size
                _check_limits(source_total, max_source_bytes=max_source_bytes, category="source data")
                member_bytes = _write_member(
                    archive, archive_path, archive_name, resolved, None,
                    max_archive_bytes=max_archive_bytes, cancelled=cancelled,
                )
                entries.append({"name": archive_name, "category": "hub_source", "status": "included", "bytes": member_bytes})

            manifest = {
                "format": "local-ai-hub-support",
                "version": 2,
                "exported_at": time.time(),
                "scope": "installation_all_projects",
                "compression": "BZIP2 level 9",
                "encryption": "WinZip AES-256",
                "zip64": True,
                "telemetry_flush_complete": bool(telemetry_flush_complete),
                "runtime": _runtime_manifest(config),
                "redacted_config": True,
                "included_files": len(entries),
                "source_files": sum(item["category"] == "hub_source" for item in entries),
                "source_bytes": source_total,
                "files": entries,
                "excluded_categories": ["environment secrets", "model weights", "other project source"],
                "debug_trace_note": "Request and response content is present only when detailed trace capture was enabled and retained; traces may contain private content.",
            }
            readme = (
                "Sensitive Local AI Hub support archive.\n"
                "Contains operational state and may include private request, response, path, task, or memory data.\n"
                "Configuration secrets are redacted. Model weights and other project source are excluded.\n"
                "Use a ZIP64 and WinZip AES compatible extractor such as 7-Zip.\n"
            ).encode("utf-8")
            manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
            for name, data in (("README.txt", readme), ("manifest.json", manifest_bytes)):
                _write_member(archive, archive_path, name, None, data,
                              max_archive_bytes=max_archive_bytes, cancelled=cancelled)
        _cancelled(cancelled)
        if archive_path.stat().st_size > max_archive_bytes:
            raise ValueError(f"diagnostics archive exceeds configured limit ({max_archive_bytes} bytes)")
        return DiagnosticArchive(temp, archive_path, password, manifest)
    except Exception:
        temp.cleanup()
        raise

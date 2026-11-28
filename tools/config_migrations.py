"""Versioned, recoverable migrations for the installed Hub TOML config."""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
import shutil
import tempfile
import tomllib
from pathlib import Path
from typing import Any

CURRENT_CONFIG_VERSION = 1
_TABLE_HEADER = re.compile(r"^\s*\[([^\[\]]+)\]\s*(?:#.*)?(?:\r?\n)?$")
_KEY_LINE = re.compile(r"^(\s*)([A-Za-z0-9_-]+)\s*=.*(?:\r?\n)?$")
_LEGACY_TABLES = {"debug_traces", "observability.debug_traces"}
_TRACE_SETTINGS = {
    "enabled", "retention_days", "terminal_ttl_seconds", "max_bytes", "max_sessions",
    "max_events_per_session", "max_event_bytes", "max_session_text_bytes",
    "max_detail_response_bytes", "cleanup_batch_size", "max_list_limit",
}
_TRACE_PRIMARY_SETTINGS = {"max_bytes", "terminal_ttl_seconds", "retention_days"}


class ConfigMigrationError(RuntimeError):
    """A config migration failed; any verified original backup remains available."""

    def __init__(self, message: str, backup_path: Path | None = None, backups: list[Path] | None = None) -> None:
        self.backup_path = backup_path
        self.backups = list(backups or ([] if backup_path is None else [backup_path]))
        suffix = f" Verified original config backup retained at {backup_path}." if backup_path else ""
        super().__init__(message + suffix)


def _parse(text: str, path: Path) -> dict[str, Any]:
    try:
        value = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigMigrationError(f"config migration refused invalid TOML at {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigMigrationError(f"config migration refused non-table TOML at {path}")
    return value


def _section_ranges(lines: list[str]) -> list[tuple[str, int, int]]:
    headers: list[tuple[str, int]] = []
    for index, line in enumerate(lines):
        match = _TABLE_HEADER.match(line)
        if match:
            headers.append((match.group(1).strip(), index))
    return [
        (name, start, headers[i + 1][1] if i + 1 < len(headers) else len(lines))
        for i, (name, start) in enumerate(headers)
    ]


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float) and math.isfinite(value):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{key} = {_toml_value(item)}" for key, item in value.items()) + " }"
    raise ConfigMigrationError(f"config migration cannot preserve TOML value of type {type(value).__name__}")


def _set_table_value(lines: list[str], table: str, key: str, value: Any) -> None:
    for name, start, end in _section_ranges(lines):
        if name != table:
            continue
        for index in range(start + 1, end):
            match = _KEY_LINE.match(lines[index])
            if match and match.group(2) == key:
                newline = "\r\n" if lines[index].endswith("\r\n") else "\n"
                lines[index] = f"{match.group(1)}{key} = {_toml_value(value)}{newline}"
                return
        newline = "\r\n" if any(line.endswith("\r\n") for line in lines) else "\n"
        insert_at = end
        lines.insert(insert_at, f"{key} = {_toml_value(value)}{newline}")
        return
    newline = "\r\n" if any(line.endswith("\r\n") for line in lines) else "\n"
    if lines and not lines[-1].endswith(("\n", "\r")):
        lines[-1] += newline
    if lines and lines[-1].strip():
        lines.append(newline)
    lines.extend([f"[{table}]{newline}", f"{key} = {_toml_value(value)}{newline}"])


def _remove_tables(lines: list[str], names: set[str]) -> None:
    for _name, start, end in reversed(_section_ranges(lines)):
        if _name in names:
            del lines[start:end]


def _remove_table_key(lines: list[str], table: str, key: str) -> None:
    for name, start, end in _section_ranges(lines):
        if name != table:
            continue
        for index in range(start + 1, end):
            match = _KEY_LINE.match(lines[index])
            if match and match.group(2) == key:
                del lines[index]
                return


def _migrate_v0_to_v1(text: str, data: dict[str, Any], path: Path) -> str:
    sections = _section_ranges(text.splitlines(keepends=True))
    unsupported = [name for name, _start, _end in sections
                   if any(name.startswith(f"{legacy}.") for legacy in _LEGACY_TABLES)]
    if unsupported:
        raise ConfigMigrationError(f"config migration found unsupported legacy tables: {', '.join(unsupported)}")

    top_level = data.get("debug_traces")
    observability = data.get("observability", {})
    nested = observability.get("debug_traces") if isinstance(observability, dict) else None
    if top_level is not None and not isinstance(top_level, dict):
        raise ConfigMigrationError("config migration requires [debug_traces] to be a table")
    if nested is not None and not isinstance(nested, dict):
        raise ConfigMigrationError("config migration requires [observability.debug_traces] to be a table")
    legacy = top_level if top_level else nested if nested else {}
    unknown = sorted(set(legacy) - _TRACE_SETTINGS)
    if unknown:
        raise ConfigMigrationError(f"config migration cannot map legacy debug_traces keys: {', '.join(unknown)}")

    telemetry = data.get("telemetry", {})
    if not isinstance(telemetry, dict):
        raise ConfigMigrationError("config migration requires [telemetry] to be a table")
    updates: dict[str, Any] = {}
    if legacy.get("enabled") is True:
        updates["mode"] = "full"
    elif legacy.get("enabled") is False and "mode" not in telemetry:
        updates["mode"] = "minimal"
    # The old store selected its entire legacy limits table unless one of the
    # canonical storage limits was already explicit in [telemetry].
    if not (_TRACE_PRIMARY_SETTINGS & set(telemetry)):
        updates.update({key: value for key, value in legacy.items() if key != "enabled"})

    lines = text.splitlines(keepends=True)
    for name, value in updates.items():
        _set_table_value(lines, "telemetry", name, value)
    _remove_tables(lines, _LEGACY_TABLES)
    _remove_table_key(lines, "features", "dashboard")
    _set_table_value(lines, "local_ai_hub", "config_schema_version", CURRENT_CONFIG_VERSION)
    migrated = "".join(lines)
    verified = _parse(migrated, path)
    if "debug_traces" in verified or (
        isinstance(verified.get("observability"), dict)
        and "debug_traces" in verified["observability"]
    ):
        raise ConfigMigrationError("config migration did not remove every retired debug_traces table")
    if verified.get("local_ai_hub", {}).get("config_schema_version") != CURRENT_CONFIG_VERSION:
        raise ConfigMigrationError("config migration did not write the current schema version")
    if isinstance(verified.get("features"), dict) and "dashboard" in verified["features"]:
        raise ConfigMigrationError("config migration did not remove the retired features.dashboard flag")
    return migrated


def _remove_retired_dashboard_feature(text: str, data: dict[str, Any], path: Path) -> str:
    features = data.get("features", {})
    if not isinstance(features, dict):
        raise ConfigMigrationError("config migration requires [features] to be a table")
    lines = text.splitlines(keepends=True)
    _remove_table_key(lines, "features", "dashboard")
    migrated = "".join(lines)
    verified = _parse(migrated, path)
    if isinstance(verified.get("features"), dict) and "dashboard" in verified["features"]:
        raise ConfigMigrationError("config migration did not remove the retired features.dashboard flag")
    return migrated


def _backup(path: Path, source_version: int) -> Path:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = path.with_name(f"{path.name}.backup-config-v{source_version}-{stamp}")
    shutil.copy2(path, backup)
    if backup.read_bytes() != path.read_bytes():
        backup.unlink(missing_ok=True)
        raise OSError("config backup verification failed")
    return backup


def _migrate_config_file(config_path: Path | str) -> dict[str, Any]:
    """Migrate one config document before the new runtime opens it."""
    path = Path(config_path)
    if not path.exists():
        return {"status": "absent", "version": CURRENT_CONFIG_VERSION, "backups": []}
    if path.is_symlink() or not path.is_file():
        raise ConfigMigrationError(f"config migration requires a regular file: {path}")
    text = path.read_text(encoding="utf-8")
    data = _parse(text, path)
    hub = data.get("local_ai_hub", {})
    if not isinstance(hub, dict):
        raise ConfigMigrationError("config migration requires [local_ai_hub] to be a table")
    raw_version = hub.get("config_schema_version", 0)
    if isinstance(raw_version, bool) or not isinstance(raw_version, int) or raw_version < 0:
        raise ConfigMigrationError("local_ai_hub.config_schema_version must be a non-negative integer")
    if raw_version > CURRENT_CONFIG_VERSION:
        raise ConfigMigrationError(
            f"config schema version {raw_version} is newer than supported version {CURRENT_CONFIG_VERSION}; config unchanged"
        )
    has_legacy = "debug_traces" in data or (
        isinstance(data.get("observability"), dict) and "debug_traces" in data["observability"]
    )
    features = data.get("features", {})
    has_retired_dashboard = isinstance(features, dict) and "dashboard" in features
    if raw_version == CURRENT_CONFIG_VERSION:
        if has_legacy:
            raise ConfigMigrationError("current config schema contains retired debug_traces tables; config unchanged")
        if has_retired_dashboard:
            migrated = _remove_retired_dashboard_feature(text, data, path)
        else:
            return {"status": "current", "version": CURRENT_CONFIG_VERSION, "backups": []}
    else:
        migrated = _migrate_v0_to_v1(text, data, path)
    backup: Path | None = None
    try:
        backup = _backup(path, raw_version)
        mode = path.stat().st_mode
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent,
                                         prefix=f".{path.name}.migrate-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(migrated)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        return {"status": "migrated", "version": CURRENT_CONFIG_VERSION, "backups": [str(backup)]}
    except Exception as exc:
        if backup is not None:
            raise ConfigMigrationError(f"config migration failed: {exc}", backup, [backup]) from exc
        raise ConfigMigrationError(f"config migration failed: {exc}") from exc


def run_config_migrations(config_path: Path | str) -> dict[str, Any]:
    """Migrate base and runtime override TOML before the new runtime opens either."""
    base = Path(config_path)
    paths = (base, base.with_name("config.runtime.toml"))
    backups: list[str] = []
    statuses: list[str] = []
    for path in dict.fromkeys(paths):
        try:
            result = _migrate_config_file(path)
        except ConfigMigrationError as exc:
            retained = [str(item) for item in exc.backups]
            raise ConfigMigrationError(str(exc), backups=[Path(item) for item in (*backups, *retained)]) from exc
        statuses.append(result["status"])
        backups.extend(result.get("backups", []))
    status = "migrated" if "migrated" in statuses else "current" if "current" in statuses else "absent"
    return {"status": status, "version": CURRENT_CONFIG_VERSION, "backups": backups}

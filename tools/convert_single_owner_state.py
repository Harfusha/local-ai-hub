#!/usr/bin/env python3
"""Offline, fail-closed inventory and narrow state conversion.

This utility is deliberately not imported by the running service. SQLite
conversion accepts only registered source/target schemas and explicitly
dispositioned structured records; unknown stores and unresolved transformations
fail closed.
"""
from __future__ import annotations

import argparse
import ast
import base64
from contextlib import closing
import hashlib
import importlib.util
import json
import math
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import tomllib
from pathlib import Path
from typing import Any

_RETIRED = {"tenant", "tenant_id", "tenant_key", "tenant_scope", "api_token_principal"}
_MAX_CONFIG_BYTES = 4 * 1024 * 1024
_MAX_SQLITE_BYTES = 512 * 1024 * 1024
_MAX_PROVENANCE_ENTRIES = 200_000
_MAX_PROVENANCE_VALUE_CHARS = 1024
_MAX_TABLES = 512
_MAX_ROWS = 1_000_000
_MAX_CONFIG_DEPTH = 64
_RETIRED_CONFIG_PATHS = {
    "$.security.api_token_tenant", "$.security.api_token_principal",
    "$.security.tenant_derivation_key", "$.security.users",
    "$.scheduler.max_queued_per_tenant", "$.scheduler.max_inflight_per_tenant",
    "$.browser_bridge.tenant", "$.rag.scope",
}

_STORE_DDL: dict[str, tuple[dict[str, str], tuple[str, ...]]] = {
    "artifacts": ({
        "artifacts": "CREATE TABLE artifacts (artifact_id TEXT PRIMARY KEY, created_at REAL NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL DEFAULT '', mime_type TEXT, encoding TEXT, blob BLOB, size_bytes INTEGER, checksum TEXT, identity_json TEXT)",
        "artifact_paging_metadata": "CREATE TABLE artifact_paging_metadata (artifact_id TEXT PRIMARY KEY, char_count INTEGER NOT NULL, section_json TEXT NOT NULL, section_checksum TEXT NOT NULL, page_text TEXT, nul_mask BLOB)",
    }, ("CREATE INDEX idx_artifacts_created ON artifacts(created_at)",)),
    "workspace_memos": ({
        "memos": "CREATE TABLE memos (workspace TEXT NOT NULL, memo_key TEXT NOT NULL, value TEXT NOT NULL, metadata TEXT NOT NULL, updated_at REAL NOT NULL, expires_at REAL NOT NULL, version INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(workspace, memo_key))",
        "memo_versions": "CREATE TABLE memo_versions (workspace TEXT NOT NULL, memo_key TEXT NOT NULL, version INTEGER NOT NULL, PRIMARY KEY(workspace, memo_key))",
    }, ("CREATE INDEX idx_memos_expiry ON memos(expires_at)",)),
    "request_journal": ({
        "requests": "CREATE TABLE requests (request_id TEXT PRIMARY KEY, action TEXT NOT NULL, payload_fingerprint TEXT NOT NULL DEFAULT '', state TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL, detail TEXT NOT NULL DEFAULT '', status_code INTEGER NOT NULL DEFAULT 0, response_json TEXT NOT NULL DEFAULT '')",
    }, ("CREATE INDEX idx_recovery_state ON requests(state, updated_at)", "CREATE INDEX idx_recovery_updated ON requests(updated_at DESC)")),
}
_ARTIFACT_SCHEMA_META_DDL = "CREATE TABLE artifact_schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"


def _literal_exports(path: Path, names: set[str]) -> dict[str, Any]:
    """Read named literal assignments without importing contract modules."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: dict[str, Any] = {}
    for node in tree.body:
        target = node.target if isinstance(node, ast.AnnAssign) else (node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1 else None)
        if isinstance(target, ast.Name) and target.id in names:
            result[target.id] = ast.literal_eval(node.value)
    missing = names - result.keys()
    if missing:
        raise ConversionError(f"static store contract is missing literal exports: {', '.join(sorted(missing))}")
    return result


def _load_local_module(path: Path, module_name: str):
    """Load one explicit offline helper without changing import search paths."""
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ConversionError(f"cannot load offline helper: {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        if sys.modules.get(module_name) is module:
            del sys.modules[module_name]
        raise
    return module


_SUPPLEMENTAL = _literal_exports(Path(__file__).with_name("single_owner_additional_store_contracts.py"),
                                  {"ADDITIONAL_STORE_DDL", "ADDITIONAL_RETIRED_COLUMNS", "ADDITIONAL_JSON_CONTAINERS"})
_AGENT_CONTRACTS = _literal_exports(Path(__file__).with_name("single_owner_agent_state_contracts.py"),
                                    {"STANDALONE_STORE_DDL", "AGENT_STATE_STORE_DDL", "UNSUPPORTED_STORE_METADATA",
                                     "RETIRED_COLUMNS", "ROW_TRANSFORMS_REQUIRED", "JSON_TRANSFORMS_REQUIRED"})
_COMPLETE_AGENT = _literal_exports(Path(__file__).with_name("single_owner_complete_agent_state_contract.py"),
                                   {"COMPLETE_AGENT_STATE_DDL", "GENERATED_OBJECT_HASHES", "SOURCE_OBJECT_HASHES",
                                    "RETIRED_ARCHIVE_TABLES", "PRESERVE_SQLITE_SEQUENCE_HIGH_WATER",
                                    "FTS_REBUILD_SOURCE", "FTS_REBUILD_FROM_METADATA_ONLY", "EXPECTED_OBJECT_SQL_HASHES",
                                    "LEGACY_SOURCE_OBJECT_HASHES", "LEGACY_SOURCE_REVISION"})
_HISTORICAL_STORE_CONTRACTS = _literal_exports(
    Path(__file__).with_name("single_owner_historical_store_contracts.py"),
    {"HISTORICAL_SOURCE_OBJECT_HASHES", "HISTORICAL_RETIRED_COLUMNS",
     "HISTORICAL_INDEX_ACTIONS", "HISTORICAL_ARTIFACT_PAGING"})
_STORE_DDL.update(_SUPPLEMENTAL["ADDITIONAL_STORE_DDL"])
_STORE_DDL.update(_AGENT_CONTRACTS["STANDALONE_STORE_DDL"])
_STORE_DDL.update(_AGENT_CONTRACTS["AGENT_STATE_STORE_DDL"])
_STORE_DDL["agent_state"] = (_COMPLETE_AGENT["COMPLETE_AGENT_STATE_DDL"]["tables"],
                             _COMPLETE_AGENT["COMPLETE_AGENT_STATE_DDL"]["indexes"])
_UNSUPPORTED_STORE_METADATA = _AGENT_CONTRACTS["UNSUPPORTED_STORE_METADATA"]
_JSON_CONTAINERS = _SUPPLEMENTAL["ADDITIONAL_JSON_CONTAINERS"]
_ROW_TRANSFORMS = _AGENT_CONTRACTS["ROW_TRANSFORMS_REQUIRED"]
_JSON_TRANSFORMS = _AGENT_CONTRACTS["JSON_TRANSFORMS_REQUIRED"]
_JSON_DISPOSITION_API = _load_local_module(Path(__file__).with_name("single_owner_json_dispositions.py"),
                                           "_single_owner_json_dispositions")
_WRITER_DISPOSITION_API = _load_local_module(Path(__file__).with_name("single_owner_writer_dispositions.py"),
                                             "_single_owner_writer_dispositions")
_REGISTRY_RETIRED_COLUMNS = {**_SUPPLEMENTAL["ADDITIONAL_RETIRED_COLUMNS"],
                             **_AGENT_CONTRACTS["RETIRED_COLUMNS"]}
_GENERATED_AGENT_HASHES = _COMPLETE_AGENT["GENERATED_OBJECT_HASHES"]
_SOURCE_AGENT_HASHES = {identity: digest for identity, digest in _COMPLETE_AGENT["LEGACY_SOURCE_OBJECT_HASHES"].items()
                        if identity not in _COMPLETE_AGENT["GENERATED_OBJECT_HASHES"]}
_EXPECTED_AGENT_HASHES = _COMPLETE_AGENT["EXPECTED_OBJECT_SQL_HASHES"]
_AGENT_ARCHIVE_TABLES = _COMPLETE_AGENT["RETIRED_ARCHIVE_TABLES"]
_SOURCE_COMPONENTS_SHA256_SCOPE = (
    "SHA-256 of canonical source-component metadata (filename, size, raw SHA-256 for main/WAL/SHM/journal); "
    "task-row SHA-256 is separately pinned"
)


class ConversionError(ValueError):
    pass


def _canonical_retired(key: object) -> bool:
    if not isinstance(key, str):
        return False
    normalized = key.strip().casefold().replace("-", "_")
    return normalized in _RETIRED or "tenant" in normalized.split("_")


def _remove_retired_config_fields(value: Any, path: str = "$", *, limit: int = _MAX_CONFIG_DEPTH) -> tuple[Any, list[dict[str, Any]]]:
    """Remove retired keys only from bounded operator configuration objects."""
    if limit <= 0:
        raise ConversionError("configuration exceeds bounded node limit")
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        removed: list[dict[str, Any]] = []
        for key, child in value.items():
            field_path = f"{path}.{key}"
            if field_path in _RETIRED_CONFIG_PATHS:
                removed.append({"path": field_path, "value": child})
                continue
            cleaned, nested = _remove_retired_config_fields(child, f"{path}.{key}", limit=limit - 1)
            out[key] = cleaned
            removed.extend(nested)
        return out, removed
    if isinstance(value, list):
        out = []
        removed: list[dict[str, Any]] = []
        for index, child in enumerate(value):
            cleaned, nested = _remove_retired_config_fields(child, f"{path}[{index}]", limit=limit - 1)
            out.append(cleaned)
            removed.extend(nested)
        return out, removed
    return value, []


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _publish_new_file(temporary: Path, target: Path) -> None:
    """Atomically create a new path without replacing a concurrent target."""
    os.link(temporary, target)
    temporary.unlink()


def _sqlite_source_fingerprint(source: Path) -> tuple[str, list[dict[str, Any]]]:
    components = []
    for path in (source, Path(str(source) + "-wal"), Path(str(source) + "-shm"), Path(str(source) + "-journal")):
        if path.exists():
            size = path.stat().st_size
            if sum(int(item["size_bytes"]) for item in components) + size > _MAX_SQLITE_BYTES:
                raise ConversionError("SQLite source and sidecars exceed the supported size bound")
            components.append({"name": path.name, "size_bytes": size, "sha256": _sha256(path)})
    digest = hashlib.sha256(json.dumps(components, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return digest.hexdigest(), components


def _copy_sqlite_snapshot(source: Path, directory: Path) -> tuple[Path, str, list[dict[str, Any]]]:
    """Copy the DB and active journal/WAL without opening the operator's files."""
    before_hash, before_components = _sqlite_source_fingerprint(source)
    if not before_components or before_components[0]["name"] != source.name:
        raise ConversionError("SQLite source is missing")
    copied_main = directory / source.name
    for component in before_components:
        name = str(component["name"])
        original = source if name == source.name else source.with_name(name)
        copied = directory / name
        if name.endswith("-shm"):
            # SHM is a transient coordination mapping; SQLite will create a private
            # one for the copied database. Never copy or open the source mapping.
            continue
        shutil.copyfile(original, copied)
        if _sha256(copied) != component["sha256"]:
            raise ConversionError("SQLite component changed while snapshotting; stop the service and retry")
    after_hash, after_components = _sqlite_source_fingerprint(source)
    if (before_hash, before_components) != (after_hash, after_components):
        raise ConversionError("SQLite source or sidecars changed during snapshot; stop the service and retry")
    return copied_main, before_hash, before_components


def inventory_sqlite(source: Path) -> dict[str, Any]:
    """Inspect a bounded private copy; do not let SQLite touch source sidecars."""
    deadline = time.monotonic() + 30.0
    with tempfile.TemporaryDirectory(prefix="single-owner-inventory-") as temp_dir:
      snapshot, source_hash_before, components_before = _copy_sqlite_snapshot(source, Path(temp_dir))
      try:
        connection = sqlite3.connect(snapshot, timeout=1.0)
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA busy_timeout=1000")
        connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        tables = connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name LIMIT ?",
            (_MAX_TABLES + 1,),
        ).fetchall()
        if len(tables) > _MAX_TABLES:
            raise ConversionError("database table count exceeds supported inventory bound")
        result = []
        total = 0
        for name, ddl in tables:
            quoted = '"' + str(name).replace('"', '""') + '"'
            columns = connection.execute(f"PRAGMA table_info({quoted})").fetchall()
            count = int(connection.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0])
            total += count
            if total > _MAX_ROWS:
                raise ConversionError("database row count exceeds supported inventory bound")
            retired = [str(col[1]) for col in columns if _canonical_retired(col[1])]
            primary_key = [str(col[1]) for col in sorted(columns, key=lambda col: int(col[5]) or 10**9) if int(col[5])]
            id_column = next((str(col[1]) for col in columns if str(col[1]).casefold() in {"id", "record_id", "artifact_id", "task_id", "session_id"}), None)
            identity_columns = [key for key in primary_key if not _canonical_retired(key)] or ([id_column] if id_column else [])
            collisions = []
            if identity_columns:
                key_fragments = ['"' + key.replace('"', '""') + '"' for key in identity_columns]
                key_sql = ", ".join(key_fragments)
                for tenant_column in retired:
                    tenant_sql = '"' + tenant_column.replace('"', '""') + '"'
                    found = connection.execute(
                        f"SELECT {key_sql}, COUNT(*), COUNT(DISTINCT {tenant_sql}) FROM {quoted} "
                        f"WHERE {tenant_sql} IS NOT NULL GROUP BY {key_sql} "
                        f"HAVING COUNT(DISTINCT {tenant_sql}) > 1 LIMIT 1001"
                    ).fetchall()
                    if len(found) > 1000:
                        raise ConversionError("collision inventory exceeds per-table bound")
                    for row in found:
                        key_values = list(row[:len(identity_columns)])
                        predicates = " AND ".join(f'{column} IS ?' for column in key_fragments)
                        tenant_values = connection.execute(
                            f"SELECT DISTINCT {tenant_sql} FROM {quoted} WHERE {predicates} LIMIT 257",
                            tuple(key_values),
                        ).fetchall()
                        if len(tenant_values) > 256:
                            raise ConversionError("collision tenant identity count exceeds per-record bound")
                        collisions.append({"tenant_column": tenant_column, "key": key_values,
                                           "tenant_values": [value[0] for value in tenant_values],
                                           "record_count": int(row[-2]), "tenant_count": int(row[-1])})
            result.append({
                "table": str(name),
                "rows": count,
                "columns": [str(col[1]) for col in columns],
                "retired_columns": retired,
                "primary_key": primary_key,
                "collision_identity_columns": identity_columns,
                "collisions": collisions,
                "schema_sha256": hashlib.sha256((ddl or "").encode("utf-8")).hexdigest(),
            })
        return {"source_sha256": source_hash_before, "source_components": components_before, "tables": result, "row_count": total,
                "collision_count": sum(len(table["collisions"]) for table in result)}
      except sqlite3.Error as exc:
        raise ConversionError(f"read-only SQLite inventory failed: {exc}") from exc
      finally:
        try:
            connection.close()
        except (NameError, sqlite3.Error):
            pass


def convert_config(source: Path, target: Path, *, expected_sha256: str | None = None) -> dict[str, Any]:
    """Write a separate JSON config target, preserving all non-retired values."""
    if source.resolve() == target.resolve():
        raise ConversionError("target must be separate from the source")
    provenance_target = target.with_name(target.name + ".conversion-provenance.json")
    if target.exists() or provenance_target.exists():
        raise ConversionError("target already exists; refusing overwrite")
    if source.stat().st_size > _MAX_CONFIG_BYTES:
        raise ConversionError("configuration exceeds supported size")
    source_hash = _sha256(source)
    if expected_sha256 is not None and expected_sha256 != source_hash:
        raise ConversionError("source changed since inventory; create a fresh plan")
    try:
        original = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConversionError(f"configuration is not readable UTF-8 JSON: {exc}") from exc
    if not isinstance(original, dict):
        raise ConversionError("only top-level JSON configuration objects are supported")
    converted, removed = _remove_retired_config_fields(original)
    payload = (json.dumps(converted, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    target.parent.mkdir(parents=False, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    provenance_temporary = provenance_target.with_name(provenance_target.name + ".tmp")
    if temporary.exists() or provenance_temporary.exists():
        raise ConversionError("temporary target already exists; refusing overwrite")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        target_hash = hashlib.sha256(payload).hexdigest()
        provenance = {"format": "single-owner-config-conversion-v1", "source_sha256": source_hash,
                      "target_sha256": target_hash, "removed_fields": removed}
        with provenance_temporary.open("xb") as stream:
            stream.write((json.dumps(provenance, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        if _sha256(source) != source_hash:
            raise ConversionError("source changed during conversion; create a fresh plan")
        if target.exists() or provenance_target.exists():
            raise ConversionError("target appeared during conversion; refusing overwrite")
        _publish_new_file(temporary, target)
        try:
            _publish_new_file(provenance_temporary, provenance_target)
        except Exception as exc:
            raise ConversionError(f"target published but provenance publication failed; preserve target and retry provenance separately: {exc}") from exc
    except Exception:
        for path in (temporary, provenance_temporary):
            try:
                path.unlink()
            except OSError:
                pass
        raise
    return {"source_sha256": source_hash, "target_sha256": target_hash,
            "provenance_path": str(provenance_target), "removed_paths": [item["path"] for item in removed]}


def convert_toml_config(source: Path, target: Path, *, expected_sha256: str | None = None) -> dict[str, Any]:
    """Remove only named retired TOML settings and verify every other value."""
    if source.resolve() == target.resolve() or target.exists():
        raise ConversionError("target must be separate from the source and must not already exist")
    provenance_target = target.with_name(target.name + ".conversion-provenance.json")
    if provenance_target.exists():
        raise ConversionError("provenance target already exists; refusing overwrite")
    if source.stat().st_size > _MAX_CONFIG_BYTES:
        raise ConversionError("configuration exceeds supported size")
    source_hash = _sha256(source)
    if expected_sha256 is not None and expected_sha256 != source_hash:
        raise ConversionError("source changed since inventory; create a fresh plan")
    try:
        text = source.read_text(encoding="utf-8")
        original = tomllib.loads(text)
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ConversionError(f"configuration is not readable UTF-8 TOML: {exc}") from exc
    expected, removed = _remove_retired_config_fields(original)
    kept_lines = []
    provenance_removed = []
    section: list[str] = []
    removing_users_block = False
    for line_number, line in enumerate(text.splitlines(keepends=True), 1):
        stripped = line.strip()
        if stripped.startswith("[[") and stripped.endswith("]]" ):
            section = [part.strip().strip('"\'') for part in stripped[2:-2].split(".")]
            removing_users_block = section[:2] == ["security", "users"]
            if not removing_users_block:
                kept_lines.append(line)
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            section = [part.strip().strip('"\'') for part in stripped[1:-1].split(".")]
            removing_users_block = section[:2] == ["security", "users"]
            if not removing_users_block:
                kept_lines.append(line)
            continue
        if removing_users_block:
            continue
        left, separator, right = line.partition("=")
        if not separator or not left.strip() or stripped.startswith("#"):
            kept_lines.append(line)
            continue
        key = left.strip().strip('"\'')
        dotted = section + [part.strip().strip('"\'') for part in key.split(".")]
        field_path = "$" + "".join(f".{part}" for part in dotted)
        if field_path not in _RETIRED_CONFIG_PATHS:
            kept_lines.append(line)
            continue
        try:
            parsed_value = tomllib.loads("value = " + right).get("value")
        except tomllib.TOMLDecodeError as exc:
            raise ConversionError(f"multiline or malformed retired TOML setting at line {line_number} is unsupported") from exc
        provenance_removed.append({"path": field_path, "value": parsed_value, "line": line_number})
    converted_text = "".join(kept_lines)
    try:
        converted = tomllib.loads(converted_text)
    except tomllib.TOMLDecodeError as exc:
        raise ConversionError("removing retired settings produced invalid TOML") from exc
    if converted != expected:
        raise ConversionError("TOML edit did not preserve all non-retired configuration values")
    recorded_paths = {item["path"] for item in provenance_removed}
    provenance_removed.extend(item for item in removed if item["path"] not in recorded_paths)
    encoded = converted_text.encode("utf-8")
    temporary = target.with_name(target.name + ".tmp")
    provenance_temporary = provenance_target.with_name(provenance_target.name + ".tmp")
    if temporary.exists() or provenance_temporary.exists():
        raise ConversionError("temporary target already exists; refusing overwrite")
    target_hash = hashlib.sha256(encoded).hexdigest()
    provenance = {"format": "single-owner-config-conversion-v1", "source_sha256": source_hash,
                  "target_sha256": target_hash, "removed_fields": provenance_removed}
    try:
        with temporary.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        with provenance_temporary.open("xb") as stream:
            stream.write((json.dumps(provenance, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        if _sha256(source) != source_hash or target.exists() or provenance_target.exists():
            raise ConversionError("source changed or target appeared during conversion; refusing overwrite")
        _publish_new_file(temporary, target)
        try:
            _publish_new_file(provenance_temporary, provenance_target)
        except Exception as exc:
            raise ConversionError(f"target published but provenance publication failed; preserve target and retry provenance separately: {exc}") from exc
    except Exception:
        for path in (temporary, provenance_temporary):
            try:
                path.unlink()
            except OSError:
                pass
        raise
    return {"source_sha256": source_hash, "target_sha256": target_hash,
            "provenance_path": str(provenance_target), "removed_paths": [item["path"] for item in provenance_removed]}


def validate_collision_manifest(inventory: dict[str, Any], manifest_path: Path) -> None:
    """Require an explicit preserve disposition for every colliding tenant value."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConversionError(f"collision manifest is not readable JSON: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("source_sha256") != inventory["source_sha256"]:
        raise ConversionError("collision manifest must bind to the inventoried source SHA-256")
    dispositions = manifest.get("dispositions")
    if not isinstance(dispositions, list):
        raise ConversionError("collision manifest requires a dispositions list")

    def identity(item: dict[str, Any]) -> str:
        try:
            return json.dumps(
                [item.get("table"), item.get("tenant_column"), item.get("key"), item.get("tenant_value")],
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            )
        except (TypeError, ValueError) as exc:
            raise ConversionError("collision identities must be JSON-serializable") from exc

    expected: set[str] = set()
    for table in inventory["tables"]:
        for collision in table["collisions"]:
            for tenant_value in collision["tenant_values"]:
                expected.add(identity({"table": table["table"], "tenant_column": collision["tenant_column"],
                                       "key": collision["key"], "tenant_value": tenant_value}))
    seen: set[str] = set()
    for item in dispositions:
        if not isinstance(item, dict) or item.get("disposition") != "preserve":
            raise ConversionError("each collision disposition must explicitly be preserve; merge/drop is unsupported")
        item_id = identity(item)
        if item_id in seen:
            raise ConversionError("duplicate collision disposition")
        seen.add(item_id)
    if seen != expected:
        raise ConversionError("collision manifest must disposition every and only colliding tenant identity")


def validate_archive_manifest(source_sha256: str, archive_tables: tuple[str, ...], manifest_path: Path | None) -> None:
    if manifest_path is None:
        raise ConversionError("retired schema tables require explicit --archive-disposition-manifest")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConversionError(f"archive disposition manifest is not readable JSON: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("source_sha256") != source_sha256:
        raise ConversionError("archive disposition manifest must bind to the inventoried source SHA-256")
    dispositions = manifest.get("dispositions")
    if not isinstance(dispositions, list):
        raise ConversionError("archive disposition manifest requires a dispositions list")
    expected = {(name, "archive_external") for name in archive_tables}
    actual = [{"table": item.get("table"), "disposition": item.get("disposition")}
              for item in dispositions if isinstance(item, dict)]
    normalized = [(item["table"], item["disposition"]) for item in actual]
    if len(actual) != len(dispositions) or len(set(normalized)) != len(expected) or set(normalized) != expected:
        raise ConversionError("archive dispositions must name every retired schema table exactly once as archive_external")


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _normalize_sql(sql: object) -> str:
    normalized = " ".join(str(sql or "").split())
    normalized = normalized.replace("CREATE INDEX IF NOT EXISTS ", "CREATE INDEX ")
    normalized = normalized.replace("CREATE UNIQUE INDEX IF NOT EXISTS ", "CREATE UNIQUE INDEX ")
    return normalized.rstrip(";")


def _canonical_index_contract(store: str) -> dict[tuple[str, str], tuple[Any, ...]]:
    ddl, indexes = _STORE_DDL[store]
    connection = sqlite3.connect(":memory:")
    try:
        for statement in ddl.values():
            connection.execute(statement)
        for statement in indexes:
            connection.execute(statement)
        contract: dict[tuple[str, str], tuple[Any, ...]] = {}
        for table, name, sql in connection.execute(
                "SELECT tbl_name, name, sql FROM sqlite_master WHERE type='index'"):
            listing = next(row for row in connection.execute(f"PRAGMA index_list({_quote(str(table))})") if str(row[1]) == str(name))
            xinfo = tuple(tuple(row) for row in connection.execute(f"PRAGMA index_xinfo({_quote(str(name))})"))
            contract[(str(table), str(name))] = (_normalize_sql(sql) if sql else None,
                int(listing[2]), str(listing[3]), int(listing[4]), xinfo)
        return contract
    finally:
        connection.close()


def _canonical_foreign_keys(store: str, table: str) -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(":memory:")
    try:
        for statement in _STORE_DDL[store][0].values():
            connection.execute(statement)
        rows = connection.execute(f"PRAGMA foreign_key_list({_quote(table)})").fetchall()
        return sorted(tuple(row) for row in rows)
    finally:
        connection.close()


def _normalized_index_xinfo(rows) -> tuple[tuple[Any, ...], ...]:
    """Represent indexed columns by name, retaining all other SQLite index flags."""
    normalized = []
    for seqno, cid, name, descending, collation, key in rows:
        identity = ("column", name) if int(cid) >= 0 else ("rowid",) if int(cid) == -1 else ("expression", int(cid))
        normalized.append((int(seqno), identity, name, int(descending), str(collation), int(key)))
    return tuple(normalized)


def _index_contract_matches_source(store: str, table: str, source_contract: tuple[Any, ...],
                                   target_contract: tuple[Any, ...], retired: list[str]) -> bool:
    source_sql, source_unique, source_origin, source_partial, source_xinfo = source_contract
    target_sql, target_unique, target_origin, target_partial, target_xinfo = target_contract
    # SQL text pins explicit indexes and all predicates/expressions; ordinal cids
    # are normalized by column name because removing unrelated fields shifts them.
    if source_sql is not None:
        return (source_sql == target_sql and source_unique == target_unique
                and source_origin == target_origin and source_partial == target_partial
                and _normalized_index_xinfo(source_xinfo) == _normalized_index_xinfo(target_xinfo))
    if target_sql is not None or source_unique != target_unique or source_origin != target_origin or source_partial != target_partial:
        return False
    rename_owner = store == "agent_state" and table in {"leases", "lease_waits"}
    def canonical_autoindex(rows, *, map_source: bool):
        result = []
        for row in rows:
            seqno, cid, name, descending, collation, key = row
            if map_source and int(key) and name in retired and not (rename_owner and name == "tenant"):
                continue
            mapped_name = "owner" if map_source and rename_owner and name == "tenant" else name
            identity = ("column", mapped_name) if int(cid) >= 0 else ("rowid",) if int(cid) == -1 else ("expression", int(cid))
            result.append((identity, mapped_name, int(descending), str(collation), int(key)))
        return tuple(result)
    return canonical_autoindex(source_xinfo, map_source=True) == canonical_autoindex(target_xinfo, map_source=False)


def _transform_requirements(store: str, tables: list[dict[str, Any]]) -> list[str]:
    names = {str(item["table"]) for item in tables}
    reasons: list[str] = []
    if store == "agent_state":
        for transform in _ROW_TRANSFORMS:
            affected = set(transform.get("tables", ()))
            if transform.get("table"):
                affected.add(str(transform["table"]))
            transform_tables = set(transform.get("tables", ()))
            fence_scoped = bool(transform_tables) and transform_tables <= {"writer_fence_leases", "writer_fence_attempts"}
            if (affected & names and transform.get("table") != "agent_swarms"
                    and transform.get("table") not in {"leases", "lease_waits"} and not fence_scoped):
                reasons.append(f"{', '.join(sorted(affected & names))}: {transform['requires']}")
    disposition_selectors = {
        ("agent_memory_records", "provenance"),
        ("agent_tasks_projection", "checkpoint"),
        ("agent_snapshots", "state"),
        ("agent_tasks_projection", "context"),
        ("agent_verification_receipts", "details"),
    }
    for transform in _JSON_TRANSFORMS:
        table = str(transform.get("table", ""))
        column = str(transform.get("column", "<json>"))
        if table in names and not (store == "agent_state" and (table, column) in disposition_selectors):
            reasons.append(f"{table}.{column}: {transform['rule']}")
    return list(dict.fromkeys(reasons))


def _registered_agent_table_names() -> set[str]:
    return {
        name for kind, name, _table in (set(_SOURCE_AGENT_HASHES) | set(_GENERATED_AGENT_HASHES))
        if kind == "table" and not name.startswith("sqlite_")
    } | set(_AGENT_ARCHIVE_TABLES)


def _agent_object_sql_sha256(sql: Any) -> str:
    """Hash pinned Agent State SQL using the runtime's whitespace/case rule."""
    return hashlib.sha256(" ".join(str(sql).split()).casefold().encode("utf-8")).hexdigest()


def _matches_source_agent_sql_pin(sql: Any, expected: Any) -> bool:
    """Match one legacy source SQL fingerprint or its explicitly pinned variants."""
    actual = _agent_object_sql_sha256(sql)
    if type(expected) is str:
        return actual == expected
    if type(expected) in (tuple, list, set, frozenset):
        return bool(expected) and all(type(value) is str for value in expected) and actual in expected
    return False


def _known_unsupported_store(table_names: set[str]) -> dict[str, Any] | None:
    metadata = _UNSUPPORTED_STORE_METADATA.get("agent_state")
    agent_tables = _registered_agent_table_names()
    if any(name.startswith("agent_") for name in table_names) and table_names != agent_tables:
        return {**(metadata or {}),
                "reason": "Agent State object set is partial or contains unregistered objects; source-exact conversion is unavailable",
                "required_objects": tuple(sorted(agent_tables)),
                "extra_objects": tuple(sorted(table_names - agent_tables)),
                "missing_objects": tuple(sorted(agent_tables - table_names))}
    return None


def _canonical_store_object_hashes(store: str) -> dict[tuple[str, str], str]:
    """Build exact canonical input pins from this converter's target DDL."""
    tables, indexes = _STORE_DDL[store]
    memory = sqlite3.connect(":memory:")
    try:
        for ddl in tables.values():
            memory.execute(ddl)
        for ddl in indexes:
            memory.execute(ddl)
        return {
            (str(kind), str(name)): _agent_object_sql_sha256(sql)
            for kind, name, sql in memory.execute(
                "SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' "
                "AND type IN ('table','index')")
        }
    finally:
        memory.close()


def _source_store_shape(connection: sqlite3.Connection) -> tuple[str, dict[str, list[str]], list[dict[str, Any]]]:
    objects = connection.execute(
        "SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' AND type IN ('table','view','trigger')"
    ).fetchall()
    tables = {str(name) for kind, name in objects if kind == "table"}
    if any(kind != "table" for kind, _ in objects):
        raise ConversionError("SQLite store contains a view or trigger; schema is unsupported")
    artifact_tables = set(_STORE_DDL["artifacts"][0]) | {"artifact_schema_meta"}
    matching = []
    for name, (ddl, _) in _STORE_DDL.items():
        if not ddl:
            continue
        if name == "artifacts":
            expected_tables = artifact_tables
            if tables == set(ddl):
                matching.append(name)
                continue
        elif name == "agent_state":
            expected_tables = _registered_agent_table_names()
        else:
            expected_tables = set(ddl)
        if tables == expected_tables:
            matching.append(name)
    if len(matching) != 1:
        raise ConversionError("SQLite table set is unknown; exact registered source schemas include artifacts, workspace memos, request journals, and Agent State")
    store = matching[0]
    # Agent State has its own complete historical source pins below.
    historical_source = store == "agent_state"
    if any(source_store == store for source_store, _kind, _name
           in _HISTORICAL_STORE_CONTRACTS["HISTORICAL_SOURCE_OBJECT_HASHES"]):
        expected_source = {
            (kind, name): digest
            for (source_store, kind, name), digest
            in _HISTORICAL_STORE_CONTRACTS["HISTORICAL_SOURCE_OBJECT_HASHES"].items()
            if source_store == store
        }
        actual_source = {
            (str(kind), str(name)): _agent_object_sql_sha256(sql)
            for kind, name, sql in connection.execute(
                "SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' AND type IN ('table','index')")
        }
        canonical_source = _canonical_store_object_hashes(store)
        if actual_source == expected_source:
            historical_source = True
        elif actual_source != canonical_source:
            extra = sorted(set(actual_source) - set(expected_source))
            missing = sorted(set(expected_source) - set(actual_source))
            mismatched = sorted(key for key in set(actual_source) & set(expected_source)
                                if actual_source[key] != expected_source[key])
            raise ConversionError(
                f"{store} source object fingerprints differ from registered historical schema; "
                f"extra={extra!r}; missing={missing!r}; mismatched={mismatched!r}")
    target_tables, _ = _STORE_DDL[store]
    removed: dict[str, list[str]] = {}
    inventory_tables: list[dict[str, Any]] = []
    if store == "agent_state":
        if connection.execute("PRAGMA user_version").fetchone()[0] != _COMPLETE_AGENT["COMPLETE_AGENT_STATE_DDL"]["user_version"]:
            raise ConversionError("Agent State source user_version differs from the registered complete contract")
        source_objects = {(str(kind), str(name), str(tbl_name)): sql for kind, name, tbl_name, sql in
                          connection.execute("SELECT type, name, tbl_name, sql FROM sqlite_master WHERE type IN ('table','index')")}
        for identity, expected_hash in _SOURCE_AGENT_HASHES.items():
            sql = source_objects.get(identity)
            if sql is None or not _matches_source_agent_sql_pin(sql, expected_hash):
                raise ConversionError(f"agent_state source object pin mismatch: {identity}")
        expected_named_objects = set(_SOURCE_AGENT_HASHES) | set(_GENERATED_AGENT_HASHES)
        actual_named_objects = {identity for identity, sql in source_objects.items()
                                if sql is not None and not str(identity[1]).startswith("sqlite_autoindex")}
        if actual_named_objects != expected_named_objects:
            extra = sorted(actual_named_objects - expected_named_objects)
            missing = sorted(expected_named_objects - actual_named_objects)
            raise ConversionError(
                f"Agent State source object set differs from complete source pins; extra={extra!r}; missing={missing!r}")
        for archive_table in _AGENT_ARCHIVE_TABLES:
            qarchive = _quote(archive_table)
            archive_ddl = connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (archive_table,)).fetchone()
            if archive_ddl is None:
                raise ConversionError(f"required archived table is missing: {archive_table}")
            archive_identity = ("table", archive_table, archive_table)
            if archive_identity not in _SOURCE_AGENT_HASHES or not _matches_source_agent_sql_pin(
                    archive_ddl[0], _SOURCE_AGENT_HASHES[archive_identity]):
                raise ConversionError(f"archived table DDL pin mismatch: {archive_table}")
            info = connection.execute(f"PRAGMA table_info({qarchive})").fetchall()
            count = int(connection.execute(f"SELECT COUNT(*) FROM {qarchive}").fetchone()[0])
            removed[archive_table] = []
            inventory_tables.append({"table": archive_table, "rows": count,
                "columns": [str(row[1]) for row in info], "retired_columns": [],
                "primary_key": [str(row[1]) for row in sorted(info, key=lambda row: int(row[5]) or 10**9) if int(row[5])],
                "collisions": [], "archive_only": True, "source_sql": str(archive_ddl[0])})
    if store == "artifacts" and historical_source:
        marker_ddl = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='artifact_schema_meta'"
        ).fetchone()
        normalize = lambda sql: " ".join(str(sql).casefold().replace('"', '').split())
        if not marker_ddl or normalize(marker_ddl[0]) != normalize(_ARTIFACT_SCHEMA_META_DDL):
            raise ConversionError("unsupported artifact schema marker definition")
        meta_info = connection.execute("PRAGMA table_info(artifact_schema_meta)").fetchall()
        meta_contract = [(str(row[1]), str(row[2]).upper(), int(row[3]), row[4], int(row[5])) for row in meta_info]
        if meta_contract != [("key", "TEXT", 0, None, 1), ("value", "TEXT", 1, None, 0)]:
            raise ConversionError("unsupported artifact schema marker table")
        markers = connection.execute("SELECT key, value FROM artifact_schema_meta ORDER BY key LIMIT 2").fetchall()
        if markers != [("tenant_storage", "sha256-v1")]:
            raise ConversionError("unknown artifact schema markers; refusing conversion")
        removed["artifact_schema_meta"] = ["tenant_storage"]
    for table, target_ddl in target_tables.items():
        qtable = _quote(table)
        source_info = connection.execute(f"PRAGMA table_info({qtable})").fetchall()
        source_columns = [str(row[1]) for row in source_info]
        registered_retired = set(_REGISTRY_RETIRED_COLUMNS.get(table, ()))
        registered_retired.update(_HISTORICAL_STORE_CONTRACTS["HISTORICAL_RETIRED_COLUMNS"].get(store, {}).get(table, ()))
        retired = [column for column in source_columns if column in registered_retired or _canonical_retired(column)
                   or (store == "request_journal" and table == "requests" and column == "identity")]
        for row in source_info:
            if str(row[1]) in retired and str(row[2]).upper() != "TEXT":
                raise ConversionError(f"unsupported non-text retired identity in {store}.{table}")
        memory = sqlite3.connect(":memory:")
        try:
            memory.execute(target_ddl)
            target_info = memory.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
        finally:
            memory.close()
        target_columns = [str(row[1]) for row in target_info]
        historical_mapping = (historical_source and store == "artifacts" and table == "artifact_paging_metadata"
                              and source_columns == list(_HISTORICAL_STORE_CONTRACTS["HISTORICAL_ARTIFACT_PAGING"]["legacy_columns"]))
        writer_rename = (store == "agent_state" and table in {"leases", "lease_waits"}
                         and "tenant" in retired and "owner" in target_columns)
        mapped_columns = ["owner" if writer_rename and column == "tenant" else
                          "section_json" if historical_mapping and column == "section_names" else column
                          for column in source_columns if column not in retired or writer_rename and column == "tenant"]
        telemetry_reorder = historical_source and store == "telemetry" and table == "events"
        if historical_mapping:
            columns_match = tuple(mapped_columns) == ("artifact_id", "char_count", "section_json", "page_text", "nul_mask")
            # The source has no checksum column; conversion creates it from the exact metadata bytes.
            columns_match = columns_match and "section_checksum" in target_columns
        elif telemetry_reorder:
            columns_match = set(mapped_columns) == set(target_columns) and len(mapped_columns) == len(target_columns)
        else:
            columns_match = mapped_columns == target_columns
        if not columns_match:
            raise ConversionError(f"unsupported {store}.{table} columns; only exact canonical fields plus registered retired identity columns are supported")
        target_contract = {str(row[1]): (str(row[2]).upper(), int(row[3]), row[4]) for row in target_info}
        for row in source_info:
            column = str(row[1])
            if column in retired:
                if store == "agent_state" and table in {"leases", "lease_waits"} and column == "tenant":
                    if ("owner" not in target_contract
                            or (str(row[2]).upper(), int(row[3]), row[4]) != target_contract["owner"]):
                        raise ConversionError(f"unsupported {store}.{table}.tenant definition for explicit owner mapping")
                continue
            target_name = "section_json" if historical_mapping and column == "section_names" else column
            contract = (str(row[2]).upper(), int(row[3]), row[4])
            if target_name not in target_contract or contract != target_contract[target_name]:
                raise ConversionError(f"unsupported {store}.{table}.{column} definition")
        target_pk = [str(row[1]) for row in sorted(target_info, key=lambda row: int(row[5]) or 10**9) if int(row[5])]
        source_pk = [str(row[1]) for row in sorted(source_info, key=lambda row: int(row[5]) or 10**9) if int(row[5])]
        writer_pk_match = False
        if store == "agent_state" and table in {"leases", "lease_waits"} and "tenant" in retired:
            if table == "leases":
                writer_pk_match = [column for column in source_pk if column != "tenant"] == target_pk
            else:
                writer_pk_match = ["owner" if column == "tenant" else column for column in source_pk] == target_pk
        if source_pk != target_pk and not writer_pk_match and not any(
            len(source_pk) == len(target_pk) + 1 and set(source_pk) == set(target_pk + [tenant_column])
            for tenant_column in retired
        ):
            raise ConversionError(f"unsupported {store}.{table} primary key; cannot prove target uniqueness")
        source_foreign_keys = sorted(tuple(row) for row in connection.execute(f"PRAGMA foreign_key_list({qtable})").fetchall())
        if source_foreign_keys != _canonical_foreign_keys(store, table):
            raise ConversionError(f"unsupported foreign-key contract in {store}.{table}")
        removed[table] = retired
        count = int(connection.execute(f"SELECT COUNT(*) FROM {qtable}").fetchone()[0])
        inventory_tables.append({"table": table, "rows": count, "columns": source_columns,
                                 "retired_columns": retired, "primary_key": source_pk, "collisions": []})

    # Every source object is fingerprint-pinned. A small registry maps only
    # those exact historical indexes whose tenant key is removed or renamed.
    if sum(item["rows"] * len(item["retired_columns"]) for item in inventory_tables) > _MAX_PROVENANCE_ENTRIES:
        raise ConversionError("removed-field provenance exceeds supported record bound")

    expected_indexes = _canonical_index_contract(store)
    seen_expected_indexes: set[tuple[str, str]] = set()
    historical_actions = (_HISTORICAL_STORE_CONTRACTS["HISTORICAL_INDEX_ACTIONS"].get(store, {})
                          if historical_source else {})
    for table in target_tables:
        for row in connection.execute(f"PRAGMA index_list({_quote(table)})").fetchall():
            name = str(row[1])
            index_sql = connection.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name=?", (name,)).fetchone()
            source_xinfo = tuple(tuple(item) for item in connection.execute(f"PRAGMA index_xinfo({_quote(name)})"))
            source_contract = (_normalize_sql(index_sql[0]) if index_sql and index_sql[0] else None,
                               int(row[2]), str(row[3]), int(row[4]), source_xinfo)
            action = historical_actions.get(name)
            if action is not None:
                action_kind, target_name, removed_column, *rename = action
                if action_kind == "drop":
                    continue  # Exact source fingerprint above authorizes only this retired index.
                key = (table, target_name)
                target_contract = expected_indexes.get(key)
                if target_contract is None:
                    raise ConversionError(f"historical index {name} has no registered canonical target")
                rename_to = rename[0] if rename else None
                transformed_xinfo = []
                for item in source_xinfo:
                    seqno, cid, column_name, descending, collation, is_key = item
                    if int(is_key) and column_name == removed_column and rename_to is None:
                        continue
                    mapped_name = rename_to if int(is_key) and column_name == removed_column else column_name
                    mapped_cid = -2 if int(cid) == -2 else int(cid)
                    identity = (("column", mapped_name) if mapped_cid >= 0 else
                                ("rowid",) if mapped_cid == -1 else ("expression", mapped_cid))
                    transformed_xinfo.append((identity, mapped_name, int(descending), str(collation), int(is_key)))
                target_xinfo = _normalized_index_xinfo(target_contract[4])
                if (int(row[2]) != target_contract[1] or str(row[3]) != target_contract[2]
                        or int(row[4]) != target_contract[3]
                        or tuple(transformed_xinfo) != tuple(item[1:] for item in target_xinfo)):
                    raise ConversionError(f"historical index {name} does not map exactly to its registered target contract")
                if key in seen_expected_indexes:
                    raise ConversionError(f"multiple source indexes map to canonical index {target_name}")
                seen_expected_indexes.add(key)
                continue
            key = (table, name)
            if key not in expected_indexes:
                raise ConversionError(f"unsupported extra index {name}; source remains unchanged")
            if not _index_contract_matches_source(store, table, source_contract,
                                                  expected_indexes[key], removed.get(table, [])):
                raise ConversionError(f"index {name} differs from its full canonical contract; retired-column rewrite is unsupported")
            seen_expected_indexes.add(key)
    if seen_expected_indexes != set(expected_indexes):
        raise ConversionError("source is missing a required canonical index")
    return store, removed, inventory_tables


def _store_collisions(connection: sqlite3.Connection, store: str, removed: dict[str, list[str]],
                      tables: list[dict[str, Any]], *, ignore_tables: set[str] | None = None) -> None:
    target_tables, _ = _STORE_DDL[store]
    for item in tables:
        if item["table"] in (ignore_tables or set()):
            continue
        tenant_columns = removed[item["table"]]
        if not tenant_columns:
            continue
        memory = sqlite3.connect(":memory:")
        try:
            memory.execute(target_tables[item["table"]])
            target_info = memory.execute(f"PRAGMA table_info({_quote(item['table'])})").fetchall()
        finally:
            memory.close()
        keys = [str(row[1]) for row in sorted(target_info, key=lambda row: int(row[5]) or 10**9) if int(row[5])]
        if not keys:
            raise ConversionError(f"{store}.{item['table']} has no canonical identity key")
        key_sql = ", ".join(_quote(key) for key in keys)
        duplicate_groups = connection.execute(
            f"SELECT {key_sql}, COUNT(*) FROM {_quote(item['table'])} GROUP BY {key_sql} HAVING COUNT(*) > 1 LIMIT 1001"
        ).fetchall()
        if len(duplicate_groups) > 1000:
            raise ConversionError("target-key collision inventory exceeds per-table bound")
        for tenant in tenant_columns:
            qtenant = _quote(tenant)
            groups = connection.execute(
                f"SELECT {key_sql} FROM {_quote(item['table'])} GROUP BY {key_sql} "
                f"HAVING COUNT(DISTINCT {qtenant}) > 1 LIMIT 1001"
            ).fetchall()
            if len(groups) > 1000:
                raise ConversionError("collision inventory exceeds per-table bound")
            for group in groups:
                predicate = " AND ".join(f"{_quote(key)} IS ?" for key in keys)
                identities = connection.execute(
                    f"SELECT DISTINCT {qtenant} FROM {_quote(item['table'])} WHERE {predicate} LIMIT 257",
                    tuple(group),
                ).fetchall()
                if len(identities) > 256:
                    raise ConversionError("collision tenant identity count exceeds per-record bound")
                item["collisions"].append({"tenant_column": tenant, "key": list(group),
                                            "tenant_values": [identity[0] for identity in identities],
                                            "record_count": len(identities), "tenant_count": len(identities)})
        cross_tenant_keys = {tuple(collision["key"]) for collision in item["collisions"]}
        if any(tuple(group[:len(keys)]) not in cross_tenant_keys for group in duplicate_groups):
            raise ConversionError(f"same-tenant or null-tenant duplicate identity in {item['table']}; explicit remapping is unsupported")


def _preflight_historical_unique_indexes(connection: sqlite3.Connection, store: str) -> None:
    """Reject collisions under the exact target indexes before target creation."""
    if store != "async_jobs":
        return
    checks = (
        ("idx_async_jobs_active_dedupe",
         "SELECT request_hash FROM async_jobs WHERE state IN ('queued','running') "
         "GROUP BY request_hash HAVING COUNT(*)>1 LIMIT 1"),
        ("idx_async_jobs_request_id",
         "SELECT json_extract(payload_json, '$.request_id') FROM async_jobs "
         "WHERE json_valid(payload_json) AND json_type(payload_json, '$.request_id')='text' "
         "AND json_extract(payload_json, '$.request_id')<>'' "
         "GROUP BY json_extract(payload_json, '$.request_id') HAVING COUNT(*)>1 LIMIT 1"),
    )
    for index_name, query in checks:
        if connection.execute(query).fetchone() is not None:
            raise ConversionError(
                f"historical async rows collide under target UNIQUE index {index_name}; "
                "explicit key remapping is unsupported")


def _verify_store_relations(connection: sqlite3.Connection, store: str) -> None:
    if store == "artifacts":
        missing = connection.execute(
            "SELECT 1 FROM artifact_paging_metadata AS p LEFT JOIN artifacts AS a "
            "ON a.artifact_id=p.artifact_id WHERE a.artifact_id IS NULL LIMIT 1"
        ).fetchone()
        if missing:
            raise ConversionError("artifact paging metadata has an orphaned artifact ID")
    elif store == "workspace_memos":
        missing = connection.execute(
            "SELECT 1 FROM memos AS m LEFT JOIN memo_versions AS v "
            "ON v.workspace=m.workspace AND v.memo_key=m.memo_key "
            "WHERE v.memo_key IS NULL LIMIT 1"
        ).fetchone()
        if missing:
            raise ConversionError("workspace memo is missing its version record")


def _row_hash(connection: sqlite3.Connection, table: str, columns: list[str], keys: list[str],
              replacements: dict[tuple[tuple[Any, ...], str], Any] | None = None) -> str:
    digest = hashlib.sha256()
    order = ", ".join(_quote(key) for key in keys)
    with closing(connection.execute(f"SELECT {', '.join(_quote(column) for column in columns)} FROM {_quote(table)} ORDER BY {order}")) as cursor:
        for row in cursor:
            if replacements:
                identity = tuple(row[columns.index(key)] for key in keys)
                row = tuple(replacements.get((identity, column), value) for column, value in zip(columns, row))
            encoded = []
            for value in row:
                if isinstance(value, bytes):
                    encoded.append({"blob_b64": base64.b64encode(value).decode("ascii")})
                else:
                    encoded.append(value)
            digest.update(json.dumps(encoded, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"))
            digest.update(b"\n")
    return digest.hexdigest()


def _historical_store_row_transforms(
    connection: sqlite3.Connection, store: str, tables: list[dict[str, Any]],
) -> tuple[dict[tuple[str, tuple[Any, ...]], dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    """Preflight the one typed historical row transform before target creation."""
    if store != "artifacts":
        return {}, [], {}
    item = next((record for record in tables if record["table"] == "artifact_paging_metadata"), None)
    if item is None or "section_names" not in item["columns"]:
        return {}, [], {}
    contract = _HISTORICAL_STORE_CONTRACTS["HISTORICAL_ARTIFACT_PAGING"]
    columns = list(item["columns"])
    target_columns = list(contract["target_columns"])
    if tuple(columns) != tuple(contract["legacy_columns"]):
        raise ConversionError("artifact paging metadata source columns differ from the pinned historical layout")
    replacements: dict[tuple[str, tuple[Any, ...]], dict[str, Any]] = {}
    provenance: list[dict[str, Any]] = []
    digest = hashlib.sha256()
    deadline = time.monotonic() + 30.0
    with closing(connection.execute(
        "SELECT artifact_id,char_count,section_names,page_text,nul_mask "
        "FROM artifact_paging_metadata ORDER BY artifact_id")) as cursor:
        for row_number, values in enumerate(cursor, 1):
            if row_number > _MAX_ROWS or time.monotonic() >= deadline:
                raise ConversionError("artifact section metadata preflight exceeded its bounded scan")
            artifact_id, char_count, raw, page_text, nul_mask = values
            if (type(artifact_id) is not str or not artifact_id or type(raw) is not str
                    or len(raw.encode("utf-8")) > _MAX_STRUCTURED_JSON_CHARS):
                raise ConversionError("artifact section metadata row has an invalid or oversized identity/value")
            def unique_pairs(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("duplicate metadata key")
                    result[key] = value
                return result
            try:
                parsed = json.loads(raw, object_pairs_hook=unique_pairs)
            except (TypeError, ValueError, RecursionError) as exc:
                raise ConversionError(f"artifact {artifact_id!r} has malformed historical section_names metadata") from exc
            names = parsed.get("names") if isinstance(parsed, dict) else None
            truncated = parsed.get("truncated") if isinstance(parsed, dict) else None
            if (not isinstance(parsed, dict) or set(parsed) != {"names", "truncated"}
                    or not isinstance(names, list) or len(names) > int(contract["maximum_names"])
                    or any(type(name) is not str or len(name) > int(contract["maximum_name_chars"]) for name in names)
                    or len(set(names)) != len(names) or type(truncated) is not bool):
                raise ConversionError(f"artifact {artifact_id!r} has unsupported historical section_names values")
            section_json = json.dumps(
                {"artifact_id": artifact_id, "names": names, "truncated": truncated},
                ensure_ascii=False, separators=(",", ":"),
            )
            section_checksum = hashlib.sha256(section_json.encode("utf-8")).hexdigest()
            replacements[("artifact_paging_metadata", (artifact_id,))] = {
                "section_json": section_json,
                "section_checksum": section_checksum,
            }
            if len(provenance) >= _MAX_PROVENANCE_ENTRIES:
                raise ConversionError("artifact section metadata provenance exceeds supported row bound")
            source_row_sha256 = hashlib.sha256(json.dumps(
                [artifact_id, char_count, raw, page_text,
                 {"blob_b64": base64.b64encode(nul_mask).decode("ascii")} if isinstance(nul_mask, bytes) else nul_mask],
                ensure_ascii=False, separators=(",", ":"), allow_nan=False,
            ).encode("utf-8")).hexdigest()
            provenance.append({"store": store, "table": "artifact_paging_metadata", "artifact_id": artifact_id,
                               "removed_field": "section_names", "removed_value": {"type": "text", "value": raw},
                               "source_row_sha256": source_row_sha256,
                               "target_section_json_sha256": hashlib.sha256(section_json.encode("utf-8")).hexdigest()})
            row_values = {"artifact_id": artifact_id, "char_count": char_count, "section_json": section_json,
                          "section_checksum": section_checksum, "page_text": page_text, "nul_mask": nul_mask}
            encoded = [{"blob_b64": base64.b64encode(value).decode("ascii")} if isinstance(value, bytes) else value
                       for value in (row_values[column] for column in target_columns)]
            digest.update(json.dumps(encoded, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"))
            digest.update(b"\n")
    return replacements, provenance, {"artifact_paging_metadata": digest.hexdigest()}


_AGENT_JSON_CONTRACTS = {
    ("agent_memory_records", "provenance", "record_id"),
    ("agent_tasks_projection", "context", "task_id"),
    ("agent_tasks_projection", "checkpoint", "task_id"),
    ("agent_snapshots", "state", "snapshot_id"),
    ("agent_verification_receipts", "details", "receipt_id"),
}
_JSON_RETIRED_KEYS = {"tenant", "tenant_id", "tenant_identity", "tenant_key", "tenant_scope", "tenant_partition"}
_RECEIPT_METADATA_SCHEMA = "verification_receipt_metadata.v1"
_RECEIPT_EVIDENCE_TYPES = {"test", "benchmark", "source_review"}
_ASYNC_RETIRED_JSON_KEYS = {"tenant", "tenant_id", "tenant_key", "tenant_scope"}
_TELEMETRY_RETIRED_JSON_KEYS = _ASYNC_RETIRED_JSON_KEYS
_MAX_STRUCTURED_RECORDS = 250_000
_MAX_STRUCTURED_JSON_CHARS = 1_048_576
_MAX_STRUCTURED_DEPTH = 16
_MAX_STRUCTURED_KEYS = 4096


def _json_contract_needs_disposition(raw: str, table: str, column: str) -> bool:
    """Inspect only registered provenance/scope locations, never opaque payloads."""
    if len(raw.encode("utf-8")) > 16 * 1024 * 1024:
        raise ConversionError(f"{table}.{column} exceeds the JSON disposition size bound")
    def unique_members(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ConversionError(f"{table}.{column} contains duplicate JSON members")
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=unique_members)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ConversionError(f"{table}.{column} is invalid structured JSON") from exc
    if not isinstance(value, dict):
        raise ConversionError(f"{table}.{column} must be a JSON object for its registered contract")
    if table == "agent_memory_records":
        return any(key in _JSON_RETIRED_KEYS for key in value)
    if table == "agent_tasks_projection" and column == "context":
        if any(key in _JSON_RETIRED_KEYS for key in value):
            raise ConversionError("agent_tasks_projection.context has retired fields with no registered disposition operation")
        allowed = {"repository_id", "clone_id", "worktree_id", "branch", "task_id", "session_id"}
        if set(value) - allowed:
            raise ConversionError("agent_tasks_projection.context has fields outside canonical ScopeContext")
        if any(type(item) is not str or item.strip() != item or "\x00" in item for item in value.values()):
            raise ConversionError("agent_tasks_projection.context has noncanonical ScopeContext values")
        return False
    if table == "agent_verification_receipts":
        metadata = value.get("_verification_receipt")
        required = {"schema", "owner", "mutation_generation", "evidence_type"}
        if not isinstance(metadata, dict) or set(metadata) != required:
            raise ConversionError("agent_verification_receipts.details requires explicit current receipt metadata; no promotion is supported")
        owner = metadata["owner"]
        generation = metadata["mutation_generation"]
        evidence_type = metadata["evidence_type"]
        if (metadata["schema"] != _RECEIPT_METADATA_SCHEMA or type(owner) is not str
                or owner.strip() != owner or "\x00" in owner
                or type(generation) is not int or generation < 0
                or type(evidence_type) is not str or evidence_type not in _RECEIPT_EVIDENCE_TYPES):
            raise ConversionError("agent_verification_receipts.details has noncanonical receipt metadata; offline conversion required")
        return False
    if table == "agent_tasks_projection":
        node = value.get("state_data")
    else:
        node = value.get("checkpoint")
        node = node.get("state_data") if isinstance(node, dict) else None
    if isinstance(node, dict) and "memory_context" in node:
        memory = node["memory_context"]
        if not isinstance(memory, dict):
            raise ConversionError(f"{table}.{column} memory_context is malformed")
        if (type(memory.get("schema_version")) is not int or memory.get("schema_version") != 2
                or "tenant_key" in memory):
            return True
        context_fields = {"root", "coordination_id", "task_id", "session_id", "clone_id", "worktree_id", "branch"}
        context = memory.get("context")
        if (set(memory) != {"schema_version", "context", "instruction", "items", "warnings", "estimated_tokens"}
                or not isinstance(context, dict)
                or not (set(context) == context_fields or context == {} and memory.get("items") == [])
                or any(type(item) is not str or item.strip() != item or "\x00" in item for item in context.values())
                or any(key in _JSON_RETIRED_KEYS for key in context)
                or not isinstance(memory.get("items"), list) or not isinstance(memory.get("warnings"), list)
                or type(memory.get("estimated_tokens")) is not int or memory["estimated_tokens"] < 0
                or type(memory.get("instruction")) is not str):
            raise ConversionError(f"{table}.{column} memory_context does not match the current v2 envelope")
    if not isinstance(node, dict) or "_agent_task_scope" not in node:
        return False
    scope = node["_agent_task_scope"]
    if not isinstance(scope, dict):
        raise ConversionError(f"{table}.{column} task scope is malformed")
    if set(scope) - {"version", "repo_root"} - _JSON_RETIRED_KEYS:
        raise ConversionError(f"{table}.{column} task scope has unsupported fields")
    version = scope.get("version")
    if type(version) is int and version == 1:
        if set(scope) - _JSON_RETIRED_KEYS != {"version", "repo_root"}:
            raise ConversionError(f"{table}.{column} legacy task scope is malformed")
        try:
            _JSON_DISPOSITION_API._canonical_historical_root(scope["repo_root"])
        except (KeyError, ValueError, OSError) as exc:
            raise ConversionError(f"{table}.{column} legacy task scope root is not preservable") from exc
        return True
    if type(version) is not int or version != 2:
        raise ConversionError(f"{table}.{column} task scope version is malformed")
    if set(scope) != {"version", "repo_root"}:
        raise ConversionError(f"{table}.{column} current task scope fields are noncanonical")
    try:
        _JSON_DISPOSITION_API._canonical_historical_root(scope["repo_root"])
    except (KeyError, ValueError, OSError) as exc:
        raise ConversionError(f"{table}.{column} current task scope root is not canonical") from exc
    return False


def _validate_json_contract_result(raw: str, table: str, column: str) -> None:
    if _json_contract_needs_disposition(raw, table, column):
        raise ConversionError(f"{table}.{column} contains retired or legacy scope data; explicit offline JSON disposition required")


def _validate_memory_context_identity(raw: str, table: str, key: Any, *, task_context=None, coordination_id=None) -> None:
    """Require persisted v2 memory context to agree with the same task envelope."""
    if table not in {"agent_tasks_projection", "agent_snapshots"}:
        return
    try:
        envelope = json.loads(raw)
    except (ValueError, TypeError, RecursionError) as exc:
        raise ConversionError(f"{table} memory context envelope is invalid") from exc
    state_data = envelope.get("state_data") if table == "agent_tasks_projection" else envelope.get("checkpoint", {}).get("state_data")
    if not isinstance(state_data, dict):
        return
    memory = state_data.get("memory_context")
    if not isinstance(memory, dict) or memory.get("schema_version") != 2:
        return
    context = memory["context"]
    expected_context = {"root", "coordination_id", "task_id", "session_id", "clone_id", "worktree_id", "branch"}
    if (set(memory) != {"schema_version", "context", "instruction", "items", "warnings", "estimated_tokens"}
            or not isinstance(context, dict)
            or not (set(context) == expected_context or context == {} and memory.get("items") == [])
            or any(type(value) is not str or value.strip() != value or "\x00" in value for value in context.values())
            or any(key in _JSON_RETIRED_KEYS for key in context)):
        raise ConversionError(f"{table} memory context identity fields are malformed")
    if context == {} and memory["items"] == []:
        return
    expected_task_id = envelope.get("task_id") if table == "agent_snapshots" else key
    if context["task_id"] != str(expected_task_id):
        raise ConversionError(f"{table} memory context task_id does not match its actual row")
    task_context = envelope.get("context") if task_context is None else task_context
    expected_task_context = {"repository_id", "clone_id", "worktree_id", "branch", "task_id", "session_id"}
    if (not isinstance(task_context, dict) or set(task_context) != expected_task_context
            or any(type(value) is not str for value in task_context.values())):
        raise ConversionError(f"{table} has no actual TaskState context to prove memory identity")
    if context["task_id"] != task_context["task_id"]:
        raise ConversionError(f"{table} memory context task_id differs from its TaskState context")
    for field in ("session_id", "clone_id", "worktree_id", "branch"):
        if context[field] != task_context.get(field, ""):
            raise ConversionError(f"{table} memory context {field} differs from its TaskState row")
    actual_coordination = envelope.get("coordination_id") if coordination_id is None else coordination_id
    if type(actual_coordination) is not str or actual_coordination != context["coordination_id"]:
        raise ConversionError(f"{table} lacks source-backed coordination_id proof for memory context")
    scope = state_data.get("_agent_task_scope")
    if (not isinstance(scope, dict) or type(scope.get("version")) is not int or scope.get("version") != 2
            or set(scope) != {"version", "repo_root"} or context["root"] != scope.get("repo_root")):
        raise ConversionError(f"{table} memory context root differs from explicit task scope")


def _preflight_agent_json(old: sqlite3.Connection, tables: list[dict[str, Any]], source_sha256: str,
                          manifest_path: Path | None) -> tuple[dict[tuple[str, tuple[Any, ...], str], str], list[dict[str, Any]]]:
    deadline = time.monotonic() + 30.0
    applicable = []
    for item in tables:
        table = str(item["table"])
        for contract_table, column, key_name in _AGENT_JSON_CONTRACTS:
            if table == contract_table and column in item["columns"]:
                if key_name not in item["columns"]:
                    raise ConversionError(f"{table}.{column} lacks its canonical record key")
                applicable.append((table, column, key_name))
    manifest = None
    if manifest_path is not None:
        try:
            manifest = _JSON_DISPOSITION_API.load_dispositions(manifest_path, source_sha256=source_sha256)
        except (OSError, ValueError) as exc:
            raise ConversionError(f"JSON disposition manifest rejected: {exc}") from exc
    changes: dict[tuple[str, tuple[Any, ...], str], str] = {}
    proofs: list[dict[str, Any]] = []
    for table, column, key_name in applicable:
        selected = [_quote(key_name), _quote(column)]
        context_index = coordination_index = None
        source_columns = set(next(item["columns"] for item in tables if item["table"] == table))
        if (table, column) == ("agent_tasks_projection", "checkpoint") and "context" in source_columns:
            context_index = len(selected)
            selected.append('"context"')
        if "coordination_id" in source_columns:
            coordination_index = len(selected)
            selected.append('"coordination_id"')
        if (table, column) == ("agent_verification_receipts", "details"):
            receipt_index = len(selected)
            selected.extend(('"passed"', '"observed_at"', '"expires_at"'))
        with closing(old.execute(f"SELECT {', '.join(selected)} FROM {_quote(table)} ORDER BY {_quote(key_name)}")) as cursor:
            for row in cursor:
                if time.monotonic() >= deadline:
                    raise ConversionError("Agent State structured JSON preflight exceeded its time bound")
                key_value, raw = row[:2]
                if (table, column) == ("agent_verification_receipts", "details") and (type(row[receipt_index]) is not int or row[receipt_index] not in (0, 1)):
                    raise ConversionError(f"agent_verification_receipts row {key_value!r} has a noncanonical passed flag")
                if (table, column) == ("agent_verification_receipts", "details"):
                    observed_at, expires_at = row[receipt_index + 1], row[receipt_index + 2]
                    if (type(observed_at) not in (int, float) or not math.isfinite(observed_at)
                            or expires_at is not None and (type(expires_at) not in (int, float) or not math.isfinite(expires_at))):
                        raise ConversionError(f"agent_verification_receipts row {key_value!r} has invalid timestamps")
                if not isinstance(raw, str):
                    if raw is None:
                        continue
                    raise ConversionError(f"{table}.{column} must contain text JSON")
                row_context = None
                if context_index is not None:
                    try:
                        row_context = json.loads(row[context_index]) if isinstance(row[context_index], str) else None
                    except (ValueError, TypeError, RecursionError):
                        row_context = None
                row_coordination = row[coordination_index] if coordination_index is not None else None
                if (table, column) in {("agent_tasks_projection", "checkpoint"), ("agent_snapshots", "state")}:
                    _validate_memory_context_identity(raw, table, key_value, task_context=row_context,
                                                      coordination_id=row_coordination)
                if manifest is None:
                    if _json_contract_needs_disposition(raw, table, column):
                        raise ConversionError(f"{table}.{column} record {key_value!r} requires explicit --json-dispositions")
                    continue
                try:
                    converted, proof = _JSON_DISPOSITION_API.transform_json(
                        raw, store="agent_state", table=table, key=str(key_value), column=column, manifest=manifest)
                except ValueError as exc:
                    raise ConversionError(f"JSON disposition failed for {table}.{key_value}.{column}: {exc}") from exc
                _validate_json_contract_result(converted, table, column)
                if proof.get("matched"):
                    if (table, column) in {("agent_tasks_projection", "checkpoint"), ("agent_snapshots", "state")}:
                        _validate_memory_context_identity(converted, table, key_value, task_context=row_context,
                                                          coordination_id=row_coordination)
                    identity = (key_value,)
                    changes[(table, identity, column)] = converted
                    proofs.append({**proof, "record_key": [key_value]})
    if manifest is not None:
        try:
            _JSON_DISPOSITION_API.require_all_dispositions_used(manifest, proofs)
        except ValueError as exc:
            raise ConversionError(f"JSON disposition manifest rejected: {exc}") from exc
    return changes, proofs


def _recursive_retired_key(value: Any, keys: set[str]) -> str | None:
    pending = [(value, 0)]
    seen: set[int] = set()
    inspected = 0
    while pending:
        current, depth = pending.pop()
        if depth > _MAX_STRUCTURED_DEPTH:
            raise ConversionError("structured JSON nesting exceeds preflight bound")
        if isinstance(current, dict):
            present = keys.intersection(current)
            if present:
                return sorted(present)[0]
            identity = id(current)
            if identity in seen:
                continue
            seen.add(identity)
            inspected += len(current)
            if inspected > _MAX_STRUCTURED_KEYS:
                raise ConversionError("structured JSON exceeds inspected-key bound")
            pending.extend((child, depth + 1) for child in current.values())
        elif isinstance(current, list):
            identity = id(current)
            if identity in seen:
                continue
            seen.add(identity)
            inspected += len(current)
            if inspected > _MAX_STRUCTURED_KEYS:
                raise ConversionError("structured JSON exceeds inspected-item bound")
            pending.extend((child, depth + 1) for child in current)
    return None


def _async_payload_retired_key(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    present = _ASYNC_RETIRED_JSON_KEYS.intersection(value)
    if present:
        return sorted(present)[0]
    pending = [(value.get("tasks"), 0, frozenset())] if "tasks" in value else []
    inspected = 0
    while pending:
        current, depth, ancestors = pending.pop()
        if depth > 16:
            raise ConversionError("async task list nesting exceeds runtime bound")
        if not isinstance(current, list):
            continue
        identity = id(current)
        if identity in ancestors:
            raise ConversionError("cyclic async task list is unsupported")
        next_ancestors = ancestors | {identity}
        inspected += len(current)
        if inspected > 4096:
            raise ConversionError("async task list exceeds runtime item bound")
        for item in current:
            if isinstance(item, dict):
                present = _ASYNC_RETIRED_JSON_KEYS.intersection(item)
                if present:
                    return sorted(present)[0]
                if "tasks" in item:
                    pending.append((item["tasks"], depth + 1, next_ancestors))
            elif isinstance(item, list):
                pending.append((item, depth + 1, next_ancestors))
    return None


def _async_result_retired_key(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    envelopes = [value]
    inspected = 0
    for envelope in envelopes:
        present = _ASYNC_RETIRED_JSON_KEYS.intersection(envelope)
        if present:
            return sorted(present)[0]
        if len(envelope) > 4096 or any(not isinstance(name, str) or len(name) > 4096 for name in envelope):
            raise ConversionError("async result envelope exceeds runtime key bound")
        inspected += len(envelope)
        if inspected > 4096:
            raise ConversionError("async result envelope exceeds runtime inspected-field bound")
        for name in ("control", "metadata", "provenance"):
            nested = envelope.get(name)
            if isinstance(nested, dict):
                inspected += len(nested)
                if len(nested) > 4096 or any(not isinstance(key, str) or len(key) > 4096 for key in nested):
                    raise ConversionError("async result envelope exceeds runtime key bound")
                if inspected > 4096:
                    raise ConversionError("async result envelope exceeds runtime inspected-field bound")
                present = _ASYNC_RETIRED_JSON_KEYS.intersection(nested)
                if present:
                    return sorted(present)[0]
    return None


def _task_row_digest(columns: list[str], values: tuple[Any, ...]) -> str:
    payload = [{"name": name, **_typed_archive_value(value)} for name, value in zip(columns, values)]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _preflight_writer_rows(connection: sqlite3.Connection, tables: list[dict[str, Any]],
                           source_sha256: str, writer_map_path: Path | None,
                           json_changes: dict[tuple[str, tuple[Any, ...], str], str]
                           ) -> tuple[dict[tuple[str, tuple[Any, ...]], dict[str, Any]], list[dict[str, Any]]]:
    """Map legacy lease ownership only from pinned task rows in this snapshot."""
    table_names = {str(item["table"]) for item in tables}
    writer_tables = {name for name in ("leases", "lease_waits") if name in table_names}
    if not writer_tables:
        if writer_map_path is not None:
            raise ConversionError("--writer-map has no lease rows to disposition")
        return {}, []
    count = sum(int(item["rows"]) for item in tables if item["table"] in writer_tables)
    if not count:
        if writer_map_path is not None:
            raise ConversionError("--writer-map has no lease rows to disposition")
        return {}, []
    if "agent_tasks_projection" not in table_names:
        raise ConversionError("lease conversion requires task facts from agent_tasks_projection in the same source snapshot")
    if writer_map_path is None:
        raise ConversionError("legacy leases require explicit source-pinned --writer-map dispositions")
    try:
        manifest = _WRITER_DISPOSITION_API.load_writer_map(writer_map_path, source_sha256=source_sha256)
    except (OSError, ValueError) as exc:
        raise ConversionError(f"writer map is invalid: {exc}") from exc

    task_item = next(item for item in tables if item["table"] == "agent_tasks_projection")
    task_columns = list(task_item["columns"])
    if not {"task_id", "owner", "checkpoint"}.issubset(task_columns):
        raise ConversionError("agent task rows do not contain actual owner and checkpoint fields required by writer mapping")
    task_cache: dict[str, dict[str, Any]] = {}

    def task_lookup(task_id: str) -> dict[str, Any]:
        if task_id in task_cache:
            return task_cache[task_id]
        selected = ", ".join(_quote(name) for name in task_columns)
        found = connection.execute(
            f"SELECT {selected} FROM agent_tasks_projection WHERE task_id IS ? LIMIT 2", (task_id,)
        ).fetchall()
        if len(found) != 1:
            raise ConversionError("writer map task id does not identify exactly one actual source task")
        values = tuple(found[0])
        row = dict(zip(task_columns, values))
        raw_checkpoint = row.get("checkpoint")
        changed = json_changes.get(("agent_tasks_projection", (task_id,), "checkpoint"))
        if changed is not None:
            raw_checkpoint = changed
        try:
            checkpoint = json.loads(raw_checkpoint) if isinstance(raw_checkpoint, str) else None
        except (ValueError, TypeError, RecursionError):
            checkpoint = None
        state_data = checkpoint.get("state_data") if isinstance(checkpoint, dict) else None
        scope = state_data.get("_agent_task_scope") if isinstance(state_data, dict) else None
        if (not isinstance(scope, dict) or set(scope) != {"version", "repo_root"}
                or type(scope.get("version")) is not int or scope["version"] != 2):
            raise ConversionError("mapped task lacks current explicit checkpoint scope; offline disposition is required")
        root = scope.get("repo_root")
        if type(root) is not str or not root or root.strip() != root or "\x00" in root:
            raise ConversionError("mapped task checkpoint has no canonical repo_root")
        facts = {"task_id": task_id, "owner": row.get("owner"), "repo_root": root,
                 "source_sha256": source_sha256,
                 "task_row_sha256": _task_row_digest(task_columns, values),
                 "source_sha256_scope": _SOURCE_COMPONENTS_SHA256_SCOPE}
        task_cache[task_id] = facts
        return facts

    def root_lookup(root_id: str) -> dict[str, str]:
        if "leases" not in table_names:
            raise ConversionError("lease-wait mapping requires root_path facts from leases in the same source snapshot")
        rows = connection.execute("SELECT DISTINCT root_path FROM leases WHERE root_id IS ? LIMIT 2", (root_id,)).fetchall()
        if len(rows) != 1:
            raise ConversionError("lease-wait root id does not identify one actual source root")
        return {"root_path": rows[0][0], "source_sha256": source_sha256}

    mapped_rows: dict[tuple[str, tuple[Any, ...]], dict[str, Any]] = {}
    proofs: list[dict[str, Any]] = []
    used: list[tuple[str, dict[str, Any]]] = []
    deadline = time.monotonic() + 30.0
    scanned = 0
    for table in sorted(writer_tables):
        columns = list(next(item for item in tables if item["table"] == table)["columns"])
        expected_columns = tuple(_WRITER_DISPOSITION_API._TABLE_COLUMNS[table])
        if set(columns) != set(expected_columns):
            raise ConversionError(f"{table} source columns differ from the exact writer-map contract")
        for values in connection.execute(f"SELECT {', '.join(_quote(name) for name in columns)} FROM {_quote(table)}"):
            scanned += 1
            if scanned > _MAX_ROWS or time.monotonic() >= deadline:
                raise ConversionError("writer-row preflight exceeded its bounded scan")
            source_row = dict(zip(columns, values))
            primary_key = {key: source_row[key] for key in _WRITER_DISPOSITION_API._PRIMARY_KEYS[table]}
            try:
                mapped, proof = _WRITER_DISPOSITION_API.transform_writer_row(
                    table=table, row=source_row, manifest=manifest,
                    task_lookup=task_lookup, root_lookup=root_lookup)
            except (ValueError, OSError) as exc:
                raise ConversionError(f"{table} writer disposition failed: {exc}") from exc
            for task_field in ("task", "blocked_task"):
                if task_field in proof:
                    proof[task_field]["task_row_sha256"] = task_lookup(proof[task_field]["task_id"])["task_row_sha256"]
                    proof[task_field]["source_sha256_scope"] = _SOURCE_COMPONENTS_SHA256_SCOPE
            mapped_rows[(table, tuple(primary_key[name] for name in primary_key))] = mapped
            proofs.append(proof)
            used.append((table, primary_key))
    try:
        _WRITER_DISPOSITION_API.validate_writer_map_usage(manifest, used)
        _WRITER_DISPOSITION_API.validate_target_key_uniqueness(proofs)
    except ValueError as exc:
        raise ConversionError(f"writer map is incomplete or colliding: {exc}") from exc
    return mapped_rows, proofs


def _data_transform_requirements(connection: sqlite3.Connection, store: str,
                                 tables: list[dict[str, Any]]) -> list[str]:
    """Check only structured control/provenance columns recognized by runtime."""
    names = {str(item["table"]) for item in tables}
    reasons: list[str] = []
    deadline = time.monotonic() + 30.0

    if store == "async_jobs" and "async_jobs" in names:
        item = next(item for item in tables if item["table"] == "async_jobs")
        columns = set(item["columns"])
        registered = set(_JSON_CONTAINERS.get(store, {}))
        for column in ("payload_json", "result_json"):
            if column not in columns or ("async_jobs", column) not in registered:
                continue
            with closing(connection.execute(
                f"SELECT job_id, substr({_quote(column)},1,?) FROM async_jobs LIMIT ?",
                (_MAX_STRUCTURED_JSON_CHARS + 1, _MAX_STRUCTURED_RECORDS + 1))) as cursor:
                for row_number, (job_id, raw) in enumerate(cursor, 1):
                    if time.monotonic() >= deadline:
                        raise ConversionError("async structured-record preflight exceeded its time bound")
                    if row_number > _MAX_STRUCTURED_RECORDS:
                        reasons.append(f"async_jobs.{column}: row scan exceeds bounded retired-field preflight")
                        break
                    if not isinstance(raw, str) or len(raw) > _MAX_STRUCTURED_JSON_CHARS:
                        reasons.append(f"async_jobs.{column} row {job_id!r}: record exceeds bounded retired-field preflight")
                        break
                    try:
                        value = json.loads(raw)
                    except (TypeError, ValueError, RecursionError):
                        continue
                    retired = (_async_payload_retired_key(value) if column == "payload_json"
                               else _async_result_retired_key(value))
                    if retired:
                        reasons.append(f"async_jobs.{column} row {job_id!r}: retired field {retired}")
                        break

    if store == "work_orchestrator" and "work_orders" in names:
        item = next(item for item in tables if item["table"] == "work_orders")
        if "payload_json" in item["columns"]:
            with closing(connection.execute(
                f"SELECT work_id, substr({_quote('payload_json')},1,?) FROM work_orders LIMIT ?",
                (_MAX_STRUCTURED_JSON_CHARS + 1, _MAX_STRUCTURED_RECORDS + 1))) as cursor:
                for row_number, (work_id, raw) in enumerate(cursor, 1):
                    if time.monotonic() >= deadline:
                        raise ConversionError("work-order control preflight exceeded its time bound")
                    if row_number > _MAX_STRUCTURED_RECORDS:
                        reasons.append("work_orders.payload_json: row scan exceeds bounded control preflight")
                        break
                    if not isinstance(raw, str) or len(raw) > _MAX_STRUCTURED_JSON_CHARS:
                        reasons.append(f"work_orders.payload_json row {work_id!r}: record exceeds bounded control preflight")
                        break
                    try:
                        value = json.loads(raw)
                    except (TypeError, ValueError, RecursionError):
                        continue
                    if isinstance(value, dict) and "tenant" in value:
                        reasons.append(f"work_orders.payload_json row {work_id!r}: retired field tenant")
                        break

    if store == "telemetry" and "snapshots" in names:
        item = next(item for item in tables if item["table"] == "snapshots")
        registered = set(_JSON_CONTAINERS.get(store, {}))
        if "metrics_json" in item["columns"] and ("snapshots", "metrics_json") in registered:
            with closing(connection.execute(
                f"SELECT substr({_quote('metrics_json')},1,?) FROM snapshots LIMIT ?",
                (_MAX_STRUCTURED_JSON_CHARS + 1, _MAX_STRUCTURED_RECORDS + 1))) as cursor:
                for row_number, (raw,) in enumerate(cursor, 1):
                    if time.monotonic() >= deadline:
                        raise ConversionError("telemetry metadata preflight exceeded its time bound")
                    if row_number > _MAX_STRUCTURED_RECORDS:
                        reasons.append("snapshots.metrics_json: row scan exceeds bounded metadata preflight")
                        break
                    if not isinstance(raw, str):
                        continue
                    if len(raw) > _MAX_STRUCTURED_JSON_CHARS:
                        reasons.append("snapshots.metrics_json: record exceeds bounded metadata preflight")
                        break
                    try:
                        value = json.loads(raw)
                    except (TypeError, ValueError, RecursionError):
                        continue
                    retired = _recursive_retired_key(value, _TELEMETRY_RETIRED_JSON_KEYS)
                    if retired:
                        reasons.append(f"snapshots.metrics_json row {row_number}: retired metadata field {retired}")
                        break

    fence_tables = {"writer_fence_leases", "writer_fence_attempts"}
    if store in {"work_fencing", "agent_state"}:
        for item in tables:
            table = str(item["table"])
            if table not in fence_tables or "scope_id" not in item["columns"]:
                continue
            for row_number, (scope_id,) in enumerate(connection.execute(
                    f"SELECT scope_id FROM {_quote(table)} LIMIT ?", (_MAX_ROWS + 1,)), 1):
                if time.monotonic() >= deadline:
                    raise ConversionError("writer-fence scope preflight exceeded its time bound")
                if row_number > _MAX_ROWS:
                    reasons.append(f"{table}.scope_id: row scan exceeds supported bound")
                    break
                project_scope = (isinstance(scope_id, str) and scope_id.startswith("project:")
                                and bool(scope_id[len("project:"):])
                                and scope_id[len("project:"):].strip() == scope_id[len("project:"):])
                physical_scope = isinstance(scope_id, str) and Path(scope_id).is_absolute()
                if (type(scope_id) is not str or not scope_id or scope_id.strip() != scope_id
                        or "\x00" in scope_id or len(scope_id) > 512
                        or not (project_scope or physical_scope)):
                    reasons.append(f"{table}.scope_id row {row_number}: actual canonical scope is missing or invalid")
                    break
    return reasons


def _typed_archive_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {"type": "null", "value": None}
    if isinstance(value, bytes):
        return {"type": "blob", "base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, bool):
        return {"type": "integer", "value": int(value)}
    if isinstance(value, int):
        return {"type": "integer", "value": value}
    if isinstance(value, float):
        return {"type": "real_hex", "value": value.hex()}
    return {"type": "text", "value": str(value)}


def _archive_rows(connection: sqlite3.Connection, table_record: dict[str, Any]) -> dict[str, Any]:
    table = str(table_record["table"])
    columns = list(table_record["columns"])
    info = connection.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
    keys = [str(row[1]) for row in sorted(info, key=lambda row: int(row[5]) or 10**9) if int(row[5])]
    order = ", ".join(_quote(key) for key in keys) if keys else "rowid"
    rows = []
    for row in connection.execute(f"SELECT {', '.join(_quote(column) for column in columns)} FROM {_quote(table)} ORDER BY {order}"):
        if len(rows) >= _MAX_ROWS:
            raise ConversionError(f"archived table {table} exceeds supported row bound")
        rows.append([_typed_archive_value(value) for value in row])
    archived = {"table": table, "source_sql": table_record["source_sql"], "columns": columns, "rows": rows}
    size = len(json.dumps(archived, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    if size > _MAX_SQLITE_BYTES:
        raise ConversionError(f"external archive for {table} exceeds supported size; preserve the source database separately")
    return archived


def _autoincrement_tables(store: str) -> set[str]:
    return {name for name, ddl in _STORE_DDL[store][0].items()
            if "AUTOINCREMENT" in ddl.upper()}


def _sequence_rows(connection: sqlite3.Connection, allowed_tables: set[str] | None = None) -> list[tuple[str, int]]:
    try:
        rows = connection.execute("SELECT name, seq FROM sqlite_sequence ORDER BY name LIMIT ?",
                                  (_MAX_TABLES + 1,)).fetchall()
    except sqlite3.OperationalError:
        return []
    if len(rows) > _MAX_TABLES:
        raise ConversionError("SQLite AUTOINCREMENT sequence inventory exceeds table bound")
    result = []
    seen = set()
    for name, seq in rows:
        if (type(name) is not str or not name or name in seen or type(seq) is not int or seq < 0
                or allowed_tables is not None and name not in allowed_tables):
            raise ConversionError("SQLite AUTOINCREMENT sequence contains an unsupported table or value")
        seen.add(name)
        result.append((name, seq))
    return result


def _verify_generated_agent_objects(connection: sqlite3.Connection) -> None:
    objects = {(str(kind), str(name), str(table)): sql for kind, name, table, sql in
               connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE type='table'")}
    for identity, expected_hash in _GENERATED_AGENT_HASHES.items():
        sql = objects.get(identity)
        if sql is None or _agent_object_sql_sha256(sql) != expected_hash:
            raise ConversionError(f"SQLite-generated Agent State object pin mismatch: {identity}")


def _verify_expected_agent_object_sql(connection: sqlite3.Connection) -> None:
    objects = {(str(kind), str(name), str(table)): sql for kind, name, table, sql in
               connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE type IN ('table','index')")}
    for identity, expected_hash in _EXPECTED_AGENT_HASHES.items():
        sql = objects.get(identity)
        if sql is None or _agent_object_sql_sha256(sql) != expected_hash:
            raise ConversionError(f"Agent State target object pin mismatch: {identity}")


def _target_sequence_rows(path: Path, allowed_tables: set[str]) -> list[tuple[str, int]]:
    with closing(sqlite3.connect(path)) as connection:
        return _sequence_rows(connection, allowed_tables)


def _initialize_target_schema(connection: sqlite3.Connection, store: str) -> None:
    for statement in _STORE_DDL[store][0].values():
        connection.execute(statement)
    if store == "agent_state":
        connection.execute(
            f"PRAGMA user_version={_COMPLETE_AGENT['COMPLETE_AGENT_STATE_DDL']['user_version']}"
        )


def convert_sqlite_store(source: Path, target: Path, *, collision_manifest: Path | None = None,
                        expected_sha256: str | None = None,
                        archive_manifest: Path | None = None,
                        json_dispositions: Path | None = None,
                        writer_map: Path | None = None) -> dict[str, Any]:
    """Convert only registered source/target schemas with explicit dispositions."""
    if source.resolve() == target.resolve() or target.exists():
        raise ConversionError("SQLite target must be separate and must not already exist")
    provenance_target = target.with_name(target.name + ".conversion-provenance.json")
    if provenance_target.exists():
        raise ConversionError("provenance target already exists; refusing overwrite")
    if not target.parent.is_dir():
        raise ConversionError("target parent directory must already exist")
    source_hash_before, source_components_before = _sqlite_source_fingerprint(source)
    if expected_sha256 is not None and expected_sha256 != source_hash_before:
        raise ConversionError("source changed since inventory; create a fresh plan")
    deadline = time.monotonic() + 120.0
    with tempfile.TemporaryDirectory(prefix="single-owner-conversion-", dir=target.parent) as temp_dir:
        temp_path = Path(temp_dir)
        snapshot_path = temp_path / "snapshot.sqlite"
        target_path = temp_path / "target.sqlite"
        try:
            copied_source, copied_hash, _ = _copy_sqlite_snapshot(source, temp_path)
            if copied_hash != source_hash_before:
                raise ConversionError("source changed after initial inventory; take a fresh inventory")
            with closing(sqlite3.connect(copied_source, timeout=2.0)) as source_connection:
                source_connection.execute("PRAGMA query_only=ON")
                with closing(sqlite3.connect(snapshot_path)) as snapshot_connection:
                    source_connection.backup(snapshot_connection, pages=256, sleep=0.05)
                    snapshot_connection.commit()
            with closing(sqlite3.connect(snapshot_path)) as old:
                old.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
                store, removed, tables = _source_store_shape(old)
                total = sum(item["rows"] for item in tables)
                if total > _MAX_ROWS:
                    raise ConversionError("SQLite row count exceeds supported conversion bound")
                _store_collisions(old, store, removed, tables,
                                  ignore_tables={"leases", "lease_waits"} if store == "agent_state" else None)
                _preflight_historical_unique_indexes(old, store)
                _verify_store_relations(old, store)
                if store == "agent_state":
                    validate_archive_manifest(source_hash_before, tuple(_AGENT_ARCHIVE_TABLES), archive_manifest)
                json_changes: dict[tuple[str, tuple[Any, ...], str], str] = {}
                json_proofs: list[dict[str, Any]] = []
                if store == "agent_state":
                    json_changes, json_proofs = _preflight_agent_json(
                        old, tables, source_hash_before, json_dispositions)
                historical_row_changes, historical_row_provenance, historical_expected_hashes = (
                    _historical_store_row_transforms(old, store, tables))
                writer_rows, writer_proofs = _preflight_writer_rows(
                    old, tables, source_hash_before, writer_map, json_changes)
                required_transforms = _transform_requirements(store, tables)
                required_transforms.extend(_data_transform_requirements(old, store, tables))
                if required_transforms:
                    raise ConversionError("store requires explicit offline transforms before publication: " + "; ".join(required_transforms))
                inventory = {"source_sha256": source_hash_before, "tables": tables,
                             "row_count": total, "collision_count": sum(len(item["collisions"]) for item in tables)}
                if inventory["collision_count"]:
                    if collision_manifest is None:
                        raise ConversionError("collisions exist; explicit per-identity --collision-manifest is required")
                    validate_collision_manifest(inventory, collision_manifest)
                    raise ConversionError("collision dispositions are recorded, but target-key remapping is unsupported; no rows were merged or dropped")
                new, index_sql = _STORE_DDL[store]
                provenance_rows = []
                archived_tables = [_archive_rows(old, item) for item in tables if item.get("archive_only")]
                sequence_tables = _autoincrement_tables(store)
                source_sequences = _sequence_rows(old, sequence_tables) if sequence_tables else []
                with closing(sqlite3.connect(target_path)) as target_connection:
                    target_connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
                    target_connection.execute("PRAGMA foreign_keys=ON")
                    _initialize_target_schema(target_connection, store)
                    for item in tables:
                        if item.get("archive_only"):
                            continue
                        table = item["table"]
                        if store == "agent_state" and table == "agent_memory_fts":
                            continue
                        old_columns = item["columns"]
                        retired = removed[table]
                        kept = [column for column in old_columns if column not in retired]
                        new_info = target_connection.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
                        target_columns = [str(row[1]) for row in new_info]
                        keys = [str(row[1]) for row in sorted(new_info, key=lambda row: int(row[5]) or 10**9) if int(row[5])]
                        with closing(old.execute(f"SELECT {', '.join(_quote(column) for column in old_columns)} FROM {_quote(table)}")) as source_rows:
                            placeholders = ",".join("?" for _ in target_columns)
                            insert = f"INSERT INTO {_quote(table)} ({', '.join(_quote(column) for column in target_columns)}) VALUES ({placeholders})"
                            for row in source_rows:
                                if time.monotonic() >= deadline:
                                    raise ConversionError("SQLite conversion exceeded its time bound")
                                row_values = dict(zip(old_columns, row))
                                if table in {"leases", "lease_waits"} and store == "agent_state":
                                    source_pk_columns = _WRITER_DISPOSITION_API._PRIMARY_KEYS[table]
                                    source_pk = tuple(row_values[name] for name in source_pk_columns)
                                    writer_replacement = writer_rows.get((table, source_pk))
                                    if writer_replacement is None:
                                        raise ConversionError(f"{table} row has no preflighted writer disposition")
                                    row_identity = tuple(row_values[key] for key in source_pk_columns)
                                else:
                                    writer_replacement = None
                                    row_identity = tuple(row_values[key] for key in keys if key in row_values)
                                insert_values = dict(row_values)
                                if writer_replacement is not None:
                                    insert_values.update(writer_replacement)
                                insert_values.update(historical_row_changes.get((table, row_identity), {}))
                                for column in kept:
                                    replacement = json_changes.get((table, row_identity, column))
                                    if replacement is not None:
                                        insert_values[column] = replacement
                                for tenant_column in (() if writer_replacement is not None else retired):
                                    if len(provenance_rows) >= _MAX_PROVENANCE_ENTRIES:
                                        raise ConversionError("removed-field provenance exceeds supported record bound")
                                    removed_value = row_values[tenant_column]
                                    if removed_value is not None and len(str(removed_value)) > _MAX_PROVENANCE_VALUE_CHARS:
                                        raise ConversionError("removed tenant field exceeds supported provenance size")
                                    provenance_rows.append({"store": store, "table": table,
                                        "record_key": [row_values[key] for key in keys],
                                        "removed_field": tenant_column, "removed_value": removed_value})
                                if not set(target_columns).issubset(insert_values):
                                    missing = set(target_columns) - set(insert_values)
                                    raise ConversionError(f"{table} mapped row is missing target fields: {', '.join(sorted(missing))}")
                                target_connection.execute(insert, tuple(insert_values[column] for column in target_columns))
                    if store == "agent_state":
                        target_connection.execute(
                            "INSERT INTO agent_memory_fts(record_id,key,value) "
                            "SELECT record_id,key,value FROM agent_memory_records")
                    for sequence_name, sequence_value in source_sequences:
                        current = target_connection.execute(
                            "SELECT seq FROM sqlite_sequence WHERE name=?", (sequence_name,)).fetchone()
                        if current is None:
                            target_connection.execute("INSERT INTO sqlite_sequence(name,seq) VALUES(?,?)",
                                                      (sequence_name, sequence_value))
                        elif int(current[0]) < sequence_value:
                            target_connection.execute("UPDATE sqlite_sequence SET seq=? WHERE name=?",
                                                      (sequence_value, sequence_name))
                    for statement in index_sql:
                        target_connection.execute(statement)
                    if store == "agent_state":
                        _verify_generated_agent_objects(target_connection)
                        _verify_expected_agent_object_sql(target_connection)
                    if _sequence_rows(target_connection, sequence_tables) != source_sequences:
                        raise ConversionError("SQLite AUTOINCREMENT high-water marks changed during conversion")
                    if target_connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                        raise ConversionError("converted target failed foreign_key_check")
                    target_connection.commit()
                    _verify_store_relations(target_connection, store)
                    quick_check = target_connection.execute("PRAGMA quick_check").fetchone()
                    if not quick_check or str(quick_check[0]).casefold() != "ok":
                        raise ConversionError("converted target failed SQLite quick_check")
                    for item in tables:
                        if item.get("archive_only"):
                            continue
                        table = item["table"]
                        if store == "agent_state" and table == "agent_memory_fts":
                            if int(target_connection.execute("SELECT COUNT(*) FROM agent_memory_fts").fetchone()[0]) != int(
                                    target_connection.execute("SELECT COUNT(*) FROM agent_memory_records").fetchone()[0]):
                                raise ConversionError("rebuilt FTS index does not match authoritative memory row count")
                            continue
                        info = target_connection.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
                        keys = [str(row[1]) for row in sorted(info, key=lambda row: int(row[5]) or 10**9) if int(row[5])]
                        kept = [column for column in item["columns"] if column not in removed[table]]
                        target_count = int(target_connection.execute(f"SELECT COUNT(*) FROM {_quote(table)}").fetchone()[0])
                        if target_count != item["rows"]:
                            raise ConversionError(f"row count changed while converting {table}")
                        replacements = {(identity, column): value for (changed_table, identity, column), value in json_changes.items()
                                        if changed_table == table}
                        if table in {"leases", "lease_waits"} and store == "agent_state":
                            target_by_key = {}
                            for proof in writer_proofs:
                                if proof["table"] == table:
                                    target_by_key[tuple(proof["new_key"][key] for key in keys)] = proof
                            expected_digest = hashlib.sha256()
                            actual_digest = hashlib.sha256()
                            with closing(target_connection.execute(
                                f"SELECT {', '.join(_quote(column) for column in target_columns)} FROM {_quote(table)} ORDER BY {', '.join(_quote(key) for key in keys)}")) as cursor:
                                seen_keys = set()
                                for target_row in cursor:
                                    target_values = dict(zip(target_columns, target_row))
                                    target_key = tuple(target_values[key] for key in keys)
                                    proof = target_by_key.get(target_key)
                                    if proof is None or target_key in seen_keys:
                                        raise ConversionError(f"converted {table} row has no unique expected writer identity")
                                    seen_keys.add(target_key)
                                    source_pk = tuple(proof["source_primary_key"][name]
                                                      for name in _WRITER_DISPOSITION_API._PRIMARY_KEYS[table])
                                    expected_values = writer_rows[(table, source_pk)]
                                    if any(target_values[column] != expected_values.get(column) for column in target_columns):
                                        raise ConversionError(f"converted {table} row differs from its source-pinned writer disposition")
                                    expected_row = [expected_values[column] for column in target_columns]
                                    expected_encoded = json.dumps(expected_row, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
                                    actual_encoded = json.dumps(list(target_row), ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
                                    expected_digest.update(expected_encoded + b"\n")
                                    actual_digest.update(actual_encoded + b"\n")
                            if seen_keys != set(target_by_key):
                                raise ConversionError(f"converted {table} rows do not preserve every mapped source record")
                            retained_expected, retained_actual = expected_digest.hexdigest(), actual_digest.hexdigest()
                        elif table in historical_expected_hashes:
                            retained_expected = historical_expected_hashes[table]
                            retained_actual = _row_hash(target_connection, table, target_columns, keys)
                        else:
                            hash_columns = kept
                            if store == "telemetry" and table == "events":
                                hash_columns = [column for column in target_columns if column in kept]
                            retained_expected = _row_hash(old, table, hash_columns, keys, replacements)
                            retained_actual = _row_hash(target_connection, table, hash_columns, keys)
                        if retained_expected != retained_actual:
                            raise ConversionError(f"retained values or identifiers changed while converting {table}")
                        item["retained_expected_sha256"] = retained_expected
                        item["retained_sha256"] = retained_actual
            source_hash_after, source_components_after = _sqlite_source_fingerprint(source)
            if source_hash_before != source_hash_after or source_components_before != source_components_after:
                raise ConversionError("source or WAL/SHM sidecars changed during conversion; discard this target and take a fresh snapshot")
            target_hash = _sha256(target_path)
            provenance = {"format": "single-owner-conversion-v1", "source_sha256": source_hash_before,
                "source_components": source_components_before, "target_sha256": target_hash, "store": store,
                "row_count": total, "tables": tables, "removed_retired_fields": provenance_rows,
                "historical_row_transforms": historical_row_provenance,
                "json_dispositions": json_proofs,
                "writer_dispositions": writer_proofs,
                "archived_tables": archived_tables,
                "source_sqlite_sequence": source_sequences,
                "target_sqlite_sequence": _target_sequence_rows(target_path, sequence_tables),
                "agent_state_expected_object_sql_hashes": ([
                    {"type": kind, "name": name, "table": table, "sha256": value}
                    for (kind, name, table), value in _EXPECTED_AGENT_HASHES.items()
                ] if store == "agent_state" else []),
                "fts_rebuild": ({"source_table": _COMPLETE_AGENT["FTS_REBUILD_SOURCE"],
                                 "source_is_authoritative": _COMPLETE_AGENT["FTS_REBUILD_FROM_METADATA_ONLY"],
                                 "source_fts_shadow_preserved_in_original": True} if store == "agent_state" else None),
                "removed_artifact_schema_markers": ([{"table": "artifact_schema_meta", "key": "tenant_storage",
                                                       "value": "sha256-v1"}] if store == "artifacts" else []),
                "collision_count": 0, "conversion_status": "verified separate target; source and sidecars preserved"}
            temp_provenance = temp_path / "provenance.json"
            provenance_text = json.dumps(provenance, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
            if len(provenance_text.encode("utf-8")) > _MAX_SQLITE_BYTES:
                raise ConversionError("external conversion provenance exceeds supported size; preserve the source database separately")
            temp_provenance.write_text(provenance_text, encoding="utf-8")
            if target.exists() or provenance_target.exists():
                raise ConversionError("target appeared during conversion; refusing overwrite")
            _publish_new_file(target_path, target)
            try:
                _publish_new_file(temp_provenance, provenance_target)
            except Exception as exc:
                raise ConversionError(f"target published but provenance publication failed; preserve target and retry provenance separately: {exc}") from exc
            return {"source_sha256": source_hash_before, "target_sha256": target_hash,
                    "provenance_path": str(provenance_target), "store": store,
                    "row_count": total, "conversion": "completed into separate target"}
        except Exception:
            # All work before publication is confined to TemporaryDirectory;
            # after target publication, preserve it for provenance recovery.
            raise


def plan_sqlite_store(source: Path, inventory: dict[str, Any], *,
                      json_dispositions: Path | None = None,
                      writer_map: Path | None = None) -> dict[str, Any]:
    """Add exact supported-schema and collision evidence to a read-only plan."""
    before = _sqlite_source_fingerprint(source)
    if inventory.get("source_sha256") != before[0]:
        return {**inventory, "conversion_support": "source_changed_since_inventory"}
    try:
        with tempfile.TemporaryDirectory(prefix="single-owner-plan-") as temp_dir:
          copied_source, copied_hash, _ = _copy_sqlite_snapshot(source, Path(temp_dir))
          if copied_hash != before[0]:
              return {**inventory, "conversion_support": "source_changed_since_inventory"}
          with closing(sqlite3.connect(copied_source, timeout=2.0)) as connection:
            connection.execute("PRAGMA query_only=ON")
            plan_deadline = time.monotonic() + 30.0
            connection.set_progress_handler(lambda: int(time.monotonic() >= plan_deadline), 1000)
            table_names = {str(row[0]) for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' LIMIT ?",
                (_MAX_TABLES + 1,)).fetchall()}
            if len(table_names) > _MAX_TABLES:
                raise ConversionError("database table count exceeds supported inventory bound")
            unsupported = _known_unsupported_store(table_names)
            if unsupported is not None:
                return {**inventory, "conversion_support": "unsupported_store_contract",
                        "conversion_reason": unsupported.get("reason"),
                        "required_objects": list(unsupported.get("required_objects", ()))}
            store, removed, tables = _source_store_shape(connection)
            sequence_tables = _autoincrement_tables(store)
            source_sequences = _sequence_rows(connection, sequence_tables) if sequence_tables else []
            if writer_map is not None and store != "agent_state":
                raise ConversionError("--writer-map applies only to Agent State lease rows")
            _store_collisions(connection, store, removed, tables,
                              ignore_tables={"leases", "lease_waits"} if store == "agent_state" else None)
            data_requirements = _data_transform_requirements(connection, store, tables)
            writer_requirements = []
            if store == "agent_state":
                json_changes = {}
                try:
                    json_changes, _ = _preflight_agent_json(connection, tables, before[0], json_dispositions)
                except ConversionError as exc:
                    data_requirements.append(str(exc))
                try:
                    _preflight_writer_rows(connection, tables, before[0], writer_map, json_changes)
                except ConversionError as exc:
                    writer_requirements.append(str(exc))
        collisions = sum(len(item["collisions"]) for item in tables)
        required_transforms = _transform_requirements(store, tables) + data_requirements + writer_requirements
        result = {**inventory, "tables": tables, "supported_store": store,
                "collision_count": collisions,
                "required_transforms": required_transforms,
                "conversion_support": ("blocked_by_collisions" if collisions else
                                       "blocked_by_explicit_transforms" if required_transforms else
                                       "supported_no_collisions")}
        if store == "agent_state":
            result.update({"archive_tables": list(_AGENT_ARCHIVE_TABLES),
                           "archive_disposition_required": True,
                           "fts_rebuild": {"source_table": _COMPLETE_AGENT["FTS_REBUILD_SOURCE"],
                                           "source_is_authoritative": _COMPLETE_AGENT["FTS_REBUILD_FROM_METADATA_ONLY"],
                                           "source_fts_shadow_preserved_in_original": True},
                           "sqlite_sequence_high_water_preserved": _COMPLETE_AGENT["PRESERVE_SQLITE_SEQUENCE_HIGH_WATER"]})
        elif sequence_tables:
            result.update({"source_sqlite_sequence": source_sequences,
                           "sqlite_sequence_high_water_preserved": True})
        return result
    except ConversionError as exc:
        return {**inventory, "conversion_support": "unsupported_schema", "conversion_reason": str(exc)}


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--target", type=Path)
    parser.add_argument("--apply", action="store_true", help="write a separate supported conversion target")
    parser.add_argument("--expected-sha256", help="bind conversion to a previously inventoried source")
    parser.add_argument("--collision-manifest", type=Path, help="explicit per-identity preservation dispositions")
    parser.add_argument("--archive-disposition-manifest", type=Path,
                        help="explicit external-archive dispositions for retired schema tables")
    parser.add_argument("--json-dispositions", type=Path,
                        help="explicit source-pinned JSON record transformations")
    parser.add_argument("--writer-map", type=Path,
                        help="explicit source-pinned lease owner mappings to actual task facts")
    args = parser.parse_args(argv)
    if not args.source.is_file():
        parser.error("source must be an existing regular file")
    suffix = args.source.suffix.casefold()
    try:
        if args.json_dispositions is not None and suffix not in {".sqlite", ".sqlite3", ".db"}:
            raise ConversionError("--json-dispositions applies only to supported SQLite structured records")
        if args.writer_map is not None and suffix not in {".sqlite", ".sqlite3", ".db"}:
            raise ConversionError("--writer-map applies only to Agent State SQLite lease rows")
        if suffix in {".sqlite", ".sqlite3", ".db"}:
            report = inventory_sqlite(args.source)
            if args.apply:
                if args.target is None:
                    raise ConversionError("--target is required with --apply")
                report = convert_sqlite_store(args.source, args.target, collision_manifest=args.collision_manifest,
                                              expected_sha256=args.expected_sha256,
                                              archive_manifest=args.archive_disposition_manifest,
                                              json_dispositions=args.json_dispositions,
                                              writer_map=args.writer_map)
            else:
                report = plan_sqlite_store(args.source, report, json_dispositions=args.json_dispositions,
                                           writer_map=args.writer_map)
                report["conversion"] = "dry plan only; source, WAL, and SHM are untouched"
        elif suffix in {".json", ".toml"}:
            if args.source.stat().st_size > _MAX_CONFIG_BYTES:
                raise ConversionError("configuration exceeds supported size")
            if args.apply:
                if args.target is None:
                    raise ConversionError("--target is required with --apply")
                converter = convert_toml_config if suffix == ".toml" else convert_config
                report = converter(args.source, args.target, expected_sha256=args.expected_sha256)
                report["conversion"] = "completed: separate configuration target"
            else:
                raw = args.source.read_text(encoding="utf-8")
                original = tomllib.loads(raw) if suffix == ".toml" else json.loads(raw)
                if not isinstance(original, dict):
                    raise ConversionError("only top-level configuration objects are supported")
                converted, removed = _remove_retired_config_fields(original)
                preview = (json.dumps(converted, ensure_ascii=False, indent=2) + "\n").encode("utf-8") if suffix == ".json" else None
                report = {"source_sha256": _sha256(args.source),
                          "target_sha256_preview": hashlib.sha256(preview).hexdigest() if preview is not None else None,
                          "removed_paths": [item["path"] for item in removed],
                          "conversion": "dry plan only; configuration values are not printed"}
        else:
            raise ConversionError("unsupported source type; only JSON/TOML config and bounded SQLite stores are supported")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (ConversionError, OSError, sqlite3.Error, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(_main())

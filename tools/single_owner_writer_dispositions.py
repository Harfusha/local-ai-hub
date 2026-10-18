"""Explicit, offline writer-identity dispositions for legacy lease rows.

This module is pure conversion support: it imports no Local AI Hub runtime
modules and performs no database or filesystem mutations.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

WRITER_MAP_SCHEMA: Final = "single_owner_writer_map.v1"
SOURCE_SHA256_SCOPE: Final = (
    "SHA-256 of canonical source-component metadata (filename, size, raw SHA-256 for main/WAL/SHM/journal); "
    "task-row SHA-256 is separately pinned"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_MAP_BYTES = 16 * 1024 * 1024
_TABLE_COLUMNS: Final[dict[str, tuple[str, ...]]] = {
    "leases": (
        "lease_id", "tenant", "root_id", "root_path", "path", "purpose",
        "created_at", "expires_at",
    ),
    "lease_waits": (
        "tenant", "blocked_by", "root_id", "requested_path", "updated_at",
    ),
}
_PRIMARY_KEYS: Final[dict[str, tuple[str, ...]]] = {
    "leases": ("lease_id", "path"),
    "lease_waits": ("root_id", "tenant", "blocked_by", "requested_path"),
}


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON value is forbidden: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _sha256(value: Any, name: str) -> str:
    if type(value) is not str or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _typed_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {"type": "null", "value": None}
    if type(value) is bool:
        return {"type": "bool", "value": value}
    if type(value) is int:
        return {"type": "int", "value": value}
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("row contains a non-finite floating-point value")
        return {"type": "float", "value": value}
    if type(value) is str:
        return {"type": "str", "value": value}
    raise ValueError(f"row contains unsupported SQLite value type: {type(value).__name__}")


def typed_row_sha256(table: str, row: Mapping[str, Any]) -> str:
    """Hash every exact column and value, preserving SQLite scalar types."""
    if table not in _TABLE_COLUMNS or not isinstance(row, Mapping):
        raise ValueError("unsupported writer row")
    columns = _TABLE_COLUMNS[table]
    if set(row) != set(columns):
        raise ValueError(f"{table} row columns do not match the legacy contract")
    payload = {
        "table": table,
        "columns": [
            {"name": column, **_typed_value(row[column])}
            for column in columns
        ],
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _disposition_key(table: str, primary_key: Mapping[str, Any]) -> str:
    ordered = [(key, _typed_value(value)) for key, value in primary_key.items()]
    encoded = json.dumps(
        [table, ordered], ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_writer_map(path: str | os.PathLike[str], *, source_sha256: str) -> Mapping[str, Any]:
    """Load and freeze a complete, source-pinned writer disposition manifest."""
    expected_source = _sha256(source_sha256, "source_sha256")
    map_path = Path(path)
    raw = map_path.read_bytes()
    if len(raw) > _MAX_MAP_BYTES:
        raise ValueError("writer map exceeds the bounded size limit")
    try:
        data = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("writer map must be valid UTF-8 JSON") from exc
    if not isinstance(data, dict) or set(data) != {"schema", "source_sha256", "dispositions"}:
        raise ValueError("writer map has unsupported fields or shape")
    if data["schema"] != WRITER_MAP_SCHEMA:
        raise ValueError("unsupported writer map schema")
    if _sha256(data["source_sha256"], "manifest source_sha256") != expected_source:
        raise ValueError("writer map source digest does not match the pinned source")
    if type(data["dispositions"]) is not list:
        raise ValueError("writer map dispositions must be a list")

    seen: set[str] = set()
    dispositions: list[dict[str, Any]] = []
    for item in data["dispositions"]:
        if not isinstance(item, dict):
            raise ValueError("writer disposition must be an object")
        table = item.get("table")
        if table not in _TABLE_COLUMNS:
            raise ValueError("writer disposition names an unsupported table")
        expected_fields = {"table", "primary_key", "row_sha256", "task_id", "task_row_sha256"}
        if table == "lease_waits":
            expected_fields.update({"blocked_task_id", "blocked_task_row_sha256"})
        if set(item) != expected_fields:
            raise ValueError("writer disposition has unsupported or missing fields")
        pk = item["primary_key"]
        pk_columns = _PRIMARY_KEYS[table]
        if not isinstance(pk, dict) or set(pk) != set(pk_columns):
            raise ValueError(f"{table} disposition has an invalid primary key")
        normalized_pk = {column: pk[column] for column in pk_columns}
        if any(type(value) not in (str, int, float, bool) or value is None for value in normalized_pk.values()):
            raise ValueError("writer disposition primary key values must be SQLite scalars")
        if any(type(value) is str and (not value or value != value.strip() or "\x00" in value) for value in normalized_pk.values()):
            raise ValueError("writer disposition primary key strings must be canonical")
        row_digest = _sha256(item["row_sha256"], "row_sha256")
        task_row_digest = _sha256(item["task_row_sha256"], "task_row_sha256")
        task_id = item["task_id"]
        if type(task_id) is not str or not task_id or task_id != task_id.strip() or "\x00" in task_id:
            raise ValueError("writer disposition task_id must be a canonical non-empty string")
        disposition = {
            "table": table,
            "primary_key": normalized_pk,
            "row_sha256": row_digest,
            "task_id": task_id,
            "task_row_sha256": task_row_digest,
        }
        if table == "lease_waits":
            blocked_task_id = item["blocked_task_id"]
            if type(blocked_task_id) is not str or not blocked_task_id or blocked_task_id != blocked_task_id.strip() or "\x00" in blocked_task_id:
                raise ValueError("blocked_task_id must be a canonical non-empty string")
            disposition["blocked_task_id"] = blocked_task_id
            disposition["blocked_task_row_sha256"] = _sha256(
                item["blocked_task_row_sha256"], "blocked_task_row_sha256")
        key = _disposition_key(table, normalized_pk)
        if key in seen:
            raise ValueError("duplicate or overlapping writer dispositions")
        seen.add(key)
        dispositions.append(disposition)
    return _freeze({
        "schema": WRITER_MAP_SCHEMA,
        "source_sha256": expected_source,
        "dispositions": dispositions,
    })


def _real_root(value: Any) -> Path:
    if type(value) is not str or not value or value != value.strip() or "\x00" in value:
        raise ValueError("writer disposition requires a canonical repository root")
    path = Path(value)
    if path.is_symlink():
        raise ValueError("writer disposition root cannot be a symlink")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ValueError("writer disposition root must be an existing directory") from exc
    if not resolved.is_dir() or os.path.normcase(str(path.absolute())) != os.path.normcase(str(resolved)):
        raise ValueError("writer disposition root must be a real directory without symlink aliases")
    return resolved


def _same_root(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left)) == os.path.normcase(str(right))


def _task_facts(task_id: str, task_lookup: Callable[[str], Mapping[str, Any]]) -> dict[str, Any]:
    facts = task_lookup(task_id)
    if not isinstance(facts, Mapping):
        raise ValueError("task lookup returned no trusted facts")
    actual_id = facts.get("task_id")
    owner = facts.get("owner")
    root = facts.get("repo_root")
    source_hash = facts.get("source_sha256")
    task_row_hash = facts.get("task_row_sha256")
    if actual_id != task_id:
        raise ValueError("task lookup does not prove the requested task id")
    if type(owner) is not str or not owner or owner != owner.strip() or "\x00" in owner:
        raise ValueError("task lookup must prove a canonical non-empty actual owner")
    return {
        "task_id": task_id,
        "owner": owner,
        "repo_root": _real_root(root),
        "source_sha256": _sha256(source_hash, "task source_sha256"),
        "task_row_sha256": _sha256(task_row_hash, "task_row_sha256"),
    }


def _root_facts(root_id: str, root_lookup: Callable[[str], Any]) -> tuple[Path, str]:
    value = root_lookup(root_id)
    if isinstance(value, Mapping):
        path_value = value.get("root_path")
        source_hash = _sha256(value.get("source_sha256"), "root source_sha256")
    else:
        path_value = value
        source_hash = ""
    return _real_root(path_value), source_hash


def transform_writer_row(
    *,
    table: str,
    row: Mapping[str, Any],
    manifest: Mapping[str, Any],
    task_lookup: Callable[[str], Mapping[str, Any]],
    root_lookup: Callable[[str], Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Transform one pinned legacy lease row, returning row and audit proof."""
    if table not in _TABLE_COLUMNS or not isinstance(row, Mapping):
        raise ValueError("unsupported writer row")
    if not isinstance(manifest, MappingProxyType):
        raise ValueError("writer map must be loaded and validated from its pinned manifest")
    if set(manifest) != {"schema", "source_sha256", "dispositions"} or manifest.get("schema") != WRITER_MAP_SCHEMA:
        raise ValueError("writer map is not a validated supported manifest")
    if type(manifest.get("dispositions")) is not tuple or any(
        not isinstance(item, MappingProxyType)
        or not isinstance(item.get("primary_key"), MappingProxyType)
        for item in manifest["dispositions"]
    ):
        raise ValueError("writer map dispositions must retain loader validation and immutability")
    _sha256(manifest.get("source_sha256"), "manifest source_sha256")
    if set(row) != set(_TABLE_COLUMNS[table]):
        raise ValueError(f"{table} row columns do not match the legacy contract")
    row_digest = typed_row_sha256(table, row)
    pk_columns = _PRIMARY_KEYS[table]
    primary_key = {column: row[column] for column in pk_columns}
    key = _disposition_key(table, primary_key)
    matches = [
        item for item in manifest["dispositions"]
        if item["table"] == table and _disposition_key(table, item["primary_key"]) == key
    ]
    if len(matches) != 1:
        raise ValueError("writer row has no unique explicit disposition")
    disposition = matches[0]
    if disposition["row_sha256"] != row_digest:
        raise ValueError("writer row changed after the map was pinned")

    source_root: Path
    root_source_sha256 = ""
    if table == "leases":
        source_root = _real_root(row["root_path"])
    else:
        source_root, root_source_sha256 = _root_facts(row["root_id"], root_lookup)

    task_facts = _task_facts(disposition["task_id"], task_lookup)
    if task_facts["task_row_sha256"] != disposition["task_row_sha256"]:
        raise ValueError("actual task row changed after the writer map was pinned")
    if not _same_root(task_facts["repo_root"], source_root):
        raise ValueError("mapped task repository root does not exactly match the source lease root")

    mapped = dict(row)
    old_tenant = mapped.pop("tenant")
    mapped["owner"] = task_facts["owner"]
    blocked_facts: dict[str, Any] | None = None
    if table == "lease_waits":
        blocked_facts = _task_facts(disposition["blocked_task_id"], task_lookup)
        if blocked_facts["task_row_sha256"] != disposition["blocked_task_row_sha256"]:
            raise ValueError("actual blocked task row changed after the writer map was pinned")
        if not _same_root(blocked_facts["repo_root"], source_root):
            raise ValueError("blocked task root does not exactly match the source lease root")
        mapped["blocked_by"] = blocked_facts["owner"]

    new_key_columns = ("lease_id", "path") if table == "leases" else (
        "root_id", "owner", "blocked_by", "requested_path",
    )
    new_key = {column: mapped[column] for column in new_key_columns}
    provenance: dict[str, Any] = {
        "schema": WRITER_MAP_SCHEMA,
        "source_sha256": manifest["source_sha256"],
        "table": table,
        "source_primary_key": primary_key,
        "source_row_sha256": row_digest,
        "source_row": dict(row),
        "retired_tenant_value": old_tenant,
        "task": {
            "task_id": task_facts["task_id"],
            "owner": task_facts["owner"],
            "repo_root": str(task_facts["repo_root"]),
            "source_sha256": task_facts["source_sha256"],
            "task_row_sha256": task_facts["task_row_sha256"],
            "source_sha256_scope": SOURCE_SHA256_SCOPE,
        },
        "root": {
            "root_id": row.get("root_id", ""),
            "path": str(source_root),
            "source_sha256": root_source_sha256,
        },
        "new_key": new_key,
    }
    if blocked_facts is not None:
        provenance["blocked_task"] = {
            "task_id": blocked_facts["task_id"],
            "owner": blocked_facts["owner"],
            "repo_root": str(blocked_facts["repo_root"]),
            "source_sha256": blocked_facts["source_sha256"],
            "task_row_sha256": blocked_facts["task_row_sha256"],
            "source_sha256_scope": SOURCE_SHA256_SCOPE,
        }
    return mapped, provenance


def validate_writer_map_usage(
    manifest: Mapping[str, Any], used_primary_keys: Iterable[tuple[str, Mapping[str, Any]]]
) -> None:
    """Reject dispositions that did not match exactly one scanned source row."""
    expected = {
        _disposition_key(item["table"], item["primary_key"])
        for item in manifest.get("dispositions", ())
    }
    used: set[str] = set()
    for table, primary_key in used_primary_keys:
        key = _disposition_key(table, primary_key)
        if key in used:
            raise ValueError("source row consumed a writer disposition more than once")
        used.add(key)
    if used != expected:
        raise ValueError("writer map contains unused dispositions or unaccounted source rows")


def validate_target_key_uniqueness(provenance_rows: Iterable[Mapping[str, Any]]) -> None:
    """Check converted target primary keys before the caller publishes output."""
    seen: set[str] = set()
    for provenance in provenance_rows:
        table = provenance.get("table")
        key = provenance.get("new_key")
        if table not in _TABLE_COLUMNS or not isinstance(key, Mapping):
            raise ValueError("converted writer proof has no target key")
        encoded = json.dumps(
            [table, [(name, _typed_value(value)) for name, value in key.items()]],
            ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        identity = hashlib.sha256(encoded).hexdigest()
        if identity in seen:
            raise ValueError("converted writer rows collide on a target primary key")
        seen.add(identity)

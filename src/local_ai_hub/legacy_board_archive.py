"""Versioned offline archive for the retired global agent board."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

ARCHIVE_NAME = "agent_board.legacy.json"
ARCHIVE_SCHEMA_VERSION = 1
DATABASE_NAME = "agent_board.sqlite"

_ITEM_COLUMNS = (
    "item_id", "title", "status", "priority", "labels_json", "assignee",
    "milestone", "linked_task_id", "details_json", "created_at", "updated_at",
)
_MILESTONE_COLUMNS = ("name", "target_date", "description", "created_at")


def read_legacy_board_archive(state_dir: Path | str) -> list[dict[str, Any]]:
    """Read one verified migration archive; absent archives have no legacy rows."""
    path = Path(state_dir) / ARCHIVE_NAME
    if not path.exists():
        return []
    if path.is_symlink() or not path.is_file():
        raise ValueError("legacy board archive must be a regular file")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("legacy board archive is unreadable") from exc
    if (
        not isinstance(document, dict)
        or set(document) != {"schema_version", "items", "milestones"}
        or document.get("schema_version") != ARCHIVE_SCHEMA_VERSION
        or not isinstance(document.get("items"), list)
        or not isinstance(document.get("milestones"), list)
    ):
        raise ValueError("legacy board archive has an unsupported schema")
    item_ids: set[str] = set()
    for item in document["items"]:
        if (
            not isinstance(item, dict)
            or set(item) != set(_ITEM_COLUMNS) - {"labels_json", "details_json"} | {"labels", "details"}
            or not isinstance(item.get("item_id"), str)
            or not item["item_id"]
            or item["item_id"] in item_ids
            or not isinstance(item.get("labels"), list)
            or not isinstance(item.get("details"), dict)
        ):
            raise ValueError("legacy board archive contains an invalid item")
        item_ids.add(item["item_id"])
    for milestone in document["milestones"]:
        if not isinstance(milestone, dict) or set(milestone) != set(_MILESTONE_COLUMNS):
            raise ValueError("legacy board archive contains an invalid milestone")
    return document["items"]


def migrate_legacy_board_database(state_dir: Path | str) -> None:
    """Export the exact retired SQLite schema, then remove its active database."""
    root = Path(state_dir)
    database = root / DATABASE_NAME
    archive = root / ARCHIVE_NAME
    if not database.exists():
        if any((root / f"{DATABASE_NAME}{suffix}").exists() for suffix in ("-wal", "-shm")):
            raise ValueError("legacy board database sidecar exists without its database")
        if archive.exists():
            read_legacy_board_archive(root)
        return
    if database.is_symlink() or not database.is_file():
        raise ValueError("legacy board database must be a regular file")
    if archive.exists():
        raise ValueError("legacy board database and archive both exist")
    for suffix in ("-wal", "-shm"):
        sidecar = root / f"{DATABASE_NAME}{suffix}"
        if sidecar.is_symlink():
            raise ValueError("legacy board database sidecar must not be a link")

    uri = database.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=15.0)) as connection:
        if connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise ValueError("legacy board database failed integrity check")
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        if tables != {"agent_board_items", "agent_milestones"}:
            raise ValueError("legacy board database has an unsupported table set")
        for table, expected in (("agent_board_items", _ITEM_COLUMNS), ("agent_milestones", _MILESTONE_COLUMNS)):
            actual = tuple(row[1] for row in connection.execute(f'PRAGMA table_info("{table}")'))
            if actual != expected:
                raise ValueError(f"legacy board table {table} has an unsupported schema")
        connection.row_factory = sqlite3.Row
        item_rows = connection.execute(
            "SELECT * FROM agent_board_items ORDER BY updated_at DESC, item_id ASC"
        ).fetchall()
        milestone_rows = connection.execute(
            "SELECT * FROM agent_milestones ORDER BY name ASC"
        ).fetchall()
        items = []
        for row in item_rows:
            item = dict(row)
            try:
                labels = json.loads(item.pop("labels_json"))
                details = json.loads(item.pop("details_json"))
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError("legacy board contains invalid item JSON") from exc
            if not isinstance(labels, list) or not isinstance(details, dict):
                raise ValueError("legacy board contains invalid item JSON types")
            item["labels"] = labels
            item["details"] = details
            items.append(item)
        milestones = [dict(row) for row in milestone_rows]

    document = {
        "schema_version": ARCHIVE_SCHEMA_VERSION,
        "items": items,
        "milestones": milestones,
    }
    temporary = root / f".{ARCHIVE_NAME}.tmp"
    temporary.write_text(json.dumps(document, ensure_ascii=False, sort_keys=True) + os.linesep, encoding="utf-8")
    try:
        read_legacy_board_archive(root) if archive.exists() else _validate_archive_document(document)
        os.replace(temporary, archive)
        read_legacy_board_archive(root)
        for suffix in ("", "-wal", "-shm"):
            (root / f"{DATABASE_NAME}{suffix}").unlink(missing_ok=True)
    except Exception:
        temporary.unlink(missing_ok=True)
        archive.unlink(missing_ok=True)
        raise


def _validate_archive_document(document: dict[str, Any]) -> None:
    items = document.get("items")
    milestones = document.get("milestones")
    if document.get("schema_version") != ARCHIVE_SCHEMA_VERSION or not isinstance(items, list) or not isinstance(milestones, list):
        raise ValueError("legacy board archive has an unsupported schema")
    seen: set[str] = set()
    for item in items:
        if (
            not isinstance(item, dict)
            or set(item) != set(_ITEM_COLUMNS) - {"labels_json", "details_json"} | {"labels", "details"}
            or not isinstance(item.get("item_id"), str)
            or not item["item_id"]
            or item["item_id"] in seen
            or not isinstance(item.get("labels"), list)
            or not isinstance(item.get("details"), dict)
        ):
            raise ValueError("legacy board archive contains an invalid item")
        seen.add(item["item_id"])
    if any(not isinstance(row, dict) or set(row) != set(_MILESTONE_COLUMNS) for row in milestones):
        raise ValueError("legacy board archive contains an invalid milestone")

"""Dry-run or remove orphaned derived code-index trigrams in bounded batches."""

from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from local_ai_hub.code_index import CodeIndex
from local_ai_hub.config import load_config
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.sqlite_support import compact_sqlite_database
try:
    from tools.compact_code_index import _hub_is_online
except ModuleNotFoundError as exc:  # direct `python tools/cleanup_code_index.py`
    if exc.name != "tools":
        raise
    from compact_code_index import _hub_is_online


def _active_preprocessing_roots(database: Path) -> tuple[str, ...] | None:
    """Read active roots fail-closed; cleanup must never guess this snapshot."""
    if not database.is_file() or database.is_symlink():
        return None
    try:
        uri = database.resolve(strict=True).as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=2.0)) as con:
            con.execute("PRAGMA busy_timeout=2000")
            return tuple(
                str(row[0]) for row in con.execute(
                    "SELECT root FROM projects WHERE status='running' ORDER BY root"
                )
            )
    except (OSError, RuntimeError, sqlite3.Error, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="measure only (default)")
    mode.add_argument("--apply", action="store_true", help="delete bounded batches of orphan rows")
    parser.add_argument("--max-rows", type=int, default=100000)
    parser.add_argument("--max-roots", type=int, default=64)
    parser.add_argument("--batches", type=int, default=1, help="apply up to this many bounded batches")
    parser.add_argument("--compact", action="store_true", help="VACUUM after apply; requires --apply")
    args = parser.parse_args(argv)

    try:
        config = load_config(probe_hardware=False)
        server = config.get("server", {})
        state_dir = Path(server["state_dir"])
        online = _hub_is_online(
            str(server.get("host", "127.0.0.1")),
            int(server.get("port", 11435)),
            state_dir,
        )
        database = state_dir / "code-index.sqlite3"
        if args.apply and online is not False:
            error = "hub_online" if online is True else "hub_state_unknown"
            print(json.dumps({"success": False, "error": error, "path": str(database)}))
            return 2
        if not 1 <= args.batches <= 32 or not 1 <= args.max_rows <= 100000 or not 1 <= args.max_roots <= 128:
            print(json.dumps({"success": False, "error": "batch limits out of range"}))
            return 2
        if args.compact and not args.apply:
            print(json.dumps({"success": False, "error": "--compact requires --apply"}))
            return 2

        index = CodeIndex(config, RepositoryTools(config), read_only=not args.apply)
        index.set_active_roots_provider(
            lambda: _active_preprocessing_roots(state_dir / "preprocess.sqlite3")
        )
        try:
            batches: list[dict[str, Any]] = []
            for _ in range(args.batches if args.apply else 1):
                result = index.prune_orphaned_trigrams(
                    dry_run=not args.apply,
                    max_rows=args.max_rows,
                    max_roots=args.max_roots,
                )
                batches.append(result)
                if result.get("success") is not True or not args.apply:
                    break
                if not result.get("has_more") or result.get("rows_pruned", 0) == 0:
                    break
        finally:
            index.close()
        result = {
            "success": bool(batches) and all(item.get("success") is True for item in batches),
            "dry_run": not args.apply,
            "hub_online": online,
            "path": str(database),
            "batches": batches,
            "rows_pruned": sum(int(item.get("rows_pruned", 0)) for item in batches),
            "has_more": bool(batches and batches[-1].get("has_more")),
        }
        if args.compact and result["success"]:
            result["compaction"] = compact_sqlite_database(
                database, dry_run=False, offline_confirmed=True,
            )
            result["success"] = result["compaction"].get("success") is True
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result.get("success") is True else 1
    except Exception as exc:  # pragma: no cover - guarded CLI boundary
        print(json.dumps({"success": False, "error": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

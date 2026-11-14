from __future__ import annotations

import ast
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from .migration_sql import split_sql_statements

def detect_migration_drift(
    root: str,
    db_path: str | None = None,
    *,
    bounded_schema_files,
    connect_sqlite_fn,
    max_schema_db_bytes: int,
    schema_db_timeout_seconds: float,
    max_schema_scan_seconds: float,
    max_schema_db_tables: int,
    max_schema_db_columns: int,
    max_schema_migration_db_bytes: int,
    max_schema_file_bytes: int,
    max_schema_total_bytes: int,
) -> dict[str, Any]:
        """Detect drift between a live SQLite schema and SQL migrations or declared models."""
        p_root = Path(root).expanduser().resolve(strict=False)
        db_file: Path | None = None
        if db_path:
            p = Path(db_path).expanduser()
            db_file = p if p.is_absolute() else (p_root / p)
        else:
            for cand in [p_root / "app.db", p_root / "data.db", p_root / ".local-ai-hub" / "agent_state.db"]:
                if cand.is_file():
                    db_file = cand
                    break

        if not db_file or not db_file.is_file():
            if not db_path:
                return {
                    "success": False,
                    "db_path": None,
                    "db_tables": [],
                    "code_models_found": [],
                    "drift_detected": None,
                    "in_sync": None,
                    "missing_tables_in_db": [],
                    "extra_tables_in_db": [],
                    "column_drifts": [],
                    "drift": {},
                    "status": "database_missing",
                    "message": "No SQLite database found at default paths",
                    "error": "Cannot determine migration drift without a live SQLite database",
                    "terminal": True,
                    "retryable": False,
                }
            return {
                "success": False,
                "db_path": str(db_file or db_path),
                "drift_detected": None,
                "in_sync": None,
                "status": "database_missing",
                "error": f"SQLite database not found at {db_path}",
                "terminal": True,
                "retryable": False,
            }

        try:
            db_file = db_file.expanduser().resolve(strict=True)
            db_file.relative_to(p_root)
            if db_file.stat().st_size > max_schema_db_bytes:
                return {
                    "success": False,
                    "db_path": str(db_file),
                    "drift_detected": None,
                    "in_sync": None,
                    "status": "database_size_limit_exceeded",
                    "error": f"SQLite database exceeds {max_schema_db_bytes} bytes",
                    "terminal": True,
                    "retryable": False,
                }
        except ValueError:
            return {
                "success": False,
                "db_path": str(db_path or db_file),
                "drift_detected": None,
                "in_sync": None,
                "status": "database_path_outside_root",
                "error": "SQLite database path must resolve inside the requested root",
                "terminal": True,
                "retryable": False,
            }
        except OSError as exc:
            return {
                "success": False,
                "db_path": str(db_path or db_file),
                "drift_detected": None,
                "in_sync": None,
                "status": "database_missing",
                "error": f"SQLite database not found: {exc}",
            }

        db_tables: dict[str, set[str]] = {}
        try:
            with closing(
                connect_sqlite_fn(
                    db_file,
                    timeout_seconds=schema_db_timeout_seconds,
                    read_only=True,
                )
            ) as con:
                db_deadline = time.monotonic() + max_schema_scan_seconds
                con.set_progress_handler(
                    lambda: int(time.monotonic() >= db_deadline), 1000
                )
                table_cursor = con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
                total_db_columns = 0
                for table_row in table_cursor:
                    if time.monotonic() >= db_deadline:
                        raise TimeoutError("SQLite schema inspection exceeded its time budget")
                    tbl = table_row[0]
                    if len(db_tables) >= max_schema_db_tables:
                        raise ValueError(
                            f"SQLite schema exceeds {max_schema_db_tables} tables"
                        )
                    safe_tbl = tbl.replace('"', '""')
                    cols: set[str] = set()
                    for column_row in con.execute(f'PRAGMA table_xinfo("{safe_tbl}")'):
                        if time.monotonic() >= db_deadline:
                            raise TimeoutError(
                                "SQLite schema inspection exceeded its time budget"
                            )
                        total_db_columns += 1
                        if total_db_columns > max_schema_db_columns:
                            raise ValueError(
                                f"SQLite schema exceeds {max_schema_db_columns} columns"
                            )
                        cols.add(column_row[1])
                    db_tables[tbl] = cols
        except Exception as exc:
            return {
                "success": False,
                "db_path": str(db_file),
                "drift_detected": None,
                "in_sync": None,
                "status": "database_inspection_failed",
                "error": f"failed to inspect SQLite schema: {exc}",
            }

        code_tables: dict[str, set[str]] = {}
        schema_source = "python_models"
        migration_files: list[Path] = []
        schema_scan_deadline = time.monotonic() + max_schema_scan_seconds
        try:
            migration_files = bounded_schema_files(
                p_root, suffix=".sql", deadline=schema_scan_deadline, migrations_only=True
            )
        except TimeoutError as exc:
            return {
                "success": False,
                "db_path": str(db_file),
                "drift_detected": None,
                "in_sync": None,
                "status": "schema_scan_budget_exceeded",
                "error": str(exc),
                "terminal": True,
                "retryable": False,
            }
        except OSError as exc:
            return {
                "success": False,
                "db_path": str(db_file),
                "drift_detected": None,
                "in_sync": None,
                "status": "schema_scan_failed",
                "error": f"migration directory scan failed: {exc}",
            }
        if migration_files:
            schema_source = "sql_migrations"
            migration_db = connect_sqlite_fn(":memory:", timeout_seconds=5.0)
            migration_db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, max_schema_file_bytes)
            migration_db.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, max_schema_file_bytes)


            try:
                migration_db.setlimit(
                    sqlite3.SQLITE_LIMIT_LENGTH, max_schema_migration_db_bytes
                )
                page_size = int(migration_db.execute("PRAGMA page_size").fetchone()[0])
                max_pages = max(1, max_schema_migration_db_bytes // page_size)
                migration_db.execute(f"PRAGMA max_page_count={max_pages}")
                migration_deadline = time.monotonic() + max_schema_scan_seconds
                migration_db.set_progress_handler(
                    lambda: int(time.monotonic() >= migration_deadline), 1000
                )
                total_migration_bytes = 0
                migration_ddl_count = 0
                for migration_path in migration_files:
                    if time.monotonic() >= schema_scan_deadline:
                        return {
                            "success": False,
                            "db_path": str(db_file),
                            "drift_detected": None,
                            "in_sync": None,
                            "status": "schema_scan_budget_exceeded",
                            "error": "migration scan exceeded its time budget",
                            "terminal": True,
                            "retryable": False,
                        }
                    with migration_path.open("rb") as migration_stream:
                        raw_source = migration_stream.read(max_schema_file_bytes + 1)
                    total_migration_bytes += len(raw_source)
                    if (
                        len(raw_source) > max_schema_file_bytes
                        or total_migration_bytes > max_schema_total_bytes
                    ):
                        return {
                            "success": False,
                            "db_path": str(db_file),
                            "drift_detected": None,
                            "in_sync": None,
                            "status": "schema_scan_budget_exceeded",
                            "error": "migration SQL exceeds the bounded scan budget",
                            "terminal": True,
                            "retryable": False,
                        }
                    source = raw_source.decode("utf-8", errors="replace")

                    for statement in split_sql_statements(source):
                        if time.monotonic() >= migration_deadline:
                            raise TimeoutError("migration replay exceeded its time budget")
                        normalized = re.sub(r"(?m)^\s*--[^\n]*", "", statement)
                        normalized = re.sub(r"/\*.*?\*/", "", normalized, flags=re.DOTALL).strip()
                        if not re.match(r"^(?:CREATE\s+TABLE|ALTER\s+TABLE|DROP\s+TABLE)\b", normalized, re.IGNORECASE):
                            continue
                        try:
                            migration_db.execute(statement)
                            migration_ddl_count += 1
                        except sqlite3.Error as exc:
                            rel_path = migration_path.relative_to(p_root).as_posix()
                            return {
                                "success": False,
                                "drift_detected": None,
                                "in_sync": None,
                                "error": f"failed to apply schema DDL in {rel_path}: {exc}",
                            }
                if migration_ddl_count == 0:
                    return {
                        "success": False,
                        "drift_detected": None,
                        "in_sync": None,
                        "error": "no supported table schema DDL found in SQL migrations",
                    }
                tables = migration_db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
                total_code_columns = 0
                for (table_name,) in tables:
                    if len(code_tables) >= max_schema_db_tables:
                        raise ValueError("migration schema table limit exceeded")
                    safe_table = str(table_name).replace('"', '""')
                    columns: set[str] = set()
                    for row in migration_db.execute(f'PRAGMA table_xinfo("{safe_table}")'):
                        total_code_columns += 1
                        if total_code_columns > max_schema_db_columns:
                            raise ValueError("migration schema column limit exceeded")
                        if time.monotonic() >= migration_deadline:
                            raise TimeoutError("migration schema inspection exceeded its time budget")
                        columns.add(row[1])
                    code_tables[str(table_name)] = columns
            except (OSError, sqlite3.Error, ValueError, TimeoutError) as exc:
                return {"success": False, "drift_detected": None, "in_sync": None,
                        "error": f"failed to read schema migrations: {exc}"}
            finally:
                migration_db.close()
        else:
            python_scan_deadline = time.monotonic() + max_schema_scan_seconds
            try:
                python_files = bounded_schema_files(
                    p_root, suffix=".py", deadline=python_scan_deadline
                )
            except TimeoutError as exc:
                return {
                    "success": False,
                    "db_path": str(db_file),
                    "drift_detected": None,
                    "in_sync": None,
                    "status": "schema_scan_budget_exceeded",
                    "error": str(exc),
                    "terminal": True,
                    "retryable": False,
                }
            except OSError as exc:
                return {
                    "success": False,
                    "db_path": str(db_file),
                    "drift_detected": None,
                    "in_sync": None,
                    "status": "schema_scan_failed",
                    "error": f"Python model directory scan failed: {exc}",
                }
            total_python_bytes = 0
            for p in python_files:
                if time.monotonic() >= python_scan_deadline:
                    return {
                        "success": False,
                        "db_path": str(db_file),
                        "drift_detected": None,
                        "in_sync": None,
                        "status": "schema_scan_budget_exceeded",
                        "error": "Python model scan exceeded its time budget",
                        "terminal": True,
                        "retryable": False,
                    }
                try:
                    with p.open("rb") as source_stream:
                        raw_source = source_stream.read(max_schema_file_bytes + 1)
                    total_python_bytes += len(raw_source)
                    if (
                        len(raw_source) > max_schema_file_bytes
                        or total_python_bytes > max_schema_total_bytes
                    ):
                        return {
                            "success": False,
                            "db_path": str(db_file),
                            "drift_detected": None,
                            "in_sync": None,
                            "status": "schema_scan_budget_exceeded",
                            "error": "Python model sources exceed the bounded scan budget",
                            "terminal": True,
                            "retryable": False,
                        }
                    source_text = raw_source.decode("utf-8", errors="replace")
                    relative_parts = p.relative_to(p_root).parts
                    model_source_names = {
                        "model.py", "models.py", "schema.py", "schemas.py",
                        "entity.py", "entities.py",
                    }
                    model_source_dirs = {
                        "model", "models", "schema", "schemas", "entity", "entities",
                    }
                    if (
                        re.search(r"(?m)^\s*__tablename__\s*=", source_text) is None
                        and p.name.lower() not in model_source_names
                        and not any(
                            part.lower() in model_source_dirs for part in relative_parts[:-1]
                        )
                    ):
                        continue
                    tree = ast.parse(source_text, filename=str(p))
                    for node_index, node in enumerate(ast.walk(tree)):
                        if node_index % 256 == 0 and time.monotonic() >= python_scan_deadline:
                            return {
                                "success": False,
                                "db_path": str(db_file),
                                "drift_detected": None,
                                "in_sync": None,
                                "status": "schema_scan_budget_exceeded",
                                "error": "Python model scan exceeded its time budget",
                                "terminal": True,
                                "retryable": False,
                            }
                        if isinstance(node, ast.ClassDef):
                            tbl_name = None
                            cols: set[str] = set()
                            for item in node.body:
                                if isinstance(item, ast.Assign):
                                    for target in item.targets:
                                        if isinstance(target, ast.Name) and target.id == "__tablename__" and isinstance(item.value, ast.Constant):
                                            tbl_name = str(item.value.value)
                                elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                                    cols.add(item.target.id)
                            if tbl_name:
                                code_tables[tbl_name] = cols
                except Exception as exc:
                    rel_path = p.relative_to(p_root).as_posix()
                    return {
                        "success": False,
                        "db_path": str(db_file),
                        "drift_detected": None,
                        "in_sync": None,
                        "status": "schema_scan_failed",
                        "error": f"failed to inspect Python model source {rel_path}: {exc}",
                    }
                if time.monotonic() >= python_scan_deadline:
                    return {
                        "success": False,
                        "db_path": str(db_file),
                        "drift_detected": None,
                        "in_sync": None,
                        "status": "schema_scan_budget_exceeded",
                        "error": "Python model scan exceeded its time budget",
                        "terminal": True,
                        "retryable": False,
                    }

        if not code_tables:
            return {
                "success": False,
                "db_path": str(db_file),
                "schema_source": schema_source,
                "migration_files_found": [p.relative_to(p_root).as_posix() for p in migration_files],
                "db_tables": list(db_tables.keys()),
                "code_models_found": [],
                "drift_detected": None,
                "in_sync": None,
                "missing_tables_in_db": [],
                "extra_tables_in_db": [],
                "column_drifts": [],
                "drift": {},
                "status": "schema_source_unavailable",
                "error": "No SQL migration schema or declared Python model tables were found",
                "terminal": True,
                "retryable": False,
            }

        # SQLite identifier matching folds ASCII only; Unicode casefold would
        # incorrectly merge distinct non-ASCII names accepted by SQLite.
        ascii_lower = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
        db_names = {name.translate(ascii_lower): name for name in db_tables}
        code_names = {name.translate(ascii_lower): name for name in code_tables}
        missing_in_db = sorted(name for key, name in code_names.items() if key not in db_names)
        extra_in_db = sorted(name for key, name in db_names.items() if key not in code_names)
        column_drifts: list[dict[str, Any]] = []
        for key, t in sorted(code_names.items()):
            if key in db_names:
                declared = {column.translate(ascii_lower): column for column in code_tables[t]}
                actual = {column.translate(ascii_lower): column for column in db_tables[db_names[key]]}
                missing_cols = sorted(column for name, column in declared.items() if name not in actual)
                extra_cols = sorted(column for name, column in actual.items() if name not in declared) if declared else []
                if missing_cols or extra_cols:
                    column_drifts.append({
                        "table": t,
                        "missing_in_db": missing_cols,
                        "extra_in_db": extra_cols,
                    })

        drift_map: dict[str, Any] = {}
        for cd in column_drifts:
            drift_map[cd["table"]] = {
                "missing_in_db": cd["missing_in_db"],
                "missing_in_code": cd["extra_in_db"],
                "type_mismatches": {},
            }
        for t in missing_in_db:
            drift_map[t] = {
                "missing_in_db": sorted(code_tables.get(t, [])),
                "missing_in_code": [],
                "type_mismatches": {},
            }
        if schema_source == "sql_migrations":
            for t in extra_in_db:
                drift_map[t] = {
                    "missing_in_db": [],
                    "missing_in_code": sorted(db_tables.get(t, [])),
                    "type_mismatches": {},
                }

        drift_detected = bool(missing_in_db or column_drifts or (schema_source == "sql_migrations" and extra_in_db))
        return {
            "success": True,
            "db_path": str(db_file),
            "schema_source": schema_source,
            "migration_files_found": [p.relative_to(p_root).as_posix() for p in migration_files],
            "db_tables": list(db_tables.keys()),
            "code_models_found": list(code_tables.keys()),
            "drift_detected": drift_detected,
            "in_sync": not drift_detected,
            "missing_tables_in_db": missing_in_db,
            "extra_tables_in_db": extra_in_db,
            "column_drifts": column_drifts,
            "drift": drift_map,
            "status": "drift_detected" if drift_detected else "in_sync",
        }

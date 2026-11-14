from __future__ import annotations

import io as _io
from pathlib import Path as _Path
from typing import Any


def build_dataset(
    engine: Any,
    root: str,
    schema_or_model: dict[str, Any] | list[Any],
    count: int,
    format: str,
    *,
    path_type: Any = _Path,
    json_dumps: Any,
    io_module: Any = _io,
) -> dict[str, Any]:
    import uuid
    resolved_root = path_type(engine._root(root))
    n = max(1, min(int(count), 1000))
    fields: dict[str, str] = {}
    if isinstance(schema_or_model, dict):
        fields = {str(k): str(v).lower() for k, v in schema_or_model.items()}
    elif isinstance(schema_or_model, list):
        for item in schema_or_model:
            if isinstance(item, dict):
                fields[str(item.get("name", "field"))] = str(item.get("type", "str")).lower()
            else:
                fields[str(item)] = "str"
    else:
        fields = {"id": "uuid", "name": "str", "status": "str"}

    dataset_seed = repr(tuple(fields.items()))
    rows: list[dict[str, Any]] = []
    for i in range(1, n + 1):
        row: dict[str, Any] = {}
        for col, ctype in fields.items():
            if "uuid" in ctype or col.lower() in ("id", "guid"):
                row[col] = uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{dataset_seed}:{col}:{i}",
                ).hex[:12]
            elif "int" in ctype or col.lower() in ("age", "count", "seq", "index"):
                row[col] = i * 10
            elif "float" in ctype or col.lower() in ("price", "amount", "score", "rate"):
                row[col] = round(10.0 + (i * 3.5), 2)
            elif "bool" in ctype or col.lower() in ("active", "enabled", "valid", "is_admin"):
                row[col] = (i % 2 == 0)
            elif "email" in ctype or "email" in col.lower():
                row[col] = f"user_{i}@example.com"
            elif "date" in ctype or "time" in col.lower():
                row[col] = f"2026-09-12T12:{i % 60:02d}:00Z"
            else:
                row[col] = f"{col.capitalize()}_{i}"
        rows.append(row)

    fmt = format.lower()
    if fmt == "csv":
        import csv
        out = io_module.StringIO()
        writer = csv.DictWriter(out, fieldnames=list(fields.keys()))
        writer.writeheader()
        writer.writerows(rows)
        rendered = out.getvalue()
    elif fmt in ("sqlite", "sql"):
        lines = []
        table = "test_dataset"
        cols = ", ".join(f'"{c}"' for c in fields.keys())
        for r in rows:
            vals = ", ".join(f"'{v}'" if isinstance(v, str) else str(v).lower() if isinstance(v, bool) else str(v) for v in r.values())
            lines.append(f"INSERT INTO {table} ({cols}) VALUES ({vals});")
        rendered = "\n".join(lines)
    else:
        rendered = json_dumps(rows, indent=2)

    return {
        "success": True,
        "root": str(resolved_root),
        "count": len(rows),
        "format": fmt,
        "fields": list(fields.keys()),
        "data": rendered,
        "rows": rows[:50],
    }


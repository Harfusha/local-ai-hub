"""Synthetic microbenchmark for bounded code-index inventory reads."""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
import time
import tracemalloc
from collections.abc import Callable


_QUERY = "SELECT path, content_hash, size FROM file_refs ORDER BY path"


def _allowed(path: str) -> bool:
    index = int(path.rsplit("_", 1)[1].split(".", 1)[0])
    return index % 11 != 0


def _materialize_all(connection: sqlite3.Connection) -> dict[str, str]:
    refs = [
        (str(row["path"]), str(row["content_hash"]), int(row["size"] or 0))
        for row in connection.execute(_QUERY).fetchall()
    ]
    refs = [(path, digest) for path, digest, _size in refs if _allowed(path)]
    return {path: digest for path, digest in refs}


def _materialize_bounded(
    connection: sqlite3.Connection, batch_size: int,
) -> dict[str, str]:
    cursor = connection.execute(_QUERY)
    allowed: dict[str, str] = {}
    while True:
        batch = cursor.fetchmany(batch_size)
        if not batch:
            break
        for row in batch:
            path = str(row["path"])
            if _allowed(path):
                allowed[path] = str(row["content_hash"])
    return allowed


def _measure(fn: Callable[[], dict[str, str]], repeats: int) -> tuple[dict[str, float], dict[str, str]]:
    elapsed_ms: list[float] = []
    peak_bytes: list[int] = []
    reference: dict[str, str] | None = None
    for _ in range(repeats):
        tracemalloc.start()
        started = time.perf_counter()
        result = fn()
        elapsed_ms.append((time.perf_counter() - started) * 1000)
        _current, peak = tracemalloc.get_traced_memory()
        peak_bytes.append(peak)
        tracemalloc.stop()
        if reference is None:
            reference = result
        elif result != reference:
            raise RuntimeError("inventory implementations returned different paths")
        del result
    ordered = sorted(elapsed_ms)
    return (
        {
            "median_ms": round(statistics.median(elapsed_ms), 2),
            "p95_ms_nearest_rank": round(ordered[math.ceil(0.95 * repeats) - 1], 2),
            "median_peak_python_bytes": int(statistics.median(peak_bytes)),
        },
        reference or {},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=50_000)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--batch-size", type=int, default=256)
    args = parser.parse_args()
    if args.rows < 1 or args.repeats < 1 or args.batch_size < 1:
        parser.error("rows, repeats, and batch-size must be positive")

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE file_refs(path TEXT, content_hash TEXT, size INTEGER)"
    )
    connection.executemany(
        "INSERT INTO file_refs VALUES(?,?,?)",
        (
            (f"pkg/module_{index:06}.py", f"hash-{index}", 128)
            for index in range(args.rows)
        ),
    )
    connection.commit()
    old, old_paths = _measure(lambda: _materialize_all(connection), args.repeats)
    bounded, bounded_paths = _measure(
        lambda: _materialize_bounded(connection, args.batch_size), args.repeats,
    )
    if old_paths != bounded_paths:
        raise RuntimeError("bounded inventory differs from full-scan baseline")
    print(json.dumps({
        "dataset": "synthetic in-memory SQLite; warm query cache",
        "rows": args.rows,
        "repeats": args.repeats,
        "batch_size": args.batch_size,
        "eligible_paths": len(old_paths),
        "results": {"full_materialization": old, "bounded_batches": bounded},
    }, separators=(",", ":")))
    connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Measure pending RAG selection with and without the former inventory scan.

Synthetic SQLite fixture; no embeddings, filesystem indexing, HTTP or service timing.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import tempfile
import threading
import time
from contextlib import closing
from pathlib import Path

from local_ai_hub.preprocess import ProjectPreprocessor


class _Selected(Exception):
    pass


class _StopOnSelection:
    def semantic_needed(self, root, path):
        raise _Selected


class _Connection:
    def __init__(self, path: Path, legacy_scan: bool):
        self.con = sqlite3.connect(path)
        self.con.row_factory = sqlite3.Row
        self.legacy_scan = legacy_scan

    def execute(self, sql, params=()):
        result = self.con.execute(sql, params)
        if self.legacy_scan and "SELECT path,content_hash FROM file_refs" in sql:
            self.con.execute("SELECT path FROM file_refs WHERE root=? ORDER BY path", (params[0],)).fetchall()
        return result

    def close(self):
        self.con.close()


def run(files: int, repeats: int) -> dict:
    if files < 1 or repeats < 1:
        raise ValueError("files and repeats must be positive")
    with tempfile.TemporaryDirectory(prefix="hub-preprocess-benchmark-") as directory:
        root = str(Path(directory) / "repo")
        db = Path(directory) / "fixture.sqlite"
        with closing(sqlite3.connect(db)) as con:
            con.execute("CREATE TABLE file_refs(root TEXT, path TEXT, content_hash TEXT, needs_hash INTEGER, rag_hash TEXT, last_accessed_at REAL, size INTEGER, PRIMARY KEY(root,path))")
            con.executemany("INSERT INTO file_refs VALUES(?,?,?,0,NULL,0,10)",
                            ((root, f"src/file_{i:06}.py", "hash") for i in range(files)))
            con.commit()
        pre = ProjectPreprocessor.__new__(ProjectPreprocessor)
        pre._db_lock = threading.RLock()
        pre._yield = lambda: False
        pre.cfg = {"rag_files_per_step": 128}
        pre.deterministic = _StopOnSelection()
        samples = {"legacy_scan": [], "current": []}
        for _ in range(repeats):
            for name, legacy in (("legacy_scan", True), ("current", False)):
                pre._connect = lambda legacy=legacy: _Connection(db, legacy)
                started = time.perf_counter()
                try:
                    pre._step_rag({"root": root, "workspace": "fixture"})
                except _Selected:
                    samples[name].append((time.perf_counter() - started) * 1000)
                else:
                    raise RuntimeError("pending selection did not run")
        return {"scope": "synthetic pending RAG selection; legacy_scan simulates removed inventory query",
                "files": files, "repeats": repeats,
                "samples_ms": samples,
                "median_ms": {name: statistics.median(values) for name, values in samples.items()}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=int, default=10000)
    parser.add_argument("--repeats", type=int, default=7)
    args = parser.parse_args()
    print(json.dumps(run(args.files, args.repeats), indent=2))


if __name__ == "__main__":
    main()

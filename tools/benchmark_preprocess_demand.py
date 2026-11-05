"""Measure synthetic or repository-sampled file-card scheduling.

Only queue selection and simulated completion are measured; no model inference runs.
Repository mode reads a bounded set of small text files and stores the fixture outside the checkout.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import statistics
import tempfile
import threading
import time
from contextlib import closing
from pathlib import Path

from local_ai_hub.preprocess import ProjectPreprocessor, _ensure_file_refs_revision_tracking
from local_ai_hub.repo_tools import RepositoryTools


_TEXT_SUFFIXES = {".css", ".html", ".js", ".json", ".jsx", ".md", ".ps1", ".py", ".rst",
                  ".sh", ".sql", ".toml", ".ts", ".tsx", ".txt", ".yaml", ".yml"}
_SKIP_DIRS = {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".serena", ".venv",
              "__pycache__", "build", "dist", "node_modules", "target", "venv"}
_MAX_REPOSITORY_BYTES = 64 * 1024 * 1024
_MAX_REPOSITORY_ENTRIES = 50_000


class _Learner:
    def __init__(self, enabled: bool, query: str = "rare_demand"):
        self.enabled = enabled
        self.query = query

    def hot_queries(self, root, limit):
        return [self.query] if self.enabled else []


def _repository_fixture(root: str, max_files: int) -> tuple[str, list[tuple], list[tuple], dict]:
    requested = Path(root).expanduser()
    if (requested.is_symlink()
            or getattr(os.path, "isjunction", lambda _path: False)(str(requested))
            or not requested.is_dir()):
        raise ValueError("root must be an existing, non-symlink directory")
    resolved = requested.resolve(strict=True)
    repo_root = str(resolved)
    file_rows: list[tuple] = []
    fts_rows: list[tuple] = []
    total_bytes = 0
    entries_examined = 0
    entry_scan_capped = False
    for directory, dirs, names in os.walk(resolved, topdown=True, followlinks=False):
        current = Path(directory)
        entries_examined += len(dirs) + len(names)
        if entries_examined > _MAX_REPOSITORY_ENTRIES:
            entry_scan_capped = True
            break
        dirs[:] = sorted(name for name in dirs
                         if name.lower() not in _SKIP_DIRS
                         and not (current / name).is_symlink()
                         and not getattr(os.path, "isjunction", lambda _path: False)(str(current / name)))
        for name in sorted(names):
            path = current / name
            if path.suffix.lower() not in _TEXT_SUFFIXES or path.is_symlink():
                continue
            try:
                size = path.stat(follow_symlinks=False).st_size
                if size > 180_000 or total_bytes + size > _MAX_REPOSITORY_BYTES:
                    continue
                content = path.read_bytes().decode("utf-8")
            except (OSError, UnicodeError):
                continue
            if "\x00" in content:
                continue
            relative = path.relative_to(resolved).as_posix()
            file_rows.append((repo_root, relative, size, None, 0))
            fts_rows.append((repo_root, relative, content))
            total_bytes += size
            if len(file_rows) >= max_files:
                break
        if (entry_scan_capped or len(file_rows) >= max_files
                or total_bytes >= _MAX_REPOSITORY_BYTES):
            break
    if len(file_rows) < 2:
        raise ValueError("root yielded fewer than two bounded text files")
    return repo_root, file_rows, fts_rows, {
        "directory_entries_examined": entries_examined,
        "entry_scan_capped": entry_scan_capped,
        "file_limit_reached": len(file_rows) >= max_files,
    }


def _p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def run(files: int = 4096, batch_size: int = 64, *, root: str | None = None,
        query: str = "rare_demand") -> dict:
    if files < 2 or batch_size < 2:
        raise ValueError("files and batch_size must be at least two")
    if root is not None and (not query.strip() or len(query) > 120):
        raise ValueError("query must be non-empty and at most 120 characters in repository mode")
    with tempfile.TemporaryDirectory(prefix="hub-demand-benchmark-") as directory:
        db = Path(directory) / "fixture.sqlite"
        if root is None:
            repo_root = str(Path(directory) / "repo")
            file_rows = [(repo_root, f"file_{i:06}.py", 10, None, 0) for i in range(files)]
            fts_rows = [(repo_root, row[1], "rare_demand" if i == files - 1 else "ordinary")
                        for i, row in enumerate(file_rows)]
            hot_files = {f"file_{files - 1:06}.py"}
            scope = "synthetic file-card queue selection, no model inference"
            sample = {}
        else:
            repo_root, file_rows, fts_rows, sample = _repository_fixture(root, files)
            terms = RepositoryTools({})._terms(query)[:8]
            if not terms:
                raise ValueError("query contains no searchable terms")
            expression = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
            with closing(sqlite3.connect(db)) as con:
                con.execute("CREATE VIRTUAL TABLE source_fts USING fts5(root UNINDEXED,path UNINDEXED,content)")
                con.executemany("INSERT INTO source_fts VALUES(?,?,?)", fts_rows)
                hot_files = {str(row[0]) for row in con.execute(
                    "SELECT path FROM source_fts WHERE root=? AND source_fts MATCH ?", (repo_root, expression)
                )}
                con.commit()
            if not hot_files:
                raise ValueError("query matched no files in the bounded repository sample")
            scope = "repository text file-card queue selection, no model inference"
        with closing(sqlite3.connect(db)) as con:
            con.execute("CREATE TABLE file_refs(root TEXT, path TEXT, size INTEGER, card_key TEXT, last_accessed_at REAL, PRIMARY KEY(root,path))")
            if root is None:
                con.execute("CREATE VIRTUAL TABLE source_fts USING fts5(root UNINDEXED,path UNINDEXED,content)")
                con.executemany("INSERT INTO source_fts VALUES(?,?,?)", fts_rows)
            _ensure_file_refs_revision_tracking(con)
            con.executemany("INSERT INTO file_refs VALUES(?,?,?,?,?)", file_rows)
            con.commit()

        def connect():
            con = sqlite3.connect(db)
            con.row_factory = sqlite3.Row
            return con

        pre = ProjectPreprocessor.__new__(ProjectPreprocessor)
        pre._connect, pre._db_lock = connect, threading.RLock()
        pre._demand_priority_cache, pre._demand_priority_lock = {}, threading.Lock()
        pre.cfg, pre.repo_tools = {}, RepositoryTools({})
        hot = sorted(hot_files)[0]
        output = {"scope": scope, "files": len(file_rows), "batch_size": batch_size,
                  "query_match_count": len(hot_files), "useful_context_verified": False,
                  "cache_revision_tracking": True}
        if root is not None:
            output.update({"repository": Path(repo_root).name, "query": query,
                           "sampled_bytes": sum(row[2] for row in file_rows),
                           "sampled_files": len(file_rows), **sample})
        for name, enabled in (("baseline", False), ("demand", True)):
            with closing(connect()) as con:
                con.execute("UPDATE file_refs SET card_key=NULL")
                con.commit()
            pre.learner = _Learner(enabled, query if root is not None else "rare_demand")
            samples = []
            batches = 0
            batches_to_hot = None
            batches_to_first_hot = None
            regular_first = 0
            hot_first = 0
            completed = set()
            while True:
                start = time.perf_counter()
                selected = [str(row["path"]) for row in pre._find_next_files(repo_root, batch_size)]
                samples.append((time.perf_counter() - start) * 1000)
                if not selected:
                    break
                batches += 1
                if batches == 1:
                    hot_first = sum(path in hot_files for path in selected)
                    regular_first = len(selected) - hot_first
                if hot_files.intersection(selected) and batches_to_first_hot is None:
                    batches_to_first_hot = batches
                if hot in selected:
                    batches_to_hot = batches
                completed.update(selected)
                with closing(connect()) as con:
                    con.executemany("UPDATE file_refs SET card_key='done' WHERE root=? AND path=?", ((repo_root, path) for path in selected))
                    con.commit()
            if not hot_files.issubset(completed):
                raise RuntimeError("one or more hot files were never selected")
            output[name] = {"batches_to_hot": batches_to_hot,
                            "batches_to_first_query_match": batches_to_first_hot,
                            "query_matches_selected_first_batch": hot_first,
                            "batches_to_complete": batches,
                            "completed_files": len(completed), "unprocessed_files": len(file_rows) - len(completed),
                            "regular_files_in_first_batch": regular_first,
                            "selection_median_ms": statistics.median(samples),
                            "selection_p95_ms": _p95(samples), "selection_samples_ms": samples}
        return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=int, default=4096)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--root", help="measure a bounded sample of text files from this repository")
    parser.add_argument("--query", default="ProjectPreprocessor", help="demand query in repository mode")
    args = parser.parse_args()
    print(json.dumps(run(args.files, args.batch_size, root=args.root, query=args.query), indent=2))


if __name__ == "__main__":
    main()

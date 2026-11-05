"""Measure synthetic file-card scheduling with an existing learned query.

Only queue selection and simulated completion are measured; no model inference runs.
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
from local_ai_hub.repo_tools import RepositoryTools


class _Learner:
    def __init__(self, enabled: bool):
        self.enabled = enabled

    def hot_queries(self, root, limit):
        return ["rare_demand"]


def run(files: int = 4096, batch_size: int = 64) -> dict:
    if files < 2 or batch_size < 2:
        raise ValueError("files and batch_size must be at least two")
    with tempfile.TemporaryDirectory(prefix="hub-demand-benchmark-") as directory:
        root = str(Path(directory) / "repo")
        db = Path(directory) / "fixture.sqlite"
        with closing(sqlite3.connect(db)) as con:
            con.execute("CREATE TABLE file_refs(root TEXT, path TEXT, size INTEGER, card_key TEXT, last_accessed_at REAL, PRIMARY KEY(root,path))")
            con.execute("CREATE VIRTUAL TABLE source_fts USING fts5(root UNINDEXED,path UNINDEXED,content)")
            rows = [(root, f"file_{i:06}.py", 10, None, 0) for i in range(files)]
            con.executemany("INSERT INTO file_refs VALUES(?,?,?,?,?)", rows)
            con.executemany("INSERT INTO source_fts VALUES(?,?,?)", ((root, row[1], "rare_demand" if i == files - 1 else "ordinary") for i, row in enumerate(rows)))
            con.commit()

        def connect():
            con = sqlite3.connect(db)
            con.row_factory = sqlite3.Row
            return con

        pre = ProjectPreprocessor.__new__(ProjectPreprocessor)
        pre._connect, pre._db_lock = connect, threading.RLock()
        pre._demand_priority_cache, pre._demand_priority_lock = {}, threading.Lock()
        pre.cfg, pre.repo_tools = {}, RepositoryTools({})
        hot = f"file_{files - 1:06}.py"
        output = {"scope": "synthetic file-card queue selection, no model inference", "files": files, "batch_size": batch_size}
        for name, enabled in (("baseline", False), ("demand", True)):
            with closing(connect()) as con:
                con.execute("UPDATE file_refs SET card_key=NULL")
                con.commit()
            pre.learner = _Learner(enabled)
            samples = []
            batches = 0
            batches_to_hot = None
            regular_first = 0
            completed = set()
            while True:
                start = time.perf_counter()
                selected = [str(row["path"]) for row in pre._find_next_files(root, batch_size)]
                samples.append((time.perf_counter() - start) * 1000)
                if not selected:
                    break
                batches += 1
                if batches == 1:
                    regular_first = sum(path != hot for path in selected)
                if hot in selected:
                    batches_to_hot = batches
                completed.update(selected)
                with closing(connect()) as con:
                    con.executemany("UPDATE file_refs SET card_key='done' WHERE root=? AND path=?", ((root, path) for path in selected))
                    con.commit()
            if hot not in completed:
                raise RuntimeError("hot file was never selected")
            output[name] = {"batches_to_hot": batches_to_hot, "batches_to_complete": batches,
                            "completed_files": len(completed), "unprocessed_files": files - len(completed),
                            "regular_files_in_first_batch": regular_first,
                            "selection_median_ms": statistics.median(samples), "selection_samples_ms": samples}
        return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=int, default=4096)
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()
    print(json.dumps(run(args.files, args.batch_size), indent=2))


if __name__ == "__main__":
    main()

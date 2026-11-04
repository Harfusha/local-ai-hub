"""Measure labeled symbol lookups on this repository with an isolated service.

Labels specify one verified relevant path, not an exhaustive relevance set.
HTTP/MCP transport, caching and optional backends are disabled.
"""
from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path

from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.cache import MemoryLRUCache, SingleFlightCache
from local_ai_hub.repo_state import RepoStateTracker
from local_ai_hub.services import LocalAIServices


CASES = [
    {"query": "_exact_" "search_page", "path": "src/local_ai_hub/repo_tools.py", "source_text": "def _exact_" "search_page"},
    {"query": "_step_" "rag", "path": "src/local_ai_hub/preprocess.py", "source_text": "def _step_" "rag"},
    {"query": "pagination_" "bounds_error", "path": "src/local_ai_hub/search_pagination.py", "source_text": "def pagination_" "bounds_error"},
    {"query": "repo_" "search", "path": "src/local_ai_hub/services.py", "source_text": "def repo_" "search"},
]


def validate_cases(root: Path, cases: list[dict]) -> None:
    base = root.resolve(strict=True)
    for case in cases:
        relative = Path(case["path"])
        path = (base / relative).resolve(strict=False)
        if relative.is_absolute() or not path.is_relative_to(base):
            raise ValueError("case path escapes repository")
        if case["source_text"] not in path.read_text(encoding="utf-8"):
            raise ValueError(f"case source_text absent from {relative}")


def run(root: Path, repeats: int, use_cache: bool = False) -> dict:
    if repeats < 1:
        raise ValueError("repeats must be positive")
    root = root.resolve(strict=True)
    validate_cases(root, CASES)
    with tempfile.TemporaryDirectory(prefix="hub-real-search-state-") as directory:
        service = LocalAIServices.__new__(LocalAIServices)
        service.config = {"server": {"state_dir": directory}}
        service.repo_tools = RepositoryTools({})
        service.learner = service.deterministic = service.code_index = service.preprocessor = service.evidence_store = None
        if use_cache:
            service.repo_state = RepoStateTracker(service.config)
            service.repo_flight = SingleFlightCache(MemoryLRUCache())
        else:
            service._repo_cache_state = lambda _root: {}
            service._repo_cached = lambda _name, _root, _params, compute: compute()
        rows = []
        for case in CASES:
            durations = []
            cache_hits = []
            for _ in range(repeats):
                start = time.perf_counter()
                result = service.repo_search(str(root), case["query"], limit=10)
                durations.append((time.perf_counter() - start) * 1000)
                cache_hits.append(result.get("cache_hit"))
                if not result.get("success"):
                    raise RuntimeError(f"search failed: {result.get('error')}")
            paths = list(dict.fromkeys(item["path"] for item in result["results"]))
            rank = next((i for i, path in enumerate(paths, 1) if path == case["path"]), None)
            rows.append({"query": case["query"], "expected_path": case["path"], "rank": rank,
                         "paths": paths, "median_ms": statistics.median(durations), "samples_ms": durations,
                         "cache_hits": cache_hits})
        return {"scope": "real repository; isolated LocalAIServices.repo_search; optional backends disabled; labels are not exhaustive",
                "cache_enabled": use_cache,
                "root": str(root), "repeats": repeats, "cases": rows,
                "hit_rate_at_10": sum(row["rank"] is not None for row in rows) / len(rows),
                "mean_reciprocal_rank": statistics.mean(1 / row["rank"] if row["rank"] else 0 for row in rows)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--cache", action="store_true", help="measure cold then warm service cache with real repository fingerprinting")
    args = parser.parse_args()
    print(json.dumps(run(args.root, args.repeats, args.cache), indent=2))


if __name__ == "__main__":
    main()

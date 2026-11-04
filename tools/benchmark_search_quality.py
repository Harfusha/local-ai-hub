"""Repeatable labeled synthetic benchmark for the exact repository-search engine.

This measures an isolated service or engine, not HTTP/MCP transport or preprocessing.
Run: python tools/benchmark_search_quality.py --repeats 5 --noise-files 100
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import tempfile
import time
from pathlib import Path

from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.services import LocalAIServices


def make_fixture(root: Path, noise_files: int = 100) -> list[dict]:
    files = {
        "src/session.py": 'def restore_session_token():\n    """restore session token after reconnect"""\n    return "session token"\n',
        "src/token_cache.py": 'def cache_token():\n    return "token cache"\n',
        "src/payment.py": 'def charge_invoice():\n    return "payment invoice"\n',
        "src/literal.py": '# C++ binding\nSETTING = "foo.bar"\nWORD = "the"\n',
        "src/similar.py": 'SETTING = "fooXbar"\n',
        "src/a_retry_noise.py": '# retry retry retry\n',
        "src/z_transaction.py": 'def retry():\n    # transaction\n    pass\n',
        "docs/notes.md": '# Session notes\nThe cache holds a token.\n',
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    for index in range(noise_files):
        path = root / "noise" / f"file_{index:05d}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'# unrelated document {index}\nvalue = {index}\n', encoding="utf-8")
    return [
        {"query": "restore_session_token", "relevant": ["src/session.py"], "literal": "restore_session_token"},
        {"query": "restore session token", "relevant": ["src/session.py"], "literal": "restore session token"},
        {"query": "payment invoice", "relevant": ["src/payment.py"], "literal": "payment invoice"},
        {"query": "foo.bar", "relevant": ["src/literal.py"], "literal": "foo.bar"},
        {"query": "C++", "relevant": ["src/literal.py"], "literal": "C++"},
        {"query": "the", "relevant": ["src/literal.py", "docs/notes.md"], "literal": "the"},
        {"query": "retry transaction", "relevant": ["src/z_transaction.py"], "literal": ""},
        {"query": "nonexistent_unique_needle", "relevant": [], "literal": ""},
    ]


def make_holdout_fixture(root: Path, noise_files: int = 100) -> list[dict]:
    """Manually judged cases not used to tune the development queries."""
    files = {
        "src/access.py": 'def renew_access_key():\n    """renew access key"""\n',
        "src/noise.py": '# access access access\n# retry retry retry\n',
        "src/db.py": 'def retry():\n    # sqlite transaction\n    pass\n',
        "src/bridge.cs": '// C# bridge\nclass Bridge {}\n',
        "src/component.py": '# widget::render\nFLAG = "namespace.name"\n',
        "src/similar.py": 'FLAG = "namespaceXname"\n',
        "docs/guide.md": '# Guide\nwhile running, stop safely\n',
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    for index in range(noise_files):
        path = root / "noise" / f"item_{index:05d}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# unrelated {index}\nvalue = {index}\n", encoding="utf-8")
    return [
        {"query": "renew access key", "relevant": ["src/access.py"], "literal": "renew access key"},
        {"query": "retry sqlite", "relevant": ["src/db.py"], "literal": ""},
        {"query": "C#", "relevant": ["src/bridge.cs"], "literal": "C#"},
        {"query": "widget::render", "relevant": ["src/component.py"], "literal": "widget::render"},
        {"query": "namespace.name", "relevant": ["src/component.py"], "literal": "namespace.name"},
        {"query": "while", "relevant": ["docs/guide.md"], "literal": "while"},
        {"query": "missing_quantum_driver", "relevant": [], "literal": ""},
    ]


def evaluate(paths: list[str], relevant: list[str]) -> dict:
    ranked = list(dict.fromkeys(paths))
    expected = set(relevant)
    found = expected.intersection(ranked)
    return {
        "recall_at_k": len(found) / len(expected) if expected else None,
        "precision_at_k": len(found) / len(ranked) if ranked else (1.0 if not expected else 0.0),
        "reciprocal_rank": next((1.0 / i for i, path in enumerate(ranked, 1) if path in expected), 0.0) if expected else None,
        "negative_correct": not ranked if not expected else None,
    }


def run(repeats: int, noise_files: int, mode: str = "service", suite: str = "development") -> dict:
    if repeats < 1 or noise_files < 0:
        raise ValueError("repeats must be positive and noise_files nonnegative")
    if mode not in {"service", "engine"}:
        raise ValueError("mode must be service or engine")
    if suite not in {"development", "holdout"}:
        raise ValueError("suite must be development or holdout")
    with tempfile.TemporaryDirectory(prefix="hub-search-benchmark-") as directory:
        root = Path(directory) / "repo"
        root.mkdir()
        cases = (make_fixture if suite == "development" else make_holdout_fixture)(root, noise_files)
        tools = RepositoryTools({"rag": {"extensions": [".py", ".md", ".cs"]}})
        service = LocalAIServices.__new__(LocalAIServices)
        service.config = {"server": {"state_dir": str(Path(directory) / "state")}}
        service.repo_tools = tools
        service.learner = service.deterministic = service.code_index = service.preprocessor = service.evidence_store = None
        service._repo_cache_state = lambda _root: {}
        service._repo_cached = lambda _name, _root, _params, compute: compute()
        rows = []
        for case in cases:
            durations = []
            for _ in range(repeats):
                start = time.perf_counter()
                if mode == "service":
                    result = service.repo_search(str(root), case["query"], limit=10)
                else:
                    result = tools.search(str(root), case["query"], limit=10, exact_count=True)
                durations.append((time.perf_counter() - start) * 1000)
                if not result.get("success"):
                    raise RuntimeError(f"search failed for {case['query']!r}: {result.get('error')}")
            ordered = sorted(durations)
            paths = [item["path"] for item in result["results"]]
            rows.append({"query": case["query"], "expected": case["relevant"], "paths": paths,
                         **evaluate(paths, case["relevant"]), "total_matches": result["total_matches"],
                         "latency_ms": {"samples": durations, "median": statistics.median(durations),
                                        "p95": ordered[math.ceil(0.95 * len(ordered)) - 1]}})
        positives = [row for row in rows if row["recall_at_k"] is not None]
        scope = ("synthetic LocalAIServices.repo_search with cache and optional backends disabled"
                 if mode == "service" else "synthetic RepositoryTools.search exact_count")
        return {"scope": scope + "; no HTTP/MCP transport or preprocessing", "suite": suite,
                "noise_files": noise_files, "repeats": repeats, "ripgrep_available": bool(tools._rg),
                "mean_recall_at_10": statistics.mean(row["recall_at_k"] for row in positives),
                "mean_reciprocal_rank": statistics.mean(row["reciprocal_rank"] for row in positives),
                "cases": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--noise-files", type=int, default=100)
    parser.add_argument("--mode", choices=("service", "engine"), default="service")
    parser.add_argument("--suite", choices=("development", "holdout"), default="development")
    args = parser.parse_args()
    print(json.dumps(run(args.repeats, args.noise_files, args.mode, args.suite), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

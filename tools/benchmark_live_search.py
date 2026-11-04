"""Measure the configured loopback Hub with a manually labeled query set.

Run `python tools/benchmark_live_search.py --modes lexical rag hybrid --repeats 2`.
This sends bounded read-only search requests; it does not change Hub configuration.
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from local_ai_hub.config import load_config


ROOT = Path(__file__).resolve().parents[1]
CASE_FILE = ROOT / "tests" / "fixtures" / "search_benchmark_cases.json"
SEARCH_MODES = ("lexical", "rag", "hybrid")


def load_cases() -> list[dict[str, Any]]:
    data = json.loads(CASE_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("unsupported search benchmark case schema")
    cases = data.get("cases")
    if not isinstance(cases, list):
        raise ValueError("benchmark cases must be a list")
    for case in cases:
        if isinstance(case, dict) and "query_b64" in case:
            encoded = case.pop("query_b64")
            if type(encoded) is not str:
                raise ValueError("query_b64 must be a string")
            try:
                case["query"] = base64.b64decode(encoded, validate=True).decode("utf-8")
            except (ValueError, UnicodeError) as exc:
                raise ValueError("query_b64 must encode UTF-8 text") from exc
    return cases


def validate_cases(root: Path, cases: list[dict[str, Any]]) -> None:
    base = root.resolve(strict=True)
    seen_ids: set[str] = set()
    for case in cases:
        case_id = case.get("id")
        query = case.get("query")
        expected = case.get("expected_paths")
        evidence = case.get("evidence")
        if type(case_id) is not str or not case_id or case_id in seen_ids:
            raise ValueError("case ids must be unique non-empty strings")
        seen_ids.add(case_id)
        if type(query) is not str or not query.strip():
            raise ValueError(f"{case_id}: query must be non-empty")
        if not isinstance(expected, list) or any(type(path) is not str for path in expected):
            raise ValueError(f"{case_id}: expected_paths must be a list of paths")
        if case.get("negative") is True and expected:
            raise ValueError(f"{case_id}: negative case cannot have expected paths")
        if case.get("negative") is not True and not expected:
            raise ValueError(f"{case_id}: positive case needs at least one expected path")
        if not isinstance(evidence, list):
            raise ValueError(f"{case_id}: evidence must be a list")
        for item in evidence:
            if not isinstance(item, dict) or type(item.get("path")) is not str:
                raise ValueError(f"{case_id}: evidence path is required")
            relative = Path(item["path"])
            target = (base / relative).resolve(strict=True)
            try:
                target.relative_to(base)
            except ValueError as exc:
                raise ValueError(f"{case_id}: evidence path escapes root") from exc
            if not target.is_file():
                raise ValueError(f"{case_id}: evidence path is not a file")
            anchor = item.get("anchor")
            if type(anchor) is not str or not anchor or anchor not in target.read_text(encoding="utf-8", errors="replace"):
                raise ValueError(f"{case_id}: source anchor missing from {item['path']}")
        for relative in expected:
            path = Path(relative)
            target = (base / path).resolve(strict=True)
            try:
                target.relative_to(base)
            except ValueError as exc:
                raise ValueError(f"{case_id}: expected path escapes root") from exc
            if not target.is_file():
                raise ValueError(f"{case_id}: expected path missing: {relative}")


def evaluate_case(results: list[dict[str, Any]], case: dict[str, Any]) -> dict[str, Any]:
    ranked: list[str] = []
    for item in results:
        path = item.get("path") if isinstance(item, dict) else None
        if type(path) is str and path not in ranked:
            ranked.append(path)
    expected = set(case["expected_paths"])
    if not expected:
        return {
            "recall_at_k": None,
            "precision_at_k": None,
            "reciprocal_rank": None,
            "ndcg_at_k": None,
            "negative_correct": not ranked,
        }
    found = expected.intersection(ranked)
    first = next((rank for rank, path in enumerate(ranked, 1) if path in expected), None)
    dcg = sum(1.0 / math.log2(rank + 1) for rank, path in enumerate(ranked, 1) if path in expected)
    ideal = min(len(expected), len(ranked))
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal + 1))
    return {
        "recall_at_k": len(found) / len(expected),
        "precision_at_k": len(found) / len(ranked) if ranked else 0.0,
        "reciprocal_rank": 1.0 / first if first else 0.0,
        "ndcg_at_k": dcg / idcg if idcg else 0.0,
        "negative_correct": None,
    }


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def _request(url: str, payload: dict[str, Any], token: str, timeout: float) -> tuple[int, dict[str, Any]]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(4 * 1024 * 1024 + 1)
            if len(body) > 4 * 1024 * 1024:
                return response.status, {"success": False, "error": "response_too_large"}
            return response.status, json.loads(body or b"{}")
    except urllib.error.HTTPError as exc:
        body = exc.read(64 * 1024)
        try:
            return exc.code, json.loads(body or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return exc.code, {"success": False, "error": "invalid_http_error_body"}


def run(
    *,
    root: Path = ROOT,
    modes: tuple[str, ...] = SEARCH_MODES,
    repeats: int = 2,
    timeout_seconds: float = 30.0,
    cases: list[dict[str, Any]] | None = None,
    progress: bool = False,
) -> dict[str, Any]:
    if type(repeats) is not int or not 1 <= repeats <= 20:
        raise ValueError("repeats must be between 1 and 20")
    if type(timeout_seconds) not in {int, float} or not 1 <= timeout_seconds <= 60:
        raise ValueError("timeout_seconds must be between 1 and 60")
    if not modes or any(mode not in SEARCH_MODES for mode in modes) or len(set(modes)) != len(modes):
        raise ValueError("modes must be a unique non-empty subset of lexical, rag, hybrid")
    root = root.resolve(strict=True)
    cases = load_cases() if cases is None else cases
    validate_cases(root, cases)
    config = load_config(probe_hardware=False)
    server = config.get("server", {})
    bind = str(server.get("bind", "127.0.0.1"))
    host = "127.0.0.1" if bind in {"0.0.0.0", "::", ""} else bind
    port = int(server.get("port", 11435))
    token = str(config.get("security", {}).get("api_token", ""))
    url = f"http://{host}:{port}/api/search"
    rows: list[dict[str, Any]] = []
    for mode in modes:
        for case in cases:
            samples: list[dict[str, Any]] = []
            last_result: dict[str, Any] = {}
            last_status: int | None = None
            for repeat in range(repeats):
                payload = {
                    "root": str(root), "query": case["query"], "search_mode": mode,
                    "limit": 10, "offset": 0,
                }
                started = time.perf_counter()
                try:
                    status, response = _request(url, payload, token, float(timeout_seconds))
                    error = None
                except (OSError, TimeoutError, urllib.error.URLError) as exc:
                    status, response, error = None, {}, type(exc).__name__
                elapsed = (time.perf_counter() - started) * 1000
                last_status, last_result = status, response
                samples.append({
                    "latency_ms": round(elapsed, 3),
                    "cache_hit": response.get("cache_hit") if isinstance(response, dict) else None,
                    "http_status": status,
                    "success": response.get("success") is True if isinstance(response, dict) else False,
                    "error": error,
                })
                if progress:
                    outcome = f"HTTP {status}" if status is not None else f"error={error}"
                    cache_hit = response.get("cache_hit") if isinstance(response, dict) else None
                    print(
                        f"{mode} {case['id']} {repeat + 1}/{repeats} {outcome} "
                        f"{elapsed:.0f}ms cache_hit={cache_hit}",
                        file=sys.stderr,
                        flush=True,
                    )
                if error:
                    break
            result_rows = last_result.get("results", []) if isinstance(last_result, dict) else []
            success = last_result.get("success") is True if isinstance(last_result, dict) else False
            scored = evaluate_case(result_rows, case) if success and isinstance(result_rows, list) else None
            times = [float(item["latency_ms"]) for item in samples]
            rows.append({
                "case_id": case["id"], "query": case["query"], "language": case["language"],
                "search_mode": mode, "expected_paths": case["expected_paths"],
                "paths": [item.get("path") for item in result_rows if isinstance(item, dict)],
                "quality": scored,
                "http_status": last_status,
                "success": success,
                "result_source": last_result.get("result_source"),
                "lexical_candidate_source": last_result.get("lexical_candidate_source"),
                "lexical_preprocessed_candidate_count": last_result.get("lexical_preprocessed_candidate_count"),
                "rag_search_skipped": last_result.get("rag_search_skipped"),
                "rag_skip_reason": last_result.get("rag_skip_reason"),
                "count_exact": last_result.get("count_exact"),
                "total_matches": last_result.get("total_matches"),
                "candidate_count": last_result.get("candidate_count"),
                "query_expansion_applied": last_result.get("query_expansion_applied"),
                "coverage_complete": last_result.get("coverage_complete"),
                "index_state": last_result.get("index_state"),
                "index_coverage": last_result.get("index_coverage"),
                "stale_candidate_count": last_result.get("stale_candidate_count"),
                "stale_candidate_reasons": last_result.get("stale_candidate_reasons"),
                "stale_candidate_details": last_result.get("stale_candidate_details"),
                "degraded": last_result.get("degraded"),
                "degradation_reason": last_result.get("degradation_reason"),
                "reranker": last_result.get("reranker"),
                "samples": samples,
                "median_ms": statistics.median(times) if times else None,
                "p95_ms": _percentile(times, 0.95),
                "cold_ms": [item["latency_ms"] for item in samples if item["cache_hit"] is False],
                "warm_ms": [item["latency_ms"] for item in samples if item["cache_hit"] is True],
            })
    return {
        "scope": "configured installed loopback Hub HTTP /api/search; real repository; no configuration mutation",
        "root": str(root), "base_url": f"http://{host}:{port}",
        "hardware_profile": config.get("hardware", {}).get("profile"),
        "reranker_configured": config.get("features", {}).get("reranker"),
        "reranker_model": config.get("models", {}).get("reranker"),
        "model_downloads": False,
        "modes": list(modes), "repeats": repeats,
        "timeout_seconds": timeout_seconds, "cases": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--modes", nargs="+", choices=SEARCH_MODES, default=list(SEARCH_MODES))
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--case", action="append", dest="case_ids")
    args = parser.parse_args()
    cases = load_cases()
    if args.case_ids:
        selected = set(args.case_ids)
        cases = [case for case in cases if case["id"] in selected]
        if len(cases) != len(selected):
            parser.error("unknown case id")
    print(json.dumps(run(root=args.root, modes=tuple(args.modes), repeats=args.repeats,
                         timeout_seconds=args.timeout_seconds, cases=cases, progress=True),
          ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

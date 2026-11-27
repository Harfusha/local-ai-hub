"""Synthetic or historical Git-context transport estimates; no cloud calls."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from local_ai_hub.change_plan_delta import change_delta, remember_baseline  # noqa: E402
from local_ai_hub.change_plan_projection import project_change_plan  # noqa: E402
from local_ai_hub.split_changes import run_split_changes  # noqa: E402
from local_ai_hub.token_accounting import tool_request_tokens, tool_response_tokens  # noqa: E402
from local_ai_hub.process_utils import clean_git_env, run_hidden  # noqa: E402


class _Cache:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def get(self, key: str) -> Any:
        return self.data.get(key)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value


def measure(root: Path, *, files: int = 12, lines: int = 120) -> dict[str, Any]:
    if not 2 <= files <= 16 or not 10 <= lines <= 250:
        raise ValueError("Fixture bounds: files 2–16, lines 10–250")
    cache = _Cache()
    engine = SimpleNamespace(_root=lambda value: value, git_status_timeout=10, _change_summary_cache=cache)
    hooks = root / ".git" / "hub-bench-no-hooks"

    def git(*args: str) -> bytes:
        return subprocess.check_output(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                                        "-c", "commit.gpgsign=false", "-c", f"core.hooksPath={hooks}", *args],
                                       cwd=root, stderr=subprocess.DEVNULL)

    def plan() -> dict[str, Any]:
        result = run_split_changes(engine, str(root), None, path_type=Path,
                                   subprocess_module=subprocess, hidden_run_kwargs_fn=lambda: {})
        if result.get("success") is not True or result.get("git_visible_observation_complete") is not True:
            raise RuntimeError("Incomplete fixture observation")
        return result

    def write_file(index: int, version: int) -> None:
        # Multiple changed lines in distinct components model a broad edit.
        path = root / f"component_{index:02d}.txt"
        path.write_text("".join(f"component {index:02d} line {line:03d}: value {version:02d} synthetic payload\n"
                                for line in range(lines)), encoding="utf-8")

    git("init")
    hooks.mkdir()
    for index in range(files):
        write_file(index, 0)
    git("add", "--", ".")
    git("commit", "-m", "fixture")
    for index in range(files):
        write_file(index, 1)
    first = plan()
    if not remember_baseline(first, cache):
        raise RuntimeError("Fixture baseline unavailable")
    previous = first["observed_change_set_id"]

    def raw_cost() -> int:
        diff = git("diff", "--no-ext-diff", "--no-textconv", "--no-color", "--").decode("utf-8")
        return tool_request_tokens("git_diff", {"root": str(root)}) + tool_response_tokens({"diff": diff})

    def page_cost(result: dict[str, Any]) -> int:
        total = 0
        for offset in range(0, max(1, result["cluster_count"]), 8):
            page = project_change_plan(result, limit=8, offset=offset)
            total += tool_request_tokens("local_ai_repo", {"action": "split_changes", "root": str(root),
                                                          "mode": "summary", "limit": 8, "offset": offset})
            total += tool_response_tokens(page)
        return total

    initial_raw = raw_cost()
    initial_compact = page_cost(first)
    write_file(0, 2)
    second = plan()
    second_raw = raw_cost()
    delta = change_delta(second, cache, previous, limit=8, offset=0)
    if delta.get("success") is not True or delta.get("has_more"):
        raise RuntimeError("Fixture delta unavailable")
    delta_cost = tool_request_tokens("local_ai_repo", {"action": "split_changes", "root": str(root),
                                                       "mode": "delta", "expected_revision": previous})
    delta_cost += tool_response_tokens(delta)
    # Include one explicit raw targeted inspection in the compact scenario;
    # actual review may require every changed path and cannot be assumed away.
    targeted = git("diff", "--no-ext-diff", "--no-textconv", "--no-color", "--", "component_00.txt").decode("utf-8")
    targeted_cost = tool_request_tokens("git_diff", {"root": str(root), "path": "component_00.txt"})
    targeted_cost += tool_response_tokens({"diff": targeted})
    raw_total = initial_raw + second_raw
    compact_total = initial_compact + delta_cost + targeted_cost
    return {
        "fixture": {"files": files, "lines_per_file": lines},
        "estimated_tokens": {"raw_initial": initial_raw, "raw_repeat": second_raw, "compact_initial": initial_compact,
                             "delta_repeat": delta_cost, "targeted_raw_followup": targeted_cost,
                             "raw_total": raw_total, "compact_scenario_total": compact_total},
        "estimated_net_difference": raw_total - compact_total,
        "changed_groups": delta["changed_group_count"],
        "unchanged_content_groups": delta["unchanged_content_group_count"],
        "method": "Hub compact JSON byte-based token estimator, request and response payloads included",
        "limitations": "Synthetic transport estimate only; no provider tokenizer, protocol envelopes, task accuracy, inference cost, actual billed tokens or review completeness measured.",
    }


def measure_history(root: Path, base: str, head: str) -> dict[str, Any]:
    """Measure a real committed range without modifying a worktree or invoking a model."""
    root = root.resolve(strict=True)
    engine = SimpleNamespace(_root=lambda value: value, git_status_timeout=20, _change_summary_cache=_Cache())
    result = run_split_changes(engine, str(root), None, path_type=Path,
                               subprocess_module=subprocess, hidden_run_kwargs_fn=lambda: {}, base=base, head=head)
    if result.get("success") is not True:
        raise ValueError("Cannot observe requested committed range")
    comparison = result["comparison"]
    revisions = [comparison["base"], comparison["head"]]

    def git(*args: str) -> bytes:
        cp = run_hidden(["git", "--no-pager", "-c", "core.fsmonitor=false", *args], cwd=str(root),
                        env=clean_git_env(extra_env={"GIT_OPTIONAL_LOCKS": "0", "GIT_NO_REPLACE_OBJECTS": "1",
                                                     "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0"}),
                        stdin=subprocess.DEVNULL, capture_output=True, check=False,
                        timeout=20, max_output_bytes=4 * 1024 * 1024)
        if cp.returncode or getattr(cp, "stdout_truncated", False) or getattr(cp, "stderr_truncated", False):
            raise ValueError("Historical Git comparison exceeded bounds or failed")
        return cp.stdout

    flags = ("diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--ignore-submodules=none")
    raw = git(*flags, "--binary", "--full-index", "--no-color", *revisions, "--")
    raw_paths = git(*flags, "--name-only", "-z", *revisions, "--")
    expected = {os.fsdecode(path) for path in raw_paths.split(b"\0") if path}
    observed = {path for group in result["clusters"] for path in group["files"]}
    if observed != expected:
        raise ValueError("Historical plan inventory disagrees with independent Git path inventory")
    if len(result["clusters"]) > 256:
        raise ValueError("Historical group count exceeds benchmark budget")
    raw_cost = tool_request_tokens("git_diff", {"root": str(root), "rev1": revisions[0], "rev2": revisions[1]})
    raw_cost += tool_response_tokens({"diff": raw.decode("utf-8", errors="replace")})
    compact_cost = 0
    visible_paths = set()
    omitted_paths = 0
    for offset in range(0, max(1, result["cluster_count"]), 8):
        page = project_change_plan(result, mode="summary", limit=8, offset=offset)
        compact_cost += tool_request_tokens("local_ai_repo", {
            "action": "split_changes", "root": str(root), "mode": "summary",
            "base": revisions[0], "head": revisions[1], "limit": 8, "offset": offset,
        }) + tool_response_tokens(page)
        for group in page["clusters"]:
            visible_paths.update(group["files"])
            omitted_paths += group["files_omitted"]
    if not visible_paths <= expected or len(visible_paths) + omitted_paths != len(expected):
        raise ValueError("Historical page projection misreports path coverage")
    return {
        "workload": "real_committed_range", "comparison": comparison,
        "estimated_tokens": {"raw": raw_cost, "compact_all_pages": compact_cost},
        "estimated_net_difference": raw_cost - compact_cost,
        "inventory": {"changed_paths": len(expected), "observed_paths": len(observed),
                      "explicitly_listed_paths": len(visible_paths), "omitted_paths": omitted_paths,
                      "patch_coverage_complete": result["patch_coverage_complete"],
                      "semantic_observed_scopes": sum(g["semantic_observed_scopes"] for g in result["clusters"])},
        "method": "Hub JSON transport estimator on actual committed patches and paginated metadata",
        "limitations": "No cloud calls, billing, model accuracy or review completeness measured; omitted paths require additional inspection.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=int, default=12)
    parser.add_argument("--lines", type=int, default=120)
    parser.add_argument("--repo", type=Path, help="Existing repository for read-only historical comparison")
    parser.add_argument("--base", help="Base commit for historical benchmark")
    parser.add_argument("--head", default="HEAD", help="Head commit for historical benchmark")
    args = parser.parse_args()
    if args.repo is not None or args.base is not None:
        if args.repo is None or not args.base:
            parser.error("--repo and --base must be supplied together")
        print(json.dumps(measure_history(args.repo, args.base, args.head), indent=2))
        return 0
    with tempfile.TemporaryDirectory(prefix="hub-change-benchmark-") as tmp:
        print(json.dumps(measure(Path(tmp).resolve(), files=args.files, lines=args.lines), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

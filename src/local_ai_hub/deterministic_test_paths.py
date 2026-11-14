"""Deterministic helpers for test-path and test-matrix policy."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import re
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TypeVar

_WorkerInput = TypeVar("_WorkerInput")
_WorkerOutput = TypeVar("_WorkerOutput")


def is_test_file(rel_path: str) -> bool:
    norm = rel_path.replace("\\", "/").lower()
    parts = norm.split("/")
    test_dirs = {"test", "tests", "fixtures", "fixture", "mock", "mocks", "__tests__", "spec", "specs"}
    if any(p in test_dirs for p in parts[:-1]):
        return True
    fname = parts[-1]
    if fname.startswith(("test_", "mock_")):
        return True
    test_suffixes = (
        "_test.py", "_test.go", "_test.js", "_test.ts",
        ".test.js", ".test.ts", ".test.tsx", ".test.jsx",
        ".spec.js", ".spec.ts", ".spec.tsx", ".spec.jsx",
        "test.php", "spec.php", "_test.php", ".test.php", ".spec.php",
        ".test.mjs", ".spec.mjs", ".test.cjs", ".spec.cjs",
    )
    return any(fname.endswith(s) for s in test_suffixes)


def is_test_matrix_source(rel_path: str) -> bool:
    """Recognize test-matrix source names without inspecting repository state."""
    normalized = rel_path.replace("\\", "/").lower()
    suffix = Path(normalized).suffix
    if suffix not in {".py", ".go", ".cs", ".ts", ".tsx", ".js", ".jsx", ".java", ".rs", ".cpp", ".cc", ".c", ".php"}:
        return False
    name = Path(normalized).name
    original_name = Path(rel_path.replace("\\", "/")).name
    if name == "pest.php":
        return False
    php_test_name = (
        name == "test.php" or name.endswith("_test.php") or original_name.endswith("Test.php")
    )
    return (
        name.startswith("test_") or name.startswith("tests_")
        or name.endswith((
            "_test.py", "_test.go", ".spec.ts", ".spec.js", ".spec.tsx", ".spec.jsx",
            ".test.ts", ".test.js", ".test.tsx", ".test.jsx",
        ))
        or php_test_name
        or any(part in {"test", "tests", "spec", "specs"} for part in Path(normalized).parts)
    )


def extract_test_case_names(
    content: str,
    suffix: str,
    *,
    should_continue: Callable[[], bool] | None = None,
) -> tuple[list[str], bool]:
    """Extract the test names currently supported by the deterministic matrix."""
    cases: list[str] = []
    scan_complete = suffix in {".py", ".cs"}
    can_continue = should_continue or (lambda: True)

    if suffix == ".py":
        for line in content.splitlines():
            if not can_continue():
                scan_complete = False
                break
            stripped = line.strip()
            if stripped.startswith("def test_"):
                cases.append(stripped.split("(")[0].replace("def ", "").strip())
                if len(cases) > 15:
                    scan_complete = False
                    break
    elif suffix == ".cs":
        attribute_pending = 0
        for line in content.splitlines():
            if not can_continue():
                scan_complete = False
                break
            if re.search(r"\[(?:Test|UnityTest|Fact)\b", line):
                attribute_pending = 20
            if attribute_pending and (method := re.search(r"\bvoid\s+([A-Za-z0-9_]+)", line)):
                cases.append(method.group(1))
                attribute_pending = 0
                if len(cases) > 15:
                    scan_complete = False
                    break
            elif attribute_pending:
                attribute_pending -= 1

    return cases, scan_complete


def build_test_file_result(
    rel_path: str,
    content_sha256: str,
    cases: list[str],
    cases_scan_complete: bool,
    suffix: str,
    run_argv: list[str],
    run_command: str,
) -> dict[str, object]:
    """Build the public test-matrix row from already validated file facts."""
    return {
        "path": rel_path,
        "cases_count": len(cases),
        "cases": cases[:15],
        "run_command": run_command,
        "run_argv": run_argv,
        "content_sha256": content_sha256,
        "cases_truncated": len(cases) > 15,
        "cases_scan_complete": cases_scan_complete,
        "case_detection": {
            ".py": "python_test_function_name_heuristic",
            ".cs": "csharp_test_attribute_method_heuristic",
        }.get(suffix, "not_implemented_for_language"),
    }


def select_test_matrix_targets(
    target_paths: list[tuple[str, Path, object]],
    *,
    max_targets: int,
    max_total_bytes: int,
) -> tuple[list[tuple[str, Path, object]], bool, list[str]]:
    """Apply deterministic count and aggregate-read budgets to validated targets."""
    warnings: list[str] = []
    incomplete = False
    ordered = sorted(target_paths, key=lambda item: item[0])
    if len(ordered) > max_targets:
        incomplete = True
        warnings.append("test_file_result_limit_reached")
        ordered = ordered[:max_targets]

    selected: list[tuple[str, Path, object]] = []
    remaining_bytes = max_total_bytes
    for item in ordered:
        reservation = int(getattr(item[2], "st_size")) + 1
        if reservation > remaining_bytes:
            incomplete = True
            warnings.append("test_file_total_byte_limit_reached")
            break
        remaining_bytes -= reservation
        selected.append(item)
    return selected, incomplete, warnings


def collect_test_matrix_rows(
    rows: Iterable[dict[str, object] | None],
) -> tuple[list[dict[str, object]], bool, list[str]]:
    """Collect bounded worker rows and preserve every incomplete-result signal."""
    collected: list[dict[str, object]] = []
    warnings: list[str] = []
    incomplete = False
    for row in rows:
        if row is None or "_omitted" in row:
            incomplete = True
            warnings.append("test_file_read_failed")
            continue
        if row.get("cases_truncated"):
            incomplete = True
            warnings.append("test_case_result_limit_reached")
        if not row.get("cases_scan_complete", True):
            incomplete = True
            warnings.append("test_case_scan_incomplete")
        collected.append(row)
    return collected, incomplete, warnings


def run_test_matrix_workers(
    worker: Callable[[_WorkerInput], _WorkerOutput],
    items: list[_WorkerInput],
    *,
    max_workers: int = 8,
) -> list[_WorkerOutput]:
    """Run per-file matrix workers with a bounded pool and input-order results."""
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=min(max_workers, len(items))) as pool:
        return list(pool.map(worker, items))


def build_test_matrix_response(
    framework: str | None,
    run_all_command: str | None,
    test_files: list[dict[str, object]],
    incomplete: bool,
    warnings: list[str],
    *,
    max_depth: int,
    max_files: int,
) -> dict[str, object]:
    """Build the public response while keeping scan scope explicit."""
    scan_complete = not incomplete
    return {
        "success": True,
        "framework": framework,
        "run_all_command": run_all_command,
        "test_files_count": len(test_files),
        "test_files": test_files,
        "coverage": {
            "scan_complete": scan_complete,
            "scan_complete_within_scope": scan_complete,
            "scope": "current supported test files emitted by repo_tools iterator",
            "max_depth": max_depth,
            "max_files": max_files,
            "inventory_omissions_unknown": True,
            "warnings": sorted(set(warnings)),
        },
    }

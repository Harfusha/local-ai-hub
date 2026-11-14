from __future__ import annotations

import ast
import logging
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable


logger = logging.getLogger(f"{__package__}.deterministic")


def analyze_call_graph_diff(root: str | Path, diff: str | None, detect_breaking_changes: Callable[[str, list[str], list[str]], list[dict[str, Any]]]) -> dict[str, Any]:
    """Analyze breaking function/class signature changes against all call sites in the repository."""
    root_path = Path(root).resolve()
    if diff is None:
        try:
            from .process_utils import hidden_run_kwargs
            cp = subprocess.run(
                ["git", "diff", "HEAD"],
                cwd=str(root_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=15,
                **hidden_run_kwargs(),
            )
            diff = cp.stdout or ""
        except Exception:
            diff = ""

    file_diff_lines: dict[str, dict[str, list[str]]] = defaultdict(lambda: {"added": [], "deleted": []})
    current = orig_file = ""
    for line in diff.splitlines():
        if line.startswith("--- a/"):
            orig_file = line[6:].strip()
            current = ""
        elif line.startswith("+++ b/"):
            current = line[6:].strip()
        elif line.startswith("+++ /dev/null") and orig_file:
            current = orig_file
        elif line.startswith("+") and not line.startswith("+++"):
            if current:
                file_diff_lines[current]["added"].append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            target = current or orig_file
            if target:
                file_diff_lines[target]["deleted"].append(line[1:])

    breaking_changes: list[dict[str, Any]] = []
    for file_path, lines_dict in file_diff_lines.items():
        bcs = detect_breaking_changes(file_path, lines_dict["deleted"], lines_dict["added"])
        breaking_changes.extend(bcs)

    breaking_by_symbol = {b["symbol"]: b for b in breaking_changes}
    breaking_callers: list[dict[str, Any]] = []

    if breaking_by_symbol and root_path.is_dir():
        skip_dirs = {".git", "__pycache__", ".venv", "venv", "node_modules", ".pytest_cache"}
        for py_path in root_path.rglob("*.py"):
            if any(part in skip_dirs for part in py_path.parts):
                continue
            try:
                src = py_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            if not any(sym in src for sym in breaking_by_symbol):
                continue
            try:
                tree = ast.parse(src)
            except Exception:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    callee = ""
                    if isinstance(node.func, ast.Name):
                        callee = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        callee = node.func.attr

                    if callee in breaking_by_symbol:
                        info = breaking_by_symbol[callee]
                        b_type = info.get("type")
                        reason = ""
                        if b_type == "removed_symbol":
                            reason = f"Call to removed symbol '{callee}'"
                        elif b_type == "signature_changed":
                            kw_names = {kw.arg for kw in node.keywords if kw.arg}
                            removed_args = info.get("removed_args", [])
                            removed_overlap = kw_names & set(removed_args)
                            if removed_overlap:
                                reason = f"Call passes removed or renamed parameter(s): {', '.join(sorted(removed_overlap))}"
                            else:
                                has_varargs = any(isinstance(a, ast.Starred) for a in node.args)
                                has_kwargs = any(kw.arg is None for kw in node.keywords)
                                new_req = info.get("new_req", 0)
                                passed_args = len(node.args) + len(kw_names)
                                if not (has_varargs or has_kwargs) and passed_args < new_req:
                                    reason = f"Missing required parameter(s): expected at least {new_req}, passed {passed_args}"

                        if reason:
                            try:
                                rel_file = str(py_path.relative_to(root_path)).replace("\\", "/")
                            except Exception:
                                rel_file = str(py_path).replace("\\", "/")
                            snippet = ""
                            try:
                                snippet = ast.unparse(node)
                            except (ValueError, TypeError, RecursionError) as render_exc:
                                logger.debug(
                                    "Caller snippet rendering skipped (%s)",
                                    type(render_exc).__name__,
                                )
                            breaking_callers.append({
                                "file": rel_file,
                                "line": getattr(node, "lineno", 0),
                                "callee": callee,
                                "reason": reason,
                                "snippet": snippet,
                            })

    impacted_files = sorted(list({c["file"] for c in breaking_callers}))
    return {
        "success": True,
        "modified_symbols": breaking_changes,
        "breaking_callers": breaking_callers,
        "impacted_files": impacted_files,
        "summary": f"Found {len(breaking_callers)} breaking call site(s) across {len(impacted_files)} file(s).",
    }

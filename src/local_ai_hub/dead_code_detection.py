from __future__ import annotations

import ast as _ast
import os as _os
from pathlib import Path as _Path
from typing import Any


def find_dead_code(
    engine: Any,
    root: str,
    limit: int = 50,
    *,
    path_type: Any = _Path,
    os_module: Any = _os,
    ast_module: Any = _ast,
) -> dict[str, Any]:
    cached = engine.get_unreferenced_symbols(root, limit=limit)
    if cached:
        return {"success": True, "root": engine._root(root), "dead_code": cached}

    if engine.code_index is not None:
        try:
            st = engine.code_index.status(root)
            if st.get("symbols", 0) > 0:
                res = engine.code_index.find_dead_code(root, limit=limit)
                if res.get("success"):
                    return res
        except Exception:
            pass

    p_root = path_type(engine._root(root))
    if not p_root.is_dir():
        return {"success": False, "error": f"root not found: {root}"}

    defs: dict[str, dict[str, Any]] = {}
    usages: set[str] = set()

    for dirpath, dirnames, filenames in os_module.walk(p_root):
        dirnames[:] = [
            d for d in dirnames
            if not (
                d.startswith((".", "node_modules", "venv", ".git", "test", "tool-envs", "site-packages"))
                or d in {"tool-envs", "venv", ".venv", "site-packages", "node_modules", "__pycache__", "build", "dist"}
            )
        ]
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            p = path_type(dirpath) / fname
            rel = str(p.relative_to(p_root)).replace("\\", "/")
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
                tree = ast_module.parse(content, filename=str(p))
                for node in ast_module.walk(tree):
                    if isinstance(node, (ast_module.FunctionDef, ast_module.AsyncFunctionDef)):
                        if not node.name.startswith("_") and node.name not in ("main", "run", "cli", "app"):
                            defs[f"{rel}::{node.name}"] = {
                                "file": rel, "name": node.name, "line": node.lineno, "kind": "function"
                            }
                    elif isinstance(node, ast_module.ClassDef):
                        if not node.name.startswith("_"):
                            defs[f"{rel}::{node.name}"] = {
                                "file": rel, "name": node.name, "line": node.lineno, "kind": "class"
                            }
                    elif isinstance(node, ast_module.Name) and isinstance(node.ctx, ast_module.Load):
                        usages.add(node.id)
                    elif isinstance(node, ast_module.Attribute) and isinstance(node.ctx, ast_module.Load):
                        usages.add(node.attr)
            except Exception:
                continue

    dead_candidates: list[dict[str, Any]] = []
    for key, item in defs.items():
        if item["name"] not in usages:
            dead_candidates.append(item)
            if len(dead_candidates) >= limit:
                break

    return {
        "success": True,
        "candidate_count": len(dead_candidates),
        "dead_code": dead_candidates,
        "dead_symbols": dead_candidates,
    }


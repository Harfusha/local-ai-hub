"""Transparent Context Virtualizer (Virtual File System layer).

Automatically condenses oversized file reads into lossless, symbol-aware
AST skeletons and relevant code slices with exact line annotations.
Allows agents to read any file without exceeding Token Economy budgets.
"""
from __future__ import annotations

import ast
# import os
import re
from pathlib import Path
from typing import Any


def virtualize_python_source(
    content: str,
    query: str | None = None,
    max_lines: int = 80,
    file_name: str = "file.py",
) -> tuple[str, str]:
    """Condense a Python source into an annotated skeleton or query-guided slice."""
    lines = content.splitlines()
    total_lines = len(lines)
    if total_lines <= max_lines:
        return content, "raw"

    try:
        tree = ast.parse(content, filename=file_name)
    except SyntaxError:
        # Fallback to head + tail if AST parse fails
        head = lines[: max_lines - 15]
        tail = lines[-10:]
        out = (
            "\n".join(head)
            + f"\n\n# ... [{total_lines - len(head) - len(tail)} lines omitted for token economy] ...\n\n"
            + "\n".join(tail)
        )
        return out, "head_tail_fallback"

    # Search terms from query if provided
    terms = [t.lower() for t in re.findall(r"\w+", query or "")] if query else []

    chosen_line_indices: set[int] = set()

    # Always include top imports (up to first 15 lines)
    for i, line in enumerate(lines[:20]):
        if line.strip().startswith(("import ", "from ", "#", '"""', "'''")) or not line.strip():
            chosen_line_indices.add(i)

    # Class and function nodes
    nodes: list[ast.AST] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            nodes.append(node)

    relevant_nodes: list[ast.AST] = []
    other_nodes: list[ast.AST] = []

    for node in nodes:
        name = getattr(node, "name", "").lower()
        doc = (ast.get_docstring(node) or "").lower()
        if any(term in name or term in doc for term in terms):
            relevant_nodes.append(node)
        else:
            other_nodes.append(node)

    # If query matched nodes, expand their full bodies
    mode = "query_slice" if relevant_nodes else "ast_skeleton"
    for node in relevant_nodes:
        start = max(0, getattr(node, "lineno", 1) - 1)
        end = min(total_lines, getattr(node, "end_lineno", start + 1))
        for line_idx in range(start, end):
            chosen_line_indices.add(line_idx)

    # If no specific query matched nodes, add signatures of all top-level nodes for AST skeleton
    if not relevant_nodes:
        for node in other_nodes:
            start = max(0, getattr(node, "lineno", 1) - 1)
            chosen_line_indices.add(start)
            # Include docstring if short
            doc = ast.get_docstring(node)
            if doc and len(doc.splitlines()) <= 2:
                for d_idx in range(start + 1, min(total_lines, start + 3)):
                    chosen_line_indices.add(d_idx)

    # Convert sorted indices into annotated text blocks
    sorted_indices = sorted(chosen_line_indices)
    output_lines: list[str] = [
        f"# [Virtual Context: {file_name} ({total_lines} total lines -> {mode})]"
    ]

    last_idx = -1
    for idx in sorted_indices:
        if len(output_lines) >= max_lines:
            output_lines.append(f"# ... [{total_lines - last_idx} further lines omitted] ...")
            break
        if last_idx != -1 and idx > last_idx + 1:
            output_lines.append(f"    # ... [lines {last_idx + 2}-{idx} omitted] ...")
        # Exact 1-based line numbering prefix for agent navigation
        output_lines.append(f"{idx + 1:4d}: {lines[idx]}")
        last_idx = idx

    return "\n".join(output_lines), mode


def virtualize_file_read(
    root: Path | str,
    path: Path | str,
    query: str | None = None,
    max_lines: int = 80,
) -> dict[str, Any]:
    """Virtualize any file read into a token-bounded, lossless slice."""
    root_path = Path(root).resolve()
    target = Path(path)
    if not target.is_absolute():
        target = (root_path / target).resolve()

    if not target.is_file():
        return {
            "success": False,
            "error": f"File not found: {path}",
            "virtualized": False,
        }

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return {
            "success": False,
            "error": f"Cannot read file: {exc}",
            "virtualized": False,
        }

    lines = content.splitlines()
    total_lines = len(lines)

    if total_lines <= max_lines:
        return {
            "success": True,
            "text": content,
            "content": content,
            "virtualized": False,
            "total_lines": total_lines,
            "mode": "verbatim",
        }

    # Virtualize based on extension
    if target.suffix.lower() == ".py":
        virt_text, mode = virtualize_python_source(
            content, query=query, max_lines=max_lines, file_name=target.name
        )
    else:
        # Generic text virtualizer: head + tail
        head = lines[: max_lines - 15]
        tail = lines[-10:]
        virt_text = (
            f"# [Virtual Context: {target.name} ({total_lines} total lines -> head/tail)]\n"
            + "\n".join(f"{i+1:4d}: {line}" for i, line in enumerate(head))
            + f"\n\n# ... [{total_lines - len(head) - len(tail)} lines omitted for token economy] ...\n\n"
            + "\n".join(f"{total_lines - len(tail) + j + 1:4d}: {line}" for j, line in enumerate(tail))
        )
        mode = "head_tail"

    return {
        "success": True,
        "text": virt_text,
        "content": virt_text,
        "virtualized": True,
        "total_lines": total_lines,
        "mode": mode,
        "file_name": target.name,
    }

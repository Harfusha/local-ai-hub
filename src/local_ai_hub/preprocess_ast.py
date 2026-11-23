"""AST-directed granular symbol chunking and content-addressed hashing.

Extracts symbol-level units (functions, classes, methods, interfaces) from source
files with stable content-addressed SHA-256 hashes per symbol body. When a file is
modified, unmodified symbol chunks can be reused directly from cache, avoiding
redundant full-file re-summarization or embedding.
"""

from __future__ import annotations

import ast
import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence


@dataclass(frozen=True)
class AstSymbolChunk:
    """One symbol-level syntactic chunk with content-addressed hash."""

    name: str
    kind: str  # "class", "function", "async_function", "method", "interface", "type"
    start_line: int
    end_line: int
    body_sha256: str
    signature: str = ""
    docstring: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AstSymbolChunk:
        return cls(
            name=str(data.get("name", "")),
            kind=str(data.get("kind", "function")),
            start_line=int(data.get("start_line", 1)),
            end_line=int(data.get("end_line", 1)),
            body_sha256=str(data.get("body_sha256", "")),
            signature=str(data.get("signature", "")),
            docstring=str(data.get("docstring", "")),
        )


@dataclass(frozen=True)
class SymbolDiffResult:
    """Diff between two sets of symbol chunks for a file."""

    unchanged: tuple[AstSymbolChunk, ...]
    modified: tuple[tuple[AstSymbolChunk, AstSymbolChunk], ...]  # (old, new)
    added: tuple[AstSymbolChunk, ...]
    deleted: tuple[AstSymbolChunk, ...]

    @property
    def reuse_ratio(self) -> float:
        total = len(self.unchanged) + len(self.modified) + len(self.added)
        if total == 0:
            return 1.0
        return len(self.unchanged) / float(total)


def _compute_chunk_sha(lines: Sequence[str], start_1: int, end_1: int) -> str:
    """Hash the exact lines of a symbol (1-indexed inclusive)."""
    s = max(0, start_1 - 1)
    e = min(len(lines), end_1)
    chunk_text = "\n".join(lines[s:e])
    return hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()


def _extract_python_symbols(source: str) -> list[AstSymbolChunk]:
    """Parse Python AST and extract classes, functions, and methods."""
    lines = source.splitlines()
    symbols: list[AstSymbolChunk] = []

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return _extract_regex_symbols(source, ext=".py")

    def visit_node(node: ast.AST, parent_name: str = "") -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn_name = f"{parent_name}.{node.name}" if parent_name else node.name
            kind = "method" if parent_name else ("async_function" if isinstance(node, ast.AsyncFunctionDef) else "function")
            start = getattr(node, "lineno", 1)
            end = getattr(node, "end_lineno", start)
            doc = ast.get_docstring(node) or ""
            
            # Format signature
            args = [a.arg for a in node.args.args]
            sig = f"{node.name}({', '.join(args)})"
            
            body_sha = _compute_chunk_sha(lines, start, end)
            symbols.append(AstSymbolChunk(
                name=fn_name,
                kind=kind,
                start_line=start,
                end_line=end,
                body_sha256=body_sha,
                signature=sig,
                docstring=doc[:200],
            ))

            # Inner functions
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    visit_node(child, fn_name)

        elif isinstance(node, ast.ClassDef):
            cls_name = f"{parent_name}.{node.name}" if parent_name else node.name
            start = getattr(node, "lineno", 1)
            end = getattr(node, "end_lineno", start)
            doc = ast.get_docstring(node) or ""
            body_sha = _compute_chunk_sha(lines, start, end)
            symbols.append(AstSymbolChunk(
                name=cls_name,
                kind="class",
                start_line=start,
                end_line=end,
                body_sha256=body_sha,
                signature=f"class {node.name}",
                docstring=doc[:200],
            ))
            for child in node.body:
                visit_node(child, cls_name)

    for item in tree.body:
        visit_node(item)

    return symbols


import re

_GENERIC_PATTERNS = [
    # JavaScript/TypeScript/Rust/Go/C++ function/class/interface patterns
    (r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z0-9_$]+)\s*\(([^)]*)\)", "function"),
    (r"^\s*(?:export\s+)?class\s+([A-Za-z0-9_$]+)", "class"),
    (r"^\s*(?:export\s+)?interface\s+([A-Za-z0-9_$]+)", "interface"),
    (r"^\s*(?:export\s+)?type\s+([A-Za-z0-9_$]+)\s*=", "type"),
    (r"^\s*(?:pub\s+)?fn\s+([A-Za-z0-9_]+)\s*\(([^)]*)\)", "function"),
    (r"^\s*func\s+(?:\([^)]+\)\s+)?([A-Za-z0-9_]+)\s*\(([^)]*)\)", "function"),
    (r"^\s*(?:def|class)\s+([A-Za-z0-9_]+)", "symbol"),
]


def _extract_regex_symbols(source: str, ext: str = "") -> list[AstSymbolChunk]:
    """Lightweight regex extractor for multi-language symbol spans."""
    lines = source.splitlines()
    symbols: list[AstSymbolChunk] = []

    compiled = [(re.compile(pat), kind) for pat, kind in _GENERIC_PATTERNS]

    for idx, line in enumerate(lines):
        line_num = idx + 1
        for rx, kind in compiled:
            m = rx.match(line)
            if m:
                sym_name = m.group(1)
                # Approximate block end: until next top-level or +30 lines
                end_line = min(len(lines), line_num + 30)
                body_sha = _compute_chunk_sha(lines, line_num, end_line)
                symbols.append(AstSymbolChunk(
                    name=sym_name,
                    kind=kind,
                    start_line=line_num,
                    end_line=end_line,
                    body_sha256=body_sha,
                    signature=line.strip()[:100],
                ))
                break

    return symbols


def extract_ast_symbol_chunks(path: str | Path, source: str) -> list[AstSymbolChunk]:
    """Extract symbol-level chunks with body hashes for any supported language."""
    p = Path(path)
    suffix = p.suffix.lower()

    if suffix == ".py":
        return _extract_python_symbols(source)
    return _extract_regex_symbols(source, ext=suffix)


def diff_ast_symbols(
    old_chunks: Sequence[AstSymbolChunk],
    new_chunks: Sequence[AstSymbolChunk],
) -> SymbolDiffResult:
    """Compare old vs new symbol chunks to determine cached reuse vs modified."""
    old_by_name = {c.name: c for c in old_chunks}
    new_by_name = {c.name: c for c in new_chunks}

    unchanged: list[AstSymbolChunk] = []
    modified: list[tuple[AstSymbolChunk, AstSymbolChunk]] = []
    added: list[AstSymbolChunk] = []
    deleted: list[AstSymbolChunk] = []

    for name, new_chunk in new_by_name.items():
        if name in old_by_name:
            old_chunk = old_by_name[name]
            if old_chunk.body_sha256 == new_chunk.body_sha256:
                unchanged.append(new_chunk)
            else:
                modified.append((old_chunk, new_chunk))
        else:
            added.append(new_chunk)

    for name, old_chunk in old_by_name.items():
        if name not in new_by_name:
            deleted.append(old_chunk)

    return SymbolDiffResult(
        unchanged=tuple(unchanged),
        modified=tuple(modified),
        added=tuple(added),
        deleted=tuple(deleted),
    )


def enrich_card_with_ast_symbols(card_data: dict[str, Any], chunks: Sequence[AstSymbolChunk]) -> dict[str, Any]:
    """Attach granular AST symbol metadata and hash registry to preprocess card."""
    enriched = dict(card_data)
    symbol_records = [c.to_dict() for c in chunks]
    enriched["ast_symbol_chunks"] = symbol_records[:64]
    
    # Merge detected AST names into symbols array if not present
    existing_syms = set(enriched.get("symbols", []))
    for c in chunks:
        if len(existing_syms) < 32 and c.name not in existing_syms:
            existing_syms.add(c.name)
    enriched["symbols"] = sorted(list(existing_syms))[:32]
    return enriched

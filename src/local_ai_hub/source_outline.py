"""Source outline helpers kept independent from the repository engine."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Literal, NotRequired, TypedDict


class OutlineSuccess(TypedDict):
    success: Literal[True]
    path: str
    outline: str
    original_chars: NotRequired[int]
    outline_chars: NotRequired[int]
    reduction_pct: NotRequired[float]
    polyglot: NotRequired[bool]
    fallback: NotRequired[bool]


class OutlineFailure(TypedDict):
    success: Literal[False]
    error: str


OutlineResult = OutlineSuccess | OutlineFailure


_BRACE_FUNCTION_EXPORT = re.compile(
    r"^\s*(?:(?:pub(?:lic)?|priv(?:ate)?|prot(?:ected)?|internal|static|async|export|default|override|virtual|final)\s+)*"
    r"(?:(?:func|fn|function|def)\b|(?:[A-Za-z_$][\w.<>,\[\]]*\s+)+[A-Za-z_$][\w$]*\s*\()"
    r"|^\s*(?:func\s*\([^)]*\)\s*)?[A-Za-z_$][\w$]*\s*\([^)]*\)\s*(?:[^{;]*\{|=>)"
)
_BRACE_CLASS_INTERFACE = re.compile(
    r"^\s*(?:(?:pub(?:lic)?|export)\s+)*(?:struct|interface|enum|type|trait|class)\b"
)


def fold_brace_blocks(code: str, target_symbols: set[str] | None = None) -> str:
    """Fold function/method bodies in brace-based languages."""
    lines = code.splitlines()
    out: list[str] = []
    targets = target_symbols or set()

    in_func = False
    func_brace_depth = 0
    current_brace_depth = 0

    for line in lines:
        stripped = line.strip()
        if stripped.startswith(("//", "#", "/*", "*")):
            if not in_func:
                out.append(line)
            continue

        if not in_func:
            if (
                _BRACE_FUNCTION_EXPORT.search(line)
                and not _BRACE_CLASS_INTERFACE.search(line)
                and ("{" in line or "=>" in line)
            ):
                is_target = any(sym in line for sym in targets) if targets else False
                if not is_target and "{" in line:
                    in_func = True
                    func_brace_depth = current_brace_depth
                    idx = line.find("{")
                    out.append(line[: idx + 1])
                    out.append("    /* ... */")
                    current_brace_depth += line.count("{") - line.count("}")
                    if current_brace_depth <= func_brace_depth:
                        in_func = False
                        out.append("}")
                    continue

            out.append(line)
            current_brace_depth += line.count("{") - line.count("}")
        else:
            current_brace_depth += line.count("{") - line.count("}")
            if current_brace_depth <= func_brace_depth:
                in_func = False
                indent = " " * (len(line) - len(line.lstrip()))
                out.append(f"{indent}}}")

    return "\n".join(out)


def ast_outline(root: str, path: str) -> OutlineResult:
    """Return a token-compact structural outline of a source file."""
    p_root = Path(root).resolve()
    target = Path(path)
    if not target.is_absolute():
        target = p_root / target
    target = target.resolve()
    if not target.is_relative_to(p_root):
        return {"success": False, "error": "file is outside project root"}
    if not target.is_file():
        return {"success": False, "error": f"file not found: {path}"}

    content = target.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(content, filename=str(target))

        class _BodyEllipsisTransformer(ast.NodeTransformer):
            def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
                doc = ast.get_docstring(node)
                new_body: list[ast.stmt] = []
                if doc:
                    new_body.append(ast.Expr(value=ast.Constant(value=doc)))
                new_body.append(ast.Expr(value=ast.Constant(value=Ellipsis)))
                node.body = new_body
                return self.generic_visit(node)

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
                doc = ast.get_docstring(node)
                new_body: list[ast.stmt] = []
                if doc:
                    new_body.append(ast.Expr(value=ast.Constant(value=doc)))
                new_body.append(ast.Expr(value=ast.Constant(value=Ellipsis)))
                node.body = new_body
                return self.generic_visit(node)

        transformer = _BodyEllipsisTransformer()
        new_tree = transformer.visit(tree)
        ast.fix_missing_locations(new_tree)
        outlined = ast.unparse(new_tree)
        char_savings = max(0, len(content) - len(outlined))
        token_savings_pct = round((char_savings / max(1, len(content))) * 100, 1)

        return {
            "success": True,
            "path": str(target.relative_to(p_root)).replace("\\", "/"),
            "outline": outlined,
            "original_chars": len(content),
            "outline_chars": len(outlined),
            "reduction_pct": token_savings_pct,
        }
    except Exception:
        if "{" in content and "}" in content:
            outlined = fold_brace_blocks(content)
            char_savings = max(0, len(content) - len(outlined))
            token_savings_pct = round((char_savings / max(1, len(content))) * 100, 1)
            return {
                "success": True,
                "path": str(target.relative_to(p_root)).replace("\\", "/"),
                "outline": outlined,
                "original_chars": len(content),
                "outline_chars": len(outlined),
                "reduction_pct": token_savings_pct,
                "polyglot": True,
            }
        out_lines = []
        for line in content.splitlines():
            if re.match(
                r"^\s*(?:def|class|async def|public|private|function|fn|func|interface|struct)\b",
                line,
            ):
                out_lines.append(line)
        outline_txt = "\n".join(out_lines)
        return {
            "success": True,
            "path": str(target.relative_to(p_root)).replace("\\", "/"),
            "outline": outline_txt or content[:1000],
            "fallback": True,
        }

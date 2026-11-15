"""Source outline helpers kept independent from the repository engine."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Literal, NotRequired, TypedDict

DEFAULT_MAX_SOURCE_BYTES = 512 * 1024  # 512 KB
HARD_CAP_MAX_SOURCE_BYTES = 10 * 1024 * 1024  # 10 MB


class OutlineSuccess(TypedDict):
    success: Literal[True]
    path: str
    outline: str
    original_chars: NotRequired[int]
    outline_chars: NotRequired[int]
    reduction_pct: NotRequired[float]
    polyglot: NotRequired[bool]
    fallback: NotRequired[bool]
    outline_verified: NotRequired[bool]
    completeness: NotRequired[Literal["complete", "partial", "unverified"]]
    fallback_type: NotRequired[str]
    truncated: NotRequired[bool]
    partial: NotRequired[bool]
    suggested_slice: NotRequired[dict[str, int]]


class OutlineFailure(TypedDict):
    success: Literal[False]
    error: str
    error_code: NotRequired[str]


OutlineResult = OutlineSuccess | OutlineFailure

_BRACE_FUNCTION_EXPORT = re.compile(
    r"^\s*(?:(?:pub(?:lic)?|priv(?:ate)?|prot(?:ected)?|internal|static|async|export|default|override|virtual|final)\s+)*"
    r"(?:(?:func|fn|function|def)\b|(?:[A-Za-z_$][\w.<>,\[\]]*\s+)+[A-Za-z_$][\w$]*\s*\()"
    r"|^\s*(?:func\s*\([^)]*\)\s*)?[A-Za-z_$][\w$]*\s*\([^)]*\)\s*(?:[^{;]*\{|=>)"
)
_BRACE_CLASS_INTERFACE = re.compile(
    r"^\s*(?:(?:pub(?:lic)?|export)\s+)*(?:struct|interface|enum|type|trait|class)\b"
)


class LexicalBraceScanner:
    """State-aware lexical scanner for brace matching across JS/TS/PHP/C#/Go/Rust."""

    def __init__(self) -> None:
        self.state = "CODE"
        self.template_stack: list[int] = []
        self.heredoc_label = ""
        self.brace_depth = 0
        self.in_regex_class = False
        self.prev_token = ""

    def process_line(self, line: str) -> list[tuple[str, int, int]]:
        """Scan line and return brace events: (char, depth_after, col_index)."""
        events: list[tuple[str, int, int]] = []
        i = 0
        n = len(line)

        if self.state == "HEREDOC":
            stripped = line.strip()
            if stripped.startswith(self.heredoc_label):
                rem = stripped[len(self.heredoc_label):].strip()
                if not rem or rem.startswith(";"):
                    self.state = "CODE"
                    self.heredoc_label = ""
                    self.prev_token = ";"
                    return events
            return events

        while i < n:
            ch = line[i]
            if self.state == "CODE":
                if ch.isspace():
                    i += 1
                    continue

                if ch == "/" and i + 1 < n and line[i + 1] == "/":
                    break
                if ch == "#":
                    if i == 0 or line[i - 1].isspace():
                        break

                if ch == "/" and i + 1 < n and line[i + 1] == "*":
                    self.state = "BLOCK_COMMENT"
                    i += 2
                    continue

                if ch == '"':
                    self.state = "STRING_DOUBLE"
                    i += 1
                    continue
                if ch == "'":
                    self.state = "STRING_SINGLE"
                    i += 1
                    continue
                if ch == "`":
                    self.state = "TEMPLATE"
                    i += 1
                    continue

                if ch == "<" and i + 2 < n and line[i:i + 3] == "<<<":
                    j = i + 3
                    while j < n and line[j] in " \t":
                        j += 1
                    if j < n and line[j] in "'\"":
                        j += 1
                    lbl_start = j
                    while j < n and (line[j].isalnum() or line[j] == "_"):
                        j += 1
                    label = line[lbl_start:j]
                    if label:
                        self.state = "HEREDOC"
                        self.heredoc_label = label
                        break
                    i = j
                    continue

                if ch == "/":
                    can_start_regex = self.prev_token in {
                        "", "(", "[", "{", ";", ",", "=", "+", "-", "*", "!",
                        "&", "|", "?", ":", "~", "^", "%", "return", "throw",
                        "yield", "case", "=>",
                    }
                    if can_start_regex:
                        self.state = "REGEX"
                        self.in_regex_class = False
                        i += 1
                        continue
                    else:
                        self.prev_token = "/"
                        i += 1
                        continue

                if ch == "{":
                    self.brace_depth += 1
                    events.append(("{", self.brace_depth, i))
                    self.prev_token = "{"
                    i += 1
                    continue

                if ch == "}":
                    if self.template_stack and self.brace_depth == self.template_stack[-1]:
                        self.template_stack.pop()
                        self.state = "TEMPLATE"
                    else:
                        self.brace_depth = max(0, self.brace_depth - 1)
                        events.append(("}", self.brace_depth, i))
                    self.prev_token = "}"
                    i += 1
                    continue

                if ch.isalnum() or ch in "_$":
                    w_start = i
                    while i < n and (line[i].isalnum() or line[i] in "_$"):
                        i += 1
                    self.prev_token = line[w_start:i]
                    continue
                else:
                    self.prev_token = ch
                    i += 1
                    continue

            elif self.state == "STRING_DOUBLE":
                if ch == "\\" and i + 1 < n:
                    i += 2
                    continue
                if ch == '"':
                    self.state = "CODE"
                    self.prev_token = '"'
                i += 1

            elif self.state == "STRING_SINGLE":
                if ch == "\\" and i + 1 < n:
                    i += 2
                    continue
                if ch == "'":
                    self.state = "CODE"
                    self.prev_token = "'"
                i += 1

            elif self.state == "BLOCK_COMMENT":
                if ch == "*" and i + 1 < n and line[i + 1] == "/":
                    self.state = "CODE"
                    i += 2
                    continue
                i += 1

            elif self.state == "TEMPLATE":
                if ch == "\\" and i + 1 < n:
                    i += 2
                    continue
                if ch == "`":
                    self.state = "CODE"
                    self.prev_token = "`"
                    i += 1
                    continue
                if ch == "$" and i + 1 < n and line[i + 1] == "{":
                    self.template_stack.append(self.brace_depth)
                    self.state = "CODE"
                    self.prev_token = "{"
                    i += 2
                    continue
                i += 1

            elif self.state == "REGEX":
                if ch == "\\" and i + 1 < n:
                    i += 2
                    continue
                if ch == "[":
                    self.in_regex_class = True
                    i += 1
                    continue
                if ch == "]" and self.in_regex_class:
                    self.in_regex_class = False
                    i += 1
                    continue
                if ch == "/" and not self.in_regex_class:
                    self.state = "CODE"
                    self.prev_token = "/"
                    i += 1
                    continue
                i += 1

        return events


def fold_brace_blocks(code: str, target_symbols: set[str] | None = None) -> str:
    """Fold function/method bodies in brace-based languages."""
    lines = code.splitlines()
    out: list[str] = []
    targets = target_symbols or set()

    scanner = LexicalBraceScanner()
    in_func = False
    func_brace_depth = 0

    for line in lines:
        stripped = line.strip()
        if stripped.startswith(("//", "#", "/*", "*")):
            if not in_func:
                out.append(line)
            scanner.process_line(line)
            continue

        if not in_func:
            is_func_decl = (
                bool(_BRACE_FUNCTION_EXPORT.search(line))
                and not bool(_BRACE_CLASS_INTERFACE.search(line))
                and ("{" in line or "=>" in line)
            )
            is_target = any(bool(re.search(rf"\b{re.escape(sym)}\b", line)) for sym in targets) if targets else False

            depth_before = scanner.brace_depth
            events = scanner.process_line(line)

            if is_func_decl and not is_target:
                body_brace_col = None
                if scanner.brace_depth > depth_before:
                    balance = 0
                    unclosed: list[int] = []
                    for ev_type, _, col in reversed(events):
                        if ev_type == "}":
                            balance += 1
                        elif ev_type == "{":
                            if balance > 0:
                                balance -= 1
                            else:
                                unclosed.append(col)
                    if unclosed:
                        body_brace_col = unclosed[-1]
                elif any(ev[0] == "{" for ev in events):
                    last_param_close = max(line.rfind(")"), line.rfind("=>"))
                    for ev_type, _, col in events:
                        if ev_type == "{" and (last_param_close == -1 or col > last_param_close):
                            body_brace_col = col
                            break

                if body_brace_col is not None:
                    if scanner.brace_depth <= depth_before:
                        out.append(f"{line[:body_brace_col + 1]} /* ... */ }}")
                        continue

                    in_func = True
                    func_brace_depth = depth_before
                    out.append(line[:body_brace_col + 1])
                    out.append("    /* ... */")
                    continue

            out.append(line)
        else:
            scanner.process_line(line)
            if scanner.brace_depth <= func_brace_depth:
                in_func = False
                indent = " " * (len(line) - len(line.lstrip()))
                out.append(f"{indent}}}")

    return "\n".join(out)


def ast_outline(
    root: str,
    path: str,
    max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES,
    target_symbols: set[str] | None = None,
) -> OutlineResult:
    """Return a token-compact structural outline of a source file."""
    if not isinstance(max_source_bytes, int) or isinstance(max_source_bytes, bool) or max_source_bytes <= 0:
        max_source_bytes = DEFAULT_MAX_SOURCE_BYTES
    elif max_source_bytes > HARD_CAP_MAX_SOURCE_BYTES:
        max_source_bytes = HARD_CAP_MAX_SOURCE_BYTES

    p_root = Path(root).resolve()
    target = Path(path)
    if not target.is_absolute():
        target = p_root / target
    target = target.resolve()
    if not target.is_relative_to(p_root):
        return {"success": False, "error": "file is outside project root"}
    if not target.is_file():
        return {"success": False, "error": f"file not found: {path}"}

    try:
        st = target.stat()
        file_size = st.st_size
    except OSError:
        return {
            "success": False,
            "error": "unable to read source file",
            "error_code": "source_read_error",
        }

    rel_path = str(target.relative_to(p_root)).replace("\\", "/")

    if file_size == 0:
        return {
            "success": True,
            "path": rel_path,
            "outline": "",
            "original_chars": 0,
            "outline_chars": 0,
            "reduction_pct": 0.0,
            "truncated": False,
            "partial": False,
            "completeness": "complete",
            "outline_verified": True,
        }

    try:
        if file_size <= max_source_bytes:
            content = target.read_text(encoding="utf-8", errors="replace")
            if "\x00" in content[:8192]:
                return {
                    "success": False,
                    "error": f"binary file not supported: {path}",
                    "error_code": "binary_file",
                }
            is_truncated = False
        else:
            is_truncated = True
            with open(target, "rb") as f:
                raw_bytes = f.read(max_source_bytes)
            if b"\x00" in raw_bytes[:8192]:
                return {
                    "success": False,
                    "error": f"binary file not supported: {path}",
                    "error_code": "binary_file",
                }
            content = raw_bytes.decode("utf-8", errors="replace")
    except OSError:
        return {
            "success": False,
            "error": "unable to read source file",
            "error_code": "source_read_error",
        }

    if is_truncated:
        if "\n" in content:
            content = content.rsplit("\n", 1)[0] + "\n"
        line_count = len(content.splitlines())
        if "{" in content and "}" in content:
            outlined = fold_brace_blocks(content, target_symbols=target_symbols)
        else:
            out_lines = []
            for line in content.splitlines():
                if re.match(
                    r"^\s*(?:def|class|async def|public|private|function|fn|func|interface|struct)\b",
                    line,
                ):
                    out_lines.append(line)
            outlined = "\n".join(out_lines) or content[:1000]

        char_savings = max(0, file_size - len(outlined))
        token_savings_pct = round((char_savings / max(1, file_size)) * 100, 1)
        return {
            "success": True,
            "path": rel_path,
            "outline": outlined,
            "original_chars": file_size,
            "outline_chars": len(outlined),
            "reduction_pct": token_savings_pct,
            "truncated": True,
            "partial": True,
            "completeness": "partial",
            "outline_verified": False,
            "fallback_type": "truncated_head",
            "suggested_slice": {"start_line": 1, "end_line": max(1, line_count)},
        }

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
            "path": rel_path,
            "outline": outlined,
            "original_chars": len(content),
            "outline_chars": len(outlined),
            "reduction_pct": token_savings_pct,
            "truncated": False,
            "partial": False,
            "completeness": "complete",
            "outline_verified": True,
        }
    except Exception:
        if "{" in content and "}" in content:
            outlined = fold_brace_blocks(content, target_symbols=target_symbols)
            char_savings = max(0, len(content) - len(outlined))
            token_savings_pct = round((char_savings / max(1, len(content))) * 100, 1)
            return {
                "success": True,
                "path": rel_path,
                "outline": outlined,
                "original_chars": len(content),
                "outline_chars": len(outlined),
                "reduction_pct": token_savings_pct,
                "truncated": False,
                "partial": False,
                "completeness": "unverified",
                "polyglot": True,
                "outline_verified": False,
                "fallback_type": "lexical",
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
            "path": rel_path,
            "outline": outline_txt or content[:1000],
            "truncated": False,
            "partial": False,
            "completeness": "unverified",
            "fallback": True,
            "outline_verified": False,
            "fallback_type": "line_pattern",
        }

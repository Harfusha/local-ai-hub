"""treesitter_parser.py — Tree-Sitter AST symbol and reference extractor.

Provides robust, syntax-aware AST extraction for C#, TypeScript, JavaScript,
and Python. Falls back gracefully when language grammars are missing.
"""
from __future__ import annotations

import logging
import os
import re
import sys
import threading
from typing import Any

logger = logging.getLogger(__name__)

_PARSERS: dict[str, Any] = {}
_LANGUAGES: dict[str, Any] = {}
_INIT_ATTEMPTED = False
_PARSER_LOCK = threading.RLock()


def _init_treesitter() -> bool:
    global _INIT_ATTEMPTED
    if _INIT_ATTEMPTED:
        return bool(_PARSERS)
    _INIT_ATTEMPTED = True

    # The bundled native Tree-sitter wheels currently access-violate on Windows
    # with Python 3.13 while walking some Unity/Go syntax trees. All callers have
    # safe language-specific fallbacks, so keep the Hub process stable here.
    if os.name == "nt" and sys.version_info >= (3, 13):
        logger.warning("Tree-sitter disabled on Windows Python 3.13+; using safe fallbacks")
        return False

    try:
        from tree_sitter import Language, Parser
    except ImportError:
        return False

    # C#
    try:
        import tree_sitter_c_sharp as tscs
        lang = Language(tscs.language())
        _LANGUAGES["csharp"] = lang
        _PARSERS["csharp"] = Parser(lang)
    except Exception as exc:
        logger.debug("Tree-sitter C# grammar unavailable: %s", exc)

    # TypeScript
    try:
        import tree_sitter_typescript as tsts
        lang_ts = Language(tsts.language_typescript())
        _LANGUAGES["typescript"] = lang_ts
        _PARSERS["typescript"] = Parser(lang_ts)
        lang_tsx = Language(tsts.language_tsx())
        _LANGUAGES["tsx"] = lang_tsx
        _PARSERS["tsx"] = Parser(lang_tsx)
    except Exception as exc:
        logger.debug("Tree-sitter TypeScript grammar unavailable: %s", exc)

    # JavaScript
    try:
        import tree_sitter_javascript as tsjs
        lang = Language(tsjs.language())
        _LANGUAGES["javascript"] = lang
        _PARSERS["javascript"] = Parser(lang)
    except Exception as exc:
        logger.debug("Tree-sitter JavaScript grammar unavailable: %s", exc)

    # Python
    try:
        import tree_sitter_python as tspy
        lang = Language(tspy.language())
        _LANGUAGES["python"] = lang
        _PARSERS["python"] = Parser(lang)
    except Exception as exc:
        logger.debug("Tree-sitter Python grammar unavailable: %s", exc)

    # Go
    try:
        import tree_sitter_go as tsgo
        lang = Language(tsgo.language())
        _LANGUAGES["go"] = lang
        _PARSERS["go"] = Parser(lang)
    except Exception as exc:
        logger.debug("Tree-sitter Go grammar unavailable: %s", exc)

    # Rust
    try:
        import tree_sitter_rust as tsrs
        lang = Language(tsrs.language())
        _LANGUAGES["rust"] = lang
        _PARSERS["rust"] = Parser(lang)
    except Exception as exc:
        logger.debug("Tree-sitter Rust grammar unavailable: %s", exc)

    return bool(_PARSERS)


def is_treesitter_available(lang: str) -> bool:
    if not _INIT_ATTEMPTED:
        _init_treesitter()
    norm = lang.lower().strip()
    if norm in ("cs", "csharp"):
        return "csharp" in _PARSERS
    if norm in ("ts", "typescript"):
        return "typescript" in _PARSERS
    if norm == "tsx":
        return "tsx" in _PARSERS or "typescript" in _PARSERS
    if norm in ("js", "javascript", "jsx"):
        return "javascript" in _PARSERS
    if norm in ("py", "python"):
        return "python" in _PARSERS
    if norm in ("go", "golang"):
        return "go" in _PARSERS
    if norm in ("rs", "rust"):
        return "rust" in _PARSERS
    return False


def parse_treesitter(
    text: str, language: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]] | None:
    """Parse source text using Tree-Sitter.

    Returns (symbols, refs, edges) or None if tree-sitter is unavailable for this language.
    """
    if not text or not text.strip():
        return [], [], []

    if not _INIT_ATTEMPTED:
        _init_treesitter()

    norm = language.lower().strip()
    key = {
        "cs": "csharp", "csharp": "csharp",
        "ts": "typescript", "typescript": "typescript",
        "tsx": "tsx" if "tsx" in _PARSERS else "typescript",
        "js": "javascript", "jsx": "javascript", "javascript": "javascript",
        "py": "python", "python": "python",
        "go": "go", "golang": "go",
        "rs": "rust", "rust": "rust",
    }.get(norm)

    if not key or key not in _PARSERS:
        return None

    parser = _PARSERS[key]
    source_bytes = text.encode("utf-8", errors="replace")
    try:
        # Parser instances are mutable in the native Tree-sitter bindings and are
        # shared per language. Serialize calls so concurrent preprocessing cannot
        # corrupt parser state and crash the Python process.
        with _PARSER_LOCK:
            tree = parser.parse(source_bytes)
    except Exception as exc:
        logger.debug("Tree-sitter parse failed for %s: %s", language, exc)
        return None

    lines = text.splitlines()

    if key == "csharp":
        return _extract_csharp(tree.root_node, lines, source_bytes)
    elif key in ("typescript", "tsx", "javascript"):
        return _extract_js_ts(tree.root_node, lines, source_bytes)
    elif key == "python":
        return _extract_python(tree.root_node, lines, source_bytes)
    elif key == "go":
        return _extract_go(tree.root_node, lines, source_bytes)
    elif key == "rust":
        return _extract_rust(tree.root_node, lines, source_bytes)

    return None


def _node_text(node: Any, source_bytes: bytes) -> str:
    if node is None:
        return ""
    return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace").strip()


def _first_line_sig(node: Any, lines: list[str]) -> str:
    start_row = node.start_point.row
    if 0 <= start_row < len(lines):
        line = lines[start_row].strip()
        # strip trailing open brace
        return re.sub(r"\s*\{?\s*$", "", line)[:120]
    return ""


def _extract_csharp(
    root: Any, lines: list[str], source_bytes: bytes
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    syms: list[dict[str, Any]] = []
    refs: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    stack: list[str] = []
    curr_namespace = ""

    def visit(node: Any) -> None:
        nonlocal curr_namespace
        ntype = node.type

        if ntype == "using_directive":
            target = ""
            for c in node.children:
                if c.type in ("qualified_name", "identifier"):
                    target = _node_text(c, source_bytes)
                    break
            if not target:
                name_node = node.child_by_field_name("name")
                if name_node:
                    target = _node_text(name_node, source_bytes)
            if target:
                edges.append({
                    "src": "<module>",
                    "dst": target,
                    "kind": "imports",
                    "line": node.start_point.row + 1,
                })
            return

        if ntype == "namespace_declaration" or ntype == "file_scoped_namespace_declaration":
            ns_name_node = node.child_by_field_name("name")
            if ns_name_node:
                curr_namespace = _node_text(ns_name_node, source_bytes)
            for child in node.children:
                if child.type != "name":
                    visit(child)
            return

        is_type_decl = ntype in (
            "class_declaration", "interface_declaration", "struct_declaration",
            "enum_declaration", "record_declaration",
        )
        if is_type_decl:
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source_bytes) if name_node else ""
            if name:
                kind = ntype.replace("_declaration", "")
                container = "/".join(filter(None, [curr_namespace] + stack))
                name_path = f"{container}/{name}" if container else name
                sig = _first_line_sig(node, lines)

                # Inheritance
                base_list = next((c for c in node.children if c.type == "base_list"), None)
                if base_list:
                    base_str = _node_text(base_list, source_bytes).lstrip(":").strip()
                    for base_item in base_str.split(","):
                        bname = base_item.strip().split("<")[0].strip()
                        if bname:
                            edges.append({
                                "src": name_path,
                                "dst": bname,
                                "kind": "inherits",
                                "line": node.start_point.row + 1,
                            })

                syms.append({
                    "name": name,
                    "kind": kind,
                    "line": node.start_point.row + 1,
                    "end_line": node.end_point.row + 1,
                    "container": container,
                    "name_path": name_path,
                    "signature": sig,
                    "access": "public",
                    "docstring": "",
                })

                stack.append(name)
                for child in node.children:
                    visit(child)
                stack.pop()
                return

        if ntype in ("method_declaration", "constructor_declaration"):
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source_bytes) if name_node else ""
            if name:
                container = "/".join(filter(None, [curr_namespace] + stack))
                name_path = f"{container}/{name}" if container else name
                sig = _first_line_sig(node, lines)

                syms.append({
                    "name": name,
                    "kind": "method" if stack else "function",
                    "line": node.start_point.row + 1,
                    "end_line": node.end_point.row + 1,
                    "container": container,
                    "name_path": name_path,
                    "signature": sig,
                    "access": "public",
                    "docstring": "",
                })

        if ntype == "property_declaration":
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source_bytes) if name_node else ""
            if name:
                container = "/".join(filter(None, [curr_namespace] + stack))
                name_path = f"{container}/{name}" if container else name
                sig = _first_line_sig(node, lines)

                syms.append({
                    "name": name,
                    "kind": "property",
                    "line": node.start_point.row + 1,
                    "end_line": node.end_point.row + 1,
                    "container": container,
                    "name_path": name_path,
                    "signature": sig,
                    "access": "public",
                    "docstring": "",
                })

        if ntype == "invocation_expression":
            fn_node = node.child_by_field_name("function")
            if fn_node:
                fn_text = _node_text(fn_node, source_bytes)
                leaf_name = fn_text.split(".")[-1]
                if leaf_name and len(leaf_name) > 2 and leaf_name[0].isalpha():
                    refs.append({
                        "name": leaf_name,
                        "line": node.start_point.row + 1,
                        "kind": "call",
                    })

        for child in node.children:
            visit(child)

    visit(root)
    return syms, refs, edges


def _extract_js_ts(
    root: Any, lines: list[str], source_bytes: bytes
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    syms: list[dict[str, Any]] = []
    refs: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    stack: list[str] = []

    def visit(node: Any) -> None:
        ntype = node.type

        if ntype == "import_statement":
            src_node = node.child_by_field_name("source")
            if src_node:
                raw_src = _node_text(src_node, source_bytes).strip("'\"")
                edges.append({
                    "src": "<module>",
                    "dst": raw_src,
                    "kind": "imports",
                    "line": node.start_point.row + 1,
                })
            return

        if ntype in ("class_declaration", "interface_declaration", "type_alias_declaration"):
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source_bytes) if name_node else ""
            if name:
                kind = "class" if ntype == "class_declaration" else "interface" if ntype == "interface_declaration" else "type"
                container = "/".join(stack)
                name_path = f"{container}/{name}" if container else name
                sig = _first_line_sig(node, lines)

                # Inheritance
                heritage = next((c for c in node.children if c.type == "class_heritage"), None)
                if heritage:
                    heritage_str = _node_text(heritage, source_bytes)
                    for clause in re.split(r"\b(?:extends|implements)\b", heritage_str):
                        clause = clause.strip()
                        if clause:
                            for item in clause.split(","):
                                bname = item.strip().split("<")[0].strip()
                                if bname and bname[0].isalpha():
                                    edges.append({
                                        "src": name_path,
                                        "dst": bname,
                                        "kind": "inherits",
                                        "line": node.start_point.row + 1,
                                    })

                syms.append({
                    "name": name,
                    "kind": kind,
                    "line": node.start_point.row + 1,
                    "end_line": node.end_point.row + 1,
                    "container": container,
                    "name_path": name_path,
                    "signature": sig,
                    "access": "public",
                    "docstring": "",
                })

                stack.append(name)
                for child in node.children:
                    visit(child)
                stack.pop()
                return

        if ntype in ("function_declaration", "method_definition"):
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source_bytes) if name_node else ""
            if name:
                container = "/".join(stack)
                name_path = f"{container}/{name}" if container else name
                sig = _first_line_sig(node, lines)

                syms.append({
                    "name": name,
                    "kind": "method" if stack else "function",
                    "line": node.start_point.row + 1,
                    "end_line": node.end_point.row + 1,
                    "container": container,
                    "name_path": name_path,
                    "signature": sig,
                    "access": "public",
                    "docstring": "",
                })

        if ntype == "call_expression":
            fn_node = node.child_by_field_name("function")
            if fn_node:
                fn_text = _node_text(fn_node, source_bytes)
                leaf_name = fn_text.split(".")[-1]
                if leaf_name and len(leaf_name) > 1 and leaf_name[0].isalpha():
                    refs.append({
                        "name": leaf_name,
                        "line": node.start_point.row + 1,
                        "kind": "call",
                    })

        for child in node.children:
            visit(child)

    visit(root)
    return syms, refs, edges


def _extract_python(
    root: Any, lines: list[str], source_bytes: bytes
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    syms: list[dict[str, Any]] = []
    refs: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    stack: list[str] = []

    def visit(node: Any) -> None:
        ntype = node.type

        if ntype in ("import_statement", "import_from_statement"):
            txt = _node_text(node, source_bytes)
            dst = ""
            if ntype == "import_from_statement":
                mod_node = node.child_by_field_name("module_name")
                if mod_node:
                    dst = _node_text(mod_node, source_bytes)
            else:
                m = re.search(r"import\s+([\w.]+)", txt)
                if m:
                    dst = m.group(1)
            if dst:
                edges.append({
                    "src": "<module>",
                    "dst": dst,
                    "kind": "imports",
                    "line": node.start_point.row + 1,
                })
            return

        if ntype == "class_definition":
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source_bytes) if name_node else ""
            if name:
                container = "/".join(stack)
                name_path = f"{container}/{name}" if container else name
                sig = _first_line_sig(node, lines)

                # Inheritance
                arg_list = next((c for c in node.children if c.type == "argument_list"), None)
                if arg_list:
                    arg_str = _node_text(arg_list, source_bytes).strip("()")
                    for item in arg_str.split(","):
                        bname = item.strip().split("[")[0].strip()
                        if bname and bname[0].isalpha():
                            edges.append({
                                "src": name_path,
                                "dst": bname,
                                "kind": "inherits",
                                "line": node.start_point.row + 1,
                            })

                syms.append({
                    "name": name,
                    "kind": "class",
                    "line": node.start_point.row + 1,
                    "end_line": node.end_point.row + 1,
                    "container": container,
                    "name_path": name_path,
                    "signature": sig,
                    "access": "public" if not name.startswith("_") else "private",
                    "docstring": "",
                })

                stack.append(name)
                for child in node.children:
                    visit(child)
                stack.pop()
                return

        if ntype == "function_definition":
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source_bytes) if name_node else ""
            if name:
                container = "/".join(stack)
                name_path = f"{container}/{name}" if container else name
                sig = _first_line_sig(node, lines)

                syms.append({
                    "name": name,
                    "kind": "method" if stack else "function",
                    "line": node.start_point.row + 1,
                    "end_line": node.end_point.row + 1,
                    "container": container,
                    "name_path": name_path,
                    "signature": sig,
                    "access": "public" if not name.startswith("_") else "private",
                    "docstring": "",
                })

        if ntype == "call":
            fn_node = node.child_by_field_name("function")
            if fn_node:
                fn_text = _node_text(fn_node, source_bytes)
                leaf_name = fn_text.split(".")[-1]
                if leaf_name and len(leaf_name) > 1 and leaf_name[0].isalpha():
                    refs.append({
                        "name": leaf_name,
                        "line": node.start_point.row + 1,
                        "kind": "call",
                    })

        for child in node.children:
            visit(child)

    visit(root)
    return syms, refs, edges


def _extract_go(
    root: Any, lines: list[str], source_bytes: bytes
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    syms: list[dict[str, Any]] = []
    refs: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    curr_pkg = ""

    def visit(node: Any) -> None:
        nonlocal curr_pkg
        ntype = node.type

        if ntype == "package_clause":
            for c in node.children:
                if c.type == "package_identifier":
                    curr_pkg = _node_text(c, source_bytes)
            return

        if ntype == "import_declaration":
            for c in node.children:
                if c.type == "import_spec":
                    p_node = c.child_by_field_name("path")
                    if p_node:
                        p_text = _node_text(p_node, source_bytes).strip('"')
                        edges.append({
                            "src": "<module>",
                            "dst": p_text,
                            "kind": "imports",
                            "line": c.start_point.row + 1,
                        })
            return

        if ntype == "type_declaration":
            for c in node.children:
                if c.type == "type_spec":
                    name_node = c.child_by_field_name("name")
                    type_node = c.child_by_field_name("type")
                    name = _node_text(name_node, source_bytes) if name_node else ""
                    if name:
                        t_type = type_node.type if type_node else ""
                        kind = "struct" if "struct" in t_type else ("interface" if "interface" in t_type else "type")
                        name_path = f"{curr_pkg}/{name}" if curr_pkg else name
                        sig = _first_line_sig(c, lines)
                        syms.append({
                            "name": name,
                            "kind": kind,
                            "line": c.start_point.row + 1,
                            "end_line": c.end_point.row + 1,
                            "container": curr_pkg,
                            "name_path": name_path,
                            "signature": sig,
                            "access": "public" if name[0].isupper() else "private",
                            "docstring": "",
                        })
            return

        if ntype == "function_declaration":
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source_bytes) if name_node else ""
            if name:
                name_path = f"{curr_pkg}/{name}" if curr_pkg else name
                sig = _first_line_sig(node, lines)
                syms.append({
                    "name": name,
                    "kind": "function",
                    "line": node.start_point.row + 1,
                    "end_line": node.end_point.row + 1,
                    "container": curr_pkg,
                    "name_path": name_path,
                    "signature": sig,
                    "access": "public" if name[0].isupper() else "private",
                    "docstring": "",
                })

        if ntype == "method_declaration":
            name_node = node.child_by_field_name("name")
            recv_node = node.child_by_field_name("receiver")
            name = _node_text(name_node, source_bytes) if name_node else ""
            recv_text = _node_text(recv_node, source_bytes) if recv_node else ""
            recv_clean = re.sub(r"[()*& ]", "", recv_text).split()[-1] if recv_text else ""
            if name:
                container = f"{curr_pkg}/{recv_clean}" if (curr_pkg and recv_clean) else (recv_clean or curr_pkg)
                name_path = f"{container}/{name}" if container else name
                sig = _first_line_sig(node, lines)
                syms.append({
                    "name": name,
                    "kind": "method",
                    "line": node.start_point.row + 1,
                    "end_line": node.end_point.row + 1,
                    "container": container,
                    "name_path": name_path,
                    "signature": sig,
                    "access": "public" if name[0].isupper() else "private",
                    "docstring": "",
                })

        if ntype == "call_expression":
            fn_node = node.child_by_field_name("function")
            if fn_node:
                fn_text = _node_text(fn_node, source_bytes)
                leaf_name = fn_text.split(".")[-1]
                if leaf_name and len(leaf_name) > 1 and leaf_name[0].isalpha():
                    refs.append({
                        "name": leaf_name,
                        "line": node.start_point.row + 1,
                        "kind": "call",
                    })

        for child in node.children:
            visit(child)

    visit(root)
    return syms, refs, edges


def _extract_rust(
    root: Any, lines: list[str], source_bytes: bytes
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    syms: list[dict[str, Any]] = []
    refs: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    curr_impl = ""

    def visit(node: Any) -> None:
        nonlocal curr_impl
        ntype = node.type

        if ntype in ("struct_item", "enum_item", "trait_item", "type_item"):
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source_bytes) if name_node else ""
            if name:
                kind = "struct" if ntype == "struct_item" else ("enum" if ntype == "enum_item" else ("trait" if ntype == "trait_item" else "type"))
                sig = _first_line_sig(node, lines)
                syms.append({
                    "name": name,
                    "kind": kind,
                    "line": node.start_point.row + 1,
                    "end_line": node.end_point.row + 1,
                    "container": "",
                    "name_path": name,
                    "signature": sig,
                    "access": "public" if "pub" in sig.split()[:2] else "private",
                    "docstring": "",
                })

        if ntype == "impl_item":
            type_node = node.child_by_field_name("type")
            trait_node = node.child_by_field_name("trait")
            t_name = _node_text(type_node, source_bytes) if type_node else ""
            tr_name = _node_text(trait_node, source_bytes) if trait_node else ""
            if t_name and tr_name:
                edges.append({
                    "src": t_name,
                    "dst": tr_name,
                    "kind": "implements",
                    "line": node.start_point.row + 1,
                })
            old_impl = curr_impl
            curr_impl = t_name
            for child in node.children:
                visit(child)
            curr_impl = old_impl
            return

        if ntype == "function_item":
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source_bytes) if name_node else ""
            if name:
                container = curr_impl
                name_path = f"{container}::{name}" if container else name
                sig = _first_line_sig(node, lines)
                syms.append({
                    "name": name,
                    "kind": "method" if container else "function",
                    "line": node.start_point.row + 1,
                    "end_line": node.end_point.row + 1,
                    "container": container,
                    "name_path": name_path,
                    "signature": sig,
                    "access": "public" if "pub" in sig.split()[:2] else "private",
                    "docstring": "",
                })

        if ntype in ("call_expression", "macro_invocation"):
            fn_node = node.child_by_field_name("function") or node.child_by_field_name("macro")
            if fn_node:
                fn_text = _node_text(fn_node, source_bytes)
                leaf_name = fn_text.split("::")[-1].split(".")[-1].rstrip("!")
                if leaf_name and len(leaf_name) > 1 and leaf_name[0].isalpha():
                    refs.append({
                        "name": leaf_name,
                        "line": node.start_point.row + 1,
                        "kind": "call",
                    })

        for child in node.children:
            visit(child)

    visit(root)
    return syms, refs, edges

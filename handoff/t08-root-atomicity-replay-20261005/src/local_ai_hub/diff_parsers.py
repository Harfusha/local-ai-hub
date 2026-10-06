from __future__ import annotations

import ast
import re
from typing import Any


def extract_py_diff_defs(lines: list[str]) -> dict[str, dict[str, Any]]:
    """Extract Python function/class definitions from diff lines."""
    defs: dict[str, dict[str, Any]] = {}
    i = 0
    n = len(lines)
    while i < n:
        raw = lines[i]
        s = raw.strip()
        if s.startswith(("def ", "async def ", "class ")):
            stmt = s
            paren_count = stmt.count("(") - stmt.count(")")
            while paren_count > 0 and i + 1 < n:
                i += 1
                stmt += " " + lines[i].strip()
                paren_count = stmt.count("(") - stmt.count(")")
            try:
                to_parse = stmt
                if not to_parse.endswith(":"):
                    to_parse += ":"
                to_parse += "\n    pass"
                tree = ast.parse(to_parse)
                for node in tree.body:
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if node.name.startswith("_") and node.name not in ("__init__", "__call__", "__getitem__", "__enter__", "__exit__"):
                            continue
                        pos_args = [a.arg for a in node.args.args]
                        clean_args = [a for a in pos_args if a not in ("self", "cls")]
                        defaults_count = len(node.args.defaults)
                        req_total = len(pos_args) - defaults_count
                        clean_req = max(0, req_total - (1 if pos_args and pos_args[0] in ("self", "cls") else 0))
                        defs[node.name] = {
                            "name": node.name,
                            "kind": "function",
                            "pos_args": clean_args,
                            "required_count": clean_req,
                            "sig": stmt,
                        }
                    elif isinstance(node, ast.ClassDef):
                        if node.name.startswith("_"):
                            continue
                        defs[node.name] = {
                            "name": node.name,
                            "kind": "class",
                            "sig": stmt,
                        }
            except SyntaxError:
                pass
        i += 1
    return defs


def extract_ts_diff_defs(lines: list[str]) -> dict[str, dict[str, Any]]:
    """Extract TypeScript/JavaScript definitions from diff lines."""
    defs: dict[str, dict[str, Any]] = {}
    ts_pattern = re.compile(
        r"^\s*export\s+(?:default\s+)?(?:async\s+)?(function|class|interface|type|const|let|var)\s+([A-Za-z0-9_$]+)(?:\s*<.*?>)?(?:\s*\((.*?)\))?",
    )
    for raw in lines:
        line = raw.strip()
        m = ts_pattern.search(line)
        if m:
            kind = m.group(1)
            name = m.group(2)
            params_raw = m.group(3)
            if kind in ("let", "var"):
                continue
            d: dict[str, Any] = {"name": name, "kind": kind, "sig": line}
            if params_raw is not None and kind == "function":
                parts = []
                depth = 0
                cur = ""
                for ch in params_raw:
                    if ch in "({[<": depth += 1; cur += ch
                    elif ch in ")}]>": depth -= 1; cur += ch
                    elif ch == "," and depth == 0:
                        if cur.strip(): parts.append(cur.strip())
                        cur = ""
                    else: cur += ch
                if cur.strip(): parts.append(cur.strip())
                req_count = 0
                param_names = []
                for p in parts:
                    p_name = p.split(":")[0].strip()
                    is_opt = "?" in p_name or "=" in p
                    clean_p = p_name.rstrip("?").strip()
                    if not is_opt:
                        req_count += 1
                    param_names.append(clean_p)
                d["params"] = param_names
                d["required_count"] = req_count
            defs[name] = d
    return defs


def extract_cs_diff_defs(lines: list[str]) -> dict[str, dict[str, Any]]:
    """Extract C# class and method definitions from diff lines."""
    defs: dict[str, dict[str, Any]] = {}
    class_re = re.compile(r"^\s*public\s+(?:static\s+|sealed\s+|abstract\s+|partial\s+)*(class|interface|struct|record|enum)\s+([A-Za-z0-9_]+)")
    method_re = re.compile(r"^\s*public\s+(?:static\s+|virtual\s+|override\s+|async\s+|sealed\s+|abstract\s+)*([\w<>\[\],\s\?]+?)\s+([A-Za-z0-9_]+)\s*\((.*?)\)")
    for raw in lines:
        line = raw.strip()
        cm = class_re.search(line)
        if cm:
            defs[cm.group(2)] = {"name": cm.group(2), "kind": cm.group(1), "sig": line}
            continue
        mm = method_re.search(line)
        if mm:
            name, params_raw = mm.group(2), mm.group(3)
            parts = [p.strip() for p in params_raw.split(",") if p.strip()]
            req_count = sum(1 for p in parts if "=" not in p)
            defs[name] = {"name": name, "kind": "method", "required_count": req_count, "sig": line}
    return defs


def extract_go_diff_defs(lines: list[str]) -> dict[str, dict[str, Any]]:
    """Extract Go exported functions and types from diff lines."""
    defs: dict[str, dict[str, Any]] = {}
    func_re = re.compile(r"^\s*func\s+(?:\([^)]+\)\s+)?([A-Z][A-Za-z0-9_]*)\s*\((.*?)\)")
    type_re = re.compile(r"^\s*type\s+([A-Z][A-Za-z0-9_]*)\s+(struct|interface)")
    for raw in lines:
        line = raw.strip()
        fm = func_re.search(line)
        if fm:
            name = fm.group(1)
            defs[name] = {"name": name, "kind": "function", "sig": line}
            continue
        tm = type_re.search(line)
        if tm:
            name, kind = tm.group(1), tm.group(2)
            defs[name] = {"name": name, "kind": kind, "sig": line}
    return defs


def extract_rust_diff_defs(lines: list[str]) -> dict[str, dict[str, Any]]:
    """Extract Rust pub items from diff lines."""
    defs: dict[str, dict[str, Any]] = {}
    rust_re = re.compile(r"^\s*pub(?:\(.*?\))?\s+(fn|struct|enum|trait|type)\s+([A-Za-z0-9_]+)")
    for raw in lines:
        line = raw.strip()
        rm = rust_re.search(line)
        if rm:
            kind, name = rm.group(1), rm.group(2)
            defs[name] = {"name": name, "kind": kind, "sig": line}
    return defs

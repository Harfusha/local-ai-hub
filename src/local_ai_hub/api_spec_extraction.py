from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path
from typing import Any

from .api_spec_document import build_api_spec_document
from .code_index import _mask_non_code

_API_EXPRESS_ROUTER_METHOD = re.compile('\\b(?:app|router)\\.(get|post|put|patch|delete|options|head)\\s*\\(', re.I)
_API_NEXT_ROUTE_HANDLER = re.compile('^\\s*export\\s+(?:async\\s+)?function\\s+(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\\s*\\(', re.M)
_API_LARAVEL_ROUTE_METHOD = re.compile('\\bRoute::(get|post|put|patch|delete|options|any)\\s*\\(\\s*[\'\\"]([^\'\\"]+)[\'\\"]', re.I)
_API_LARAVEL_RESOURCE_ROUTE = re.compile('\\bRoute::(?:apiResource|resource)\\s*\\(\\s*[\'\\"]([^\'\\"]+)[\'\\"]', re.I)
_API_ATTRIBUTE_ROUTE_DECLARATION = re.compile('#\\[(?:Route|Get|Post|Put|Patch|Delete)\\s*(?:\\(\\s*[\'\\"]([^\'\\"]+)[\'\\"](?:[^)]*methods:\\s*\\[([^\\]]+)\\])?\\s*\\))?\\]', re.I)
_API_PHP_CONNECT_ROUTE = re.compile('\\$(?:builder|routes)->connect\\s*\\(\\s*[\'\\"]([^\'\\"]+)[\'\\"]', re.I)
_API_PHP_RESOURCE_ROUTE = re.compile('\\$(?:builder|routes)->resources\\s*\\(\\s*[\'\\"]([^\'\\"]+)[\'\\"]', re.I)
_API_HTML_FORM_ENDPOINT = re.compile('<form\\b(?=[^>]*\\baction=[\'\\"]([^\'\\"]+)[\'\\"])(?:[^>]*\\bmethod=[\'\\"]([A-Za-z]+)[\'\\"])?', re.I)


def extract_api_spec(
    root: str,
    framework: str | None = None,
    *,
    repo_tools: Any = None,
) -> dict[str, Any]:
    """Statically extract API routes and endpoints into OpenAPI 3.0 schema."""
    p_root = Path(root).expanduser().resolve(strict=False)
    skip_dirs = {
        str(name).casefold()
        for name in getattr(repo_tools, "ignore_dirs", ())
    }
    skip_dirs.update({".git", ".venv", "venv", "tool-envs", "node_modules", "__pycache__"})
    endpoints: list[dict[str, Any]] = []

    # Check for static openapi.json / swagger.json in root
    for spec_name in ("openapi.json", "swagger.json", "openapi.yaml", "openapi.yml"):
        spec_file = p_root / spec_name
        if spec_file.is_file():
            try:
                spec_data = json.loads(spec_file.read_text(encoding="utf-8"))
                paths_obj = spec_data.get("paths", {})
                for p_str, methods_obj in paths_obj.items():
                    if isinstance(methods_obj, dict):
                        for m_str, m_meta in methods_obj.items():
                            if m_str.lower() in {"get", "post", "put", "delete", "patch"}:
                                endpoints.append({
                                    "method": m_str.upper(),
                                    "path": p_str,
                                    "handler": m_meta.get("operationId", p_str) if isinstance(m_meta, dict) else p_str,
                                    "summary": m_meta.get("summary", "") if isinstance(m_meta, dict) else "",
                                    "description": m_meta.get("description", "") if isinstance(m_meta, dict) else "",
                                    "file": spec_name,
                                    "line": 1,
                                })
            except Exception:
                pass

    scan_patterns = ("*.py", "*.js", "*.ts", "*.mjs", "*.php", "*.ctp", "*.html", "*.htm")
    files_by_pattern: dict[str, list[Path]] = {pattern: [] for pattern in scan_patterns}
    authoritative_registry = p_root / "src" / "local_ai_hub" / "http_route_registry.py"
    registry_is_authoritative = False
    if authoritative_registry.is_file():
        try:
            registry_tree = ast.parse(
                authoritative_registry.read_text(encoding="utf-8", errors="replace"),
                filename=str(authoritative_registry),
            )
            registry_is_authoritative = any(
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name)
                    and target.id == "API_ROUTE_REGISTRIES_AUTHORITATIVE"
                    for target in node.targets
                )
                and isinstance(node.value, ast.Constant)
                and node.value.value is True
                for node in registry_tree.body
            )
        except (OSError, SyntaxError, UnicodeError):
            registry_is_authoritative = False

    if registry_is_authoritative:
        # This repository's canonical route registry is the same table the
        # HTTP server dispatches. Parse it directly instead of walking and
        # AST-parsing every test and tool file in the repository.
        files_by_pattern["*.py"].append(authoritative_registry)
    else:
        for current_root, dirnames, filenames in os.walk(p_root, topdown=True, followlinks=False):
            dirnames[:] = sorted(name for name in dirnames if name.casefold() not in skip_dirs)
            for filename in sorted(filenames):
                path = Path(current_root) / filename
                for pattern in scan_patterns:
                    if path.match(pattern):
                        files_by_pattern[pattern].append(path)
                        break

    for p in files_by_pattern["*.py"]:
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(content, filename=str(p))
        except Exception:
            continue

        for declaration in tree.body:
            if isinstance(declaration, ast.Assign):
                registry_names = [target.id for target in declaration.targets if isinstance(target, ast.Name)]
                registry_value = declaration.value
            elif isinstance(declaration, ast.AnnAssign) and isinstance(declaration.target, ast.Name):
                registry_names = [declaration.target.id]
                registry_value = declaration.value
            else:
                continue
            for registry_name in registry_names:
                suffix = "_ROUTE_REGISTRY"
                if not registry_name.endswith(suffix):
                    continue
                method = registry_name[:-len(suffix)]
                if method not in {"GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"}:
                    continue
                if not isinstance(registry_value, (ast.Tuple, ast.List)):
                    continue
                for rule in registry_value.elts:
                    if not (
                        isinstance(rule, ast.Call)
                        and isinstance(rule.func, ast.Name)
                        and rule.func.id == "RouteRule"
                        and len(rule.args) >= 2
                        and isinstance(rule.args[0], ast.Constant)
                        and isinstance(rule.args[0].value, str)
                    ):
                        continue
                    paths_node = rule.args[1]
                    if (
                        isinstance(paths_node, ast.Call)
                        and isinstance(paths_node.func, ast.Name)
                        and paths_node.func.id == "frozenset"
                        and len(paths_node.args) == 1
                    ):
                        paths_node = paths_node.args[0]
                    try:
                        route_paths = ast.literal_eval(paths_node)
                    except (TypeError, ValueError):
                        continue
                    if not isinstance(route_paths, (set, frozenset, tuple, list)):
                        continue
                    for route_path in route_paths:
                        if not isinstance(route_path, str) or not route_path:
                            continue
                        endpoints.append({
                            "method": method,
                            "path": route_path,
                            "handler": rule.args[0].value,
                            "summary": rule.args[0].value,
                            "description": "",
                            "file": str(p.relative_to(p_root) if p.is_relative_to(p_root) else p),
                            "line": rule.lineno,
                        })

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for dec in node.decorator_list:
                    route_path = None
                    method = "GET"
                    if isinstance(dec, ast.Call):
                        func = dec.func
                        if isinstance(func, ast.Attribute) and func.attr.lower() in {"get", "post", "put", "delete", "patch", "options", "head"}:
                            method = func.attr.upper()
                            if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                                route_path = dec.args[0].value
                        elif isinstance(func, ast.Attribute) and func.attr.lower() == "route":
                            if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                                route_path = dec.args[0].value
                            for kw in dec.keywords:
                                if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                                    m_list = [elt.value for elt in kw.value.elts if isinstance(elt, ast.Constant)]
                                    if m_list:
                                        method = m_list[0].upper()
                    if route_path:
                        doc = ast.get_docstring(node) or ""
                        endpoints.append({
                            "method": method,
                            "path": route_path,
                            "handler": node.name,
                            "summary": doc.splitlines()[0] if doc else node.name,
                            "description": doc,
                            "file": str(p.relative_to(p_root) if p.is_relative_to(p_root) else p),
                            "line": node.lineno,
                        })

    express_call_pat = _API_EXPRESS_ROUTER_METHOD
    next_route_pat = _API_NEXT_ROUTE_HANDLER
    for p in files_by_pattern["*.js"] + files_by_pattern["*.ts"] + files_by_pattern["*.mjs"]:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            scan_source = _mask_non_code(text, "typescript" if p.suffix.lower() == ".ts" else "javascript")
            for m in express_call_pat.finditer(scan_source):
                route_match = re.match(r"\s*(['\"])([^'\"\r\n]+)\1", text[m.end():])
                if not route_match:
                    continue
                method = m.group(1).upper()
                r_path = route_match.group(2)
                endpoints.append({
                    "method": method,
                    "path": r_path,
                    "handler": f"route_{method.lower()}",
                    "summary": f"{method} {r_path}",
                    "description": "",
                    "file": str(p.relative_to(p_root) if p.is_relative_to(p_root) else p),
                    "line": text[:m.start()].count("\n") + 1,
                })
            if p.stem.lower() == "route":
                for m in next_route_pat.finditer(scan_source):
                    method = m.group(1).upper()
                    rel_p = p.relative_to(p_root) if p.is_relative_to(p_root) else p
                    r_path = "/" + "/".join(part for part in rel_p.parts[:-1] if part not in {"app", "src", "api"})
                    if not r_path or r_path == "/":
                        r_path = "/api"
                    endpoints.append({
                        "method": method,
                        "path": r_path,
                        "handler": f"next_{method.lower()}",
                        "summary": f"{method} {r_path}",
                        "description": "",
                        "file": str(rel_p),
                        "line": text[:m.start()].count("\n") + 1,
                    })
        except Exception:
            continue

    php_route_pat = _API_LARAVEL_ROUTE_METHOD
    php_resource_pat = _API_LARAVEL_RESOURCE_ROUTE
    php_attr_route_pat = _API_ATTRIBUTE_ROUTE_DECLARATION
    cake_route_pat = _API_PHP_CONNECT_ROUTE
    cake_resource_pat = _API_PHP_RESOURCE_ROUTE

    for p in files_by_pattern["*.php"] + files_by_pattern["*.ctp"]:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            php_scan_source = _mask_non_code(text, "php")

            def is_php_code_match(match: re.Match[str]) -> bool:
                return bool(re.match(
                    r"(?:Route::|#\[(?:Route|Get|Post|Put|Patch|Delete)\b|\$(?:builder|routes)->)",
                    php_scan_source[match.start():], re.I,
                ))

            for m in php_route_pat.finditer(text):
                if not is_php_code_match(m):
                    continue
                method = m.group(1).upper()
                r_path = m.group(2)
                endpoints.append({
                    "method": method,
                    "path": r_path,
                    "handler": f"route_{method.lower()}",
                    "summary": f"{method} {r_path}",
                    "description": "",
                    "file": str(p.relative_to(p_root) if p.is_relative_to(p_root) else p),
                    "line": text[:m.start()].count("\n") + 1,
                })
            for m in php_resource_pat.finditer(text):
                if not is_php_code_match(m):
                    continue
                res_path = "/" + m.group(1).lstrip("/")
                endpoints.append({
                    "method": "RESOURCE",
                    "path": res_path,
                    "handler": "resource_controller",
                    "summary": f"RESOURCE {res_path}",
                    "description": "",
                    "file": str(p.relative_to(p_root) if p.is_relative_to(p_root) else p),
                    "line": text[:m.start()].count("\n") + 1,
                })
            for m in php_attr_route_pat.finditer(text):
                if not is_php_code_match(m):
                    continue
                r_path = m.group(1) or "/"
                methods_str = m.group(2) or "GET"
                for method_raw in methods_str.replace("'", "").replace('"', "").split(","):
                    method = method_raw.strip().upper() or "GET"
                    endpoints.append({
                        "method": method,
                        "path": r_path,
                        "handler": f"route_{method.lower()}",
                        "summary": f"{method} {r_path}",
                        "description": "",
                        "file": str(p.relative_to(p_root) if p.is_relative_to(p_root) else p),
                        "line": text[:m.start()].count("\n") + 1,
                    })
            for m in cake_route_pat.finditer(text):
                if not is_php_code_match(m):
                    continue
                r_path = m.group(1)
                endpoints.append({
                    "method": "ANY",
                    "path": r_path,
                    "handler": "cake_action",
                    "summary": f"CakePHP route {r_path}",
                    "description": "",
                    "file": str(p.relative_to(p_root) if p.is_relative_to(p_root) else p),
                    "line": text[:m.start()].count("\n") + 1,
                })
            for m in cake_resource_pat.finditer(text):
                if not is_php_code_match(m):
                    continue
                r_path = "/" + m.group(1).lstrip("/")
                endpoints.append({
                    "method": "RESOURCE",
                    "path": r_path,
                    "handler": "cake_resource",
                    "summary": f"CakePHP resource {r_path}",
                    "description": "",
                    "file": str(p.relative_to(p_root) if p.is_relative_to(p_root) else p),
                    "line": text[:m.start()].count("\n") + 1,
                })
        except Exception:
            continue

    form_pat = _API_HTML_FORM_ENDPOINT
    for p in files_by_pattern["*.html"] + files_by_pattern["*.htm"]:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            html_scan_source = re.sub(
                r"<!--[\s\S]*?-->",
                lambda match: "".join("\n" if char == "\n" else " " for char in match.group(0)),
                text,
            )
            for m in form_pat.finditer(html_scan_source):
                r_path = m.group(1)
                method = (m.group(2) or "GET").upper()
                endpoints.append({
                    "method": method,
                    "path": r_path,
                    "handler": "html_form",
                    "summary": f"HTML form {method} {r_path}",
                    "description": "",
                    "file": str(p.relative_to(p_root) if p.is_relative_to(p_root) else p),
                    "line": text[:m.start()].count("\n") + 1,
                })
        except Exception:
            continue

    return build_api_spec_document(p_root.name, endpoints)

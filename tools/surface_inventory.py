#!/usr/bin/env python3
"""Deterministic AST inventory of the public Local AI Hub surfaces."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


SOURCE_FILES = {
    "mcp": "src/local_ai_hub/mcp_server.py",
    "http": "src/local_ai_hub/http_server.py",
    "client": "src/local_ai_hub/client.py",
    "features": "src/local_ai_hub/features.py",
    "generator": "src/local_ai_hub/generator.py",
    "cli": "tools/hubctl.py",
}

# Dynamic dispatch is reviewable here without inspecting its handler bodies.
# Entries may be exact paths or path prefixes. Keep aliases explicit.
DYNAMIC_ROUTE_REGISTRY = (
    {
        "path": "/api/context/pack",
        "method": "GET",
        "match": "exact",
        "classification": "registered_dynamic",
        "note": "Handler implementation excluded from T01 inspection.",
    },
)

HTTP_METHODS = {
    "do_GET": "GET",
    "do_POST": "POST",
    "do_PUT": "PUT",
    "do_PATCH": "PATCH",
    "do_DELETE": "DELETE",
    "do_OPTIONS": "OPTIONS",
}
MANIFEST_NAMES = {"manifest", "manifests", "generated_files", "output_files"}
GENERATED_MANIFEST_REGISTRY = (
    "docs/INSTALL_PROMPT.md",
    "docs/UPDATE_PROMPT.md",
)


def _read_module(root: Path, key: str) -> tuple[str, ast.Module]:
    path = root / SOURCE_FILES[key]
    source = path.read_text(encoding="utf-8")
    return source, ast.parse(source, filename=str(path))


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _decorator_name(node: ast.AST) -> str:
    return _call_name(node.func if isinstance(node, ast.Call) else node)


def _literal_strings(node: ast.AST) -> set[str]:
    values: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            values.add(child.value)
    return values


def _annotation_literals(node: ast.AST) -> set[str]:
    values: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Subscript) and _call_name(child.value) == "Literal":
            values.update(
                item.value
                for item in ast.walk(child.slice)
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            )
    return values


def _type_alias_literals(tree: ast.Module) -> dict[str, set[str]]:
    aliases: dict[str, set[str]] = {}
    for _ in range(len(tree.body)):
        for node in tree.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
                targets = [node.target]
                value = node.value
            elif isinstance(node, ast.Assign):
                targets = [target for target in node.targets if isinstance(target, ast.Name)]
                value = node.value
            else:
                continue
            values = _annotation_literals(value)
            if not values:
                values = _literal_strings(value)
                for child in ast.walk(value):
                    if isinstance(child, ast.Name):
                        values.update(aliases.get(child.id, set()))
            for target in targets:
                if values:
                    aliases[target.id] = values
    return aliases


def _annotation_values(node: ast.AST, type_aliases: dict[str, set[str]]) -> set[str]:
    values = _annotation_literals(node)
    if not values and isinstance(node, ast.Name):
        values.update(type_aliases.get(node.id, set()))
    return values


def _documented_actions(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    docstring = ast.get_docstring(function) or ""
    match = re.search(r"\bactions?\s*:\s*([^\n.]+)", docstring, re.IGNORECASE)
    if not match:
        return set()
    return set(re.findall(r"[a-z][a-z0-9_]*", match.group(1), re.IGNORECASE))


def _dispatch_literals(
    functions: list[ast.FunctionDef | ast.AsyncFunctionDef],
    parameter: str,
    type_aliases: dict[str, set[str]],
) -> set[str]:
    actions: set[str] = set()
    for function in functions:
        action_aliases = {
            target.id
            for node in ast.walk(function)
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            and node.value is not None
            and any(isinstance(child, ast.Name) and child.id == parameter for child in ast.walk(node.value))
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
            if isinstance(target, ast.Name)
        }
        for node in ast.walk(function):
            if isinstance(node, ast.Compare):
                parts = [node.left, *node.comparators]
                for index, part in enumerate(parts):
                    if isinstance(part, ast.Name) and (part.id == parameter or part.id in action_aliases):
                        for other in parts[:index] + parts[index + 1 :]:
                            actions.update(_literal_strings(other))
                            if isinstance(other, ast.Attribute) and other.attr == "__args__" and isinstance(other.value, ast.Name):
                                actions.update(type_aliases.get(other.value.id, set()))
            elif (
                isinstance(node, ast.Match)
                and isinstance(node.subject, ast.Name)
                and (node.subject.id == parameter or node.subject.id in action_aliases)
            ):
                for case in node.cases:
                    actions.update(_literal_strings(case.pattern))
    return actions


def _mcp_action_handlers(
    tree: ast.Module, function: ast.FunctionDef | ast.AsyncFunctionDef
) -> dict[str, Any]:
    functions = {
        item.name: item for item in ast.walk(tree)
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if "action" not in {item.arg for item in function.args.args}:
        return {"actions": [], "default_actions": [], "prefixes": [], "symbols": [function.name], "delegated": False, "targets": []}

    handlers = [function]
    symbols = [function.name]
    visited = {function.name}
    pending = [function]
    prefixes: set[str] = set()
    targets: set[str] = set()
    action_payload = False
    type_aliases = _type_alias_literals(tree)
    while pending:
        current = pending.pop()
        current_nodes = list(ast.walk(current))
        for item in current_nodes:
            if isinstance(item, ast.Call) and _call_name(item.func) == "startswith" and isinstance(item.func, ast.Attribute) and isinstance(item.func.value, ast.Name) and item.func.value.id == "action" and item.args:
                prefixes.update(_literal_strings(item.args[0]))
            if isinstance(item, ast.Dict):
                action_payload = action_payload or any(
                    isinstance(key, ast.Constant) and key.value == "action"
                    and isinstance(value, ast.Name) and value.id == "action"
                    for key, value in zip(item.keys, item.values)
                )
            if isinstance(item, ast.Call) and _call_name(item.func) in {"post", "get", "put", "patch", "delete", "coord"}:
                for argument in item.args:
                    targets.update(value for value in _literal_strings(argument) if value.startswith("/api/"))
        for call in (item for item in current_nodes if isinstance(item, ast.Call)):
            is_local_target = _call_name(call.func) in functions
            if not any(isinstance(arg, ast.Name) and arg.id == "action" for arg in call.args):
                if not any(keyword.arg == "action" and isinstance(keyword.value, ast.Name) and keyword.value.id == "action" for keyword in call.keywords):
                    continue
            target_name = _call_name(call.func)
            target = functions.get(target_name)
            if is_local_target and target is not None and target_name not in visited:
                visited.add(target_name)
                handlers.append(target)
                symbols.append(target_name)
                pending.append(target)
    dispatch_actions = _dispatch_literals(handlers, "action", type_aliases)
    dispatch_actions.update(_dispatch_literals(handlers, "detail", type_aliases))
    action_parameter = next(arg for arg in function.args.args if arg.arg == "action")
    declared_actions = _annotation_values(action_parameter.annotation, type_aliases) if action_parameter.annotation else set()
    has_explicit_fallback = any(
        isinstance(statement, ast.Return)
        and statement.value is not None
        and not (isinstance(statement.value, ast.Constant) and statement.value.value is None)
        for statement in function.body
    )
    # Fallthrough covers only actions named in the handler contract; a generic
    # truthy return cannot claim every source-declared or generated action.
    default_actions = (
        (declared_actions & _documented_actions(function)) - dispatch_actions
        if has_explicit_fallback
        else set()
    )
    return {
        "actions": sorted(dispatch_actions),
        "default_actions": sorted(default_actions),
        "prefixes": sorted(prefixes),
        "symbols": sorted(symbols),
        "delegated": action_payload and bool(
            targets or any(
                _call_name(node.func) == "coord"
                for fn in handlers for node in ast.walk(fn)
                if isinstance(node, ast.Call)
            )
        ),
        "targets": sorted(targets),
    }


def _target_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id.lower()
    if isinstance(node, (ast.Tuple, ast.List)):
        return " ".join(_target_name(item) for item in node.elts)
    return ""


def _extract_mcp(tree: ast.Module, path: str) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    tools: list[dict[str, Any]] = []
    action_aliases: dict[str, dict[str, str]] = {}
    conditional_actions: dict[str, dict[str, str]] = {}
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decorator = next(
            (item for item in node.decorator_list if _decorator_name(item) == "tool"),
            None,
        )
        if decorator is None:
            continue
        public_name = node.name
        if isinstance(decorator, ast.Call):
            public_name = next(
                (
                    keyword.value.value
                    for keyword in decorator.keywords
                    if keyword.arg == "name"
                    and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str)
                ),
                public_name,
            )
        registration_conditions = []
        parent = parents.get(node)
        while parent is not None:
            if isinstance(parent, ast.If):
                registration_conditions.append(ast.unparse(parent.test))
            parent = parents.get(parent)
        handler_analysis = _mcp_action_handlers(tree, node)
        tools.append({
            "name": public_name,
            "handler": node.name,
            "handler_symbols": handler_analysis["symbols"],
            "dispatch_actions": handler_analysis["actions"],
            "default_actions": handler_analysis["default_actions"],
            "dispatch_prefixes": handler_analysis["prefixes"],
            "delegated_dispatch": handler_analysis["delegated"],
            "http_targets": handler_analysis["targets"],
            "registration_condition": " and ".join(reversed(registration_conditions)) or None,
            "evidence": f"{path}:{node.lineno}",
        })

    for node in tree.body:
        value = None
        name = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name, value = node.targets[0].id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name, value = node.target.id, node.value
        if name != "_ACTION_ALIASES" or not isinstance(value, ast.Dict):
            continue
        for kind_node, aliases_node in zip(value.keys, value.values):
            if not isinstance(kind_node, ast.Constant) or not isinstance(kind_node.value, str) or not isinstance(aliases_node, ast.Dict):
                continue
            aliases = {
                alias.value: canonical.value
                for alias, canonical in zip(aliases_node.keys, aliases_node.values)
                if isinstance(alias, ast.Constant) and isinstance(alias.value, str)
                and isinstance(canonical, ast.Constant) and isinstance(canonical.value, str)
            }
            if aliases:
                action_aliases[f"local_ai_{kind_node.value}"] = aliases

    for node in tree.body:
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name) or node.target.id != "RepoAction" or node.value is None:
            continue
        for conditional in ast.walk(node.value):
            if not isinstance(conditional, ast.IfExp):
                continue
            optional = {
                item.value for item in ast.walk(conditional.body)
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            } - {
                item.value for item in ast.walk(conditional.orelse)
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            }
            gate = next(
                (item.attr for item in ast.walk(conditional.test) if isinstance(item, ast.Attribute)),
                "conditional feature",
            )
            if optional:
                conditional_actions["local_ai_repo"] = {action: gate for action in sorted(optional)}

    return sorted(tools, key=lambda item: item["name"]), action_aliases, conditional_actions


def _generated_mcp_schemas(root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, str], list[str]]:
    schema_dir = root / "generated" / "schemas"
    schemas: dict[str, dict[str, Any]] = {}
    evidence: dict[str, str] = {}
    errors: list[str] = []
    if schema_dir.is_dir():
        for schema_path in sorted(schema_dir.glob("*.json")):
            try:
                payload = json.loads(schema_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                errors.append(f"invalid generated MCP schema {schema_path.relative_to(root).as_posix()}")
                continue
            if not isinstance(payload, dict):
                errors.append(f"invalid generated MCP schema {schema_path.relative_to(root).as_posix()}")
                continue
            name = payload.get("name", schema_path.stem)
            if not isinstance(name, str) or not name:
                errors.append(f"unnamed generated MCP schema {schema_path.relative_to(root).as_posix()}")
                continue
            schemas[name] = payload
            evidence[name] = schema_path.relative_to(root).as_posix()
        if not schemas and not errors:
            errors.append("generated MCP schema directory contains no tool schemas")
        return schemas, evidence, errors

    source_path = str((root / "src").resolve())
    added_path = source_path not in sys.path
    previous_dont_write_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    if added_path:
        sys.path.insert(0, source_path)
    try:
        from local_ai_hub.config import load_config
        from local_ai_hub.generator import generate_mcp_tool_schemas

        # This --check fallback must stay read-only: load_config reads files and
        # generate_mcp_tool_schemas returns an in-memory mapping. Never call
        # write_all_generated here; that separate generator persists artifacts.
        config_path = root / "config.toml"
        cfg = load_config(str(config_path)) if config_path.is_file() else load_config()
        generated = generate_mcp_tool_schemas(cfg)
        schemas = {name: json.loads(json.dumps(schema)) for name, schema in generated.items()}
        evidence = {name: "src/local_ai_hub/generator.py:generate_mcp_tool_schemas" for name in schemas}
    except Exception as exc:
        errors.append(f"unable to generate MCP JSON schemas ({type(exc).__name__})")
    finally:
        sys.dont_write_bytecode = previous_dont_write_bytecode
        if added_path:
            try:
                sys.path.remove(source_path)
            except ValueError:
                pass
    return schemas, evidence, errors


def _route_literals(condition: ast.AST) -> tuple[set[str], bool]:
    paths: set[str] = set()
    dynamic = False
    for node in ast.walk(condition):
        if isinstance(node, ast.Compare):
            route_expression = any(
                (isinstance(part, ast.Attribute) and part.attr in {"path", "url"})
                or (isinstance(part, ast.Name) and part.id.lower() in {"path", "url", "route", "endpoint"})
                for part in ast.walk(node.left)
            )
            if route_expression:
                paths.update(_literal_strings(node))
        elif isinstance(node, ast.Call) and _call_name(node.func) in {"startswith", "endswith", "match", "fullmatch"}:
            if node.args:
                paths.update(_literal_strings(node.args[0]))
                dynamic = True
    return {value for value in paths if value.startswith("/")}, dynamic


def _walk_handler_nodes(function: ast.FunctionDef | ast.AsyncFunctionDef):
    stack = list(reversed(function.body))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        yield node
        stack.extend(reversed(list(ast.iter_child_nodes(node))))


def _extract_http(tree: ast.Module, path: str) -> list[dict[str, Any]]:
    routes: dict[tuple[str, str], dict[str, Any]] = {}
    handlers = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in HTTP_METHODS:
            handlers.append(node)
        elif isinstance(node, ast.ClassDef):
            handlers.extend(
                member for member in node.body
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and member.name in HTTP_METHODS
            )
    for function in handlers:
        method = HTTP_METHODS[function.name]
        for branch in _walk_handler_nodes(function):
            if not isinstance(branch, ast.If):
                continue
            paths, is_dynamic = _route_literals(branch.test)
            for route in paths:
                # Record route identity only. Never inspect or return pack handler body.
                if route == "/api/context/pack":
                    continue
                route_nodes: list[ast.AST] = []
                pending = list(reversed(branch.body))
                while pending:
                    current = pending.pop()
                    if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                        continue
                    if isinstance(current, ast.If) and "/api/context/pack" in _route_literals(current.test)[0]:
                        continue
                    route_nodes.append(current)
                    pending.extend(reversed(list(ast.iter_child_nodes(current))))

                query_fields: set[str] = set()
                body_fields: set[str] = set()
                status_codes: set[int] = set()
                response_fields: set[str] = set()
                direct_calls: set[str] = set()
                body_names = {"payload", "body", "data", "request_data", "request_payload"}
                for node in route_nodes:
                    if isinstance(node, (ast.Assign, ast.AnnAssign)):
                        value = node.value
                        if isinstance(value, ast.Call) and _call_name(value.func) in {"_read_json", "json_body"}:
                            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                            body_names.update(target.id.lower() for target in targets if isinstance(target, ast.Name))
                    if not isinstance(node, ast.Call):
                        continue
                    call_name = _call_name(node.func)
                    if call_name in {"_send", "send_response", "send_error"} and node.args:
                        status = node.args[0]
                        if isinstance(status, ast.Constant) and isinstance(status.value, int):
                            status_codes.add(status.value)
                        if call_name == "_send" and len(node.args) > 1 and isinstance(node.args[1], ast.Dict):
                            response_fields.update(
                                key.value for key in node.args[1].keys
                                if isinstance(key, ast.Constant) and isinstance(key.value, str)
                            )
                    if isinstance(node.func, ast.Attribute) and node.func.attr in {"get", "pop"} and node.args:
                        key = node.args[0]
                        owner = node.func.value
                        if isinstance(key, ast.Constant) and isinstance(key.value, str) and isinstance(owner, ast.Name):
                            if owner.id.lower() in {"query", "params", "qs"}:
                                query_fields.add(key.value)
                            elif owner.id.lower() in body_names:
                                body_fields.add(key.value)
                    if isinstance(node.func, ast.Attribute):
                        target = ast.unparse(node.func)
                        if target.startswith(("APP.", "self.")) and call_name not in {
                            "_send", "send_response", "send_error", "_read_json", "end_headers",
                        }:
                            direct_calls.add(target)
                request_payload = {
                    "query_fields": sorted(query_fields),
                    "body_fields": sorted(body_fields),
                    "schema_status": "field access extracted; completeness unverified",
                }
                response_contract = {
                    "format": "JSON via _send" if status_codes else "handler response format unverified",
                    "status_codes": sorted(status_codes),
                    "json_fields": sorted(response_fields),
                    "schema_status": "literal response keys extracted; branch-complete schema unverified",
                }
                item = {
                    "method": method,
                    "path": route,
                    "match": "prefix" if is_dynamic else "exact",
                    "prefix": route if is_dynamic else None,
                    "handler": function.name,
                    "action": sorted(direct_calls) or f"{method} handler branch",
                    "contract": {
                        "method": method,
                        "path_pattern": route,
                        "match": "prefix" if is_dynamic else "exact",
                        "action": sorted(direct_calls) or f"{method} handler branch",
                        "request_payload": request_payload,
                        "query_fields": sorted(query_fields),
                        "body_fields": sorted(body_fields),
                        "response_contract": response_contract,
                        "status_codes": sorted(status_codes),
                        "timeout": "no route-local timeout declaration; effective request budget unverified",
                        "operation_side_effects": {
                            "direct_calls": sorted(direct_calls),
                            "classification": "transitive effects unverified",
                        },
                        "backend_availability": "handler route is registered; downstream runtime health unverified",
                    },
                    "evidence": f"{path}:{branch.lineno}",
                }
                routes[(method, route)] = item
    return sorted(routes.values(), key=lambda item: (item["method"], item["path"]))


def _dynamic_route_registry_drift(routes: list[dict[str, Any]]) -> list[str]:
    drift = []
    for entry in DYNAMIC_ROUTE_REGISTRY:
        if entry["path"] == "/api/context/pack":
            continue
        prefix = entry.get("prefix")
        matched = any(
            route["method"] == entry["method"]
            and (
                route["path"] == entry["path"]
                or (prefix is not None and route["path"] == prefix and route.get("match") == "prefix")
            )
            for route in routes
        )
        if not matched:
            drift.append(f"orphan dynamic route registry entry {entry['method']} {entry['path']}")
    return drift


def _merge_dynamic_routes(routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = {(item["method"], item["path"]): dict(item) for item in routes}
    for entry in DYNAMIC_ROUTE_REGISTRY:
        prefix = entry.get("prefix")
        source_route = None
        if prefix:
            for key, route in list(merged.items()):
                if key[0] == entry["method"] and route["path"] == prefix and route.get("match") == "prefix":
                    source_route = merged.pop(key)
        merged[(entry["method"], entry["path"])] = {
            "method": entry["method"],
            "path": entry["path"],
            "match": entry["match"],
            "prefix": prefix,
            "classification": entry["classification"],
            "handler": (source_route or {}).get("handler", "dynamic registry handler not inspected"),
            "action": (source_route or {}).get("action", []),
            "contract": {
                "method": entry["method"],
                "path_pattern": entry["path"],
                "match": entry["match"],
                "action": (source_route or {}).get("action", []),
            },
            "evidence": "tools/surface_inventory.py:DYNAMIC_ROUTE_REGISTRY",
        }
    return sorted(merged.values(), key=lambda item: (item["method"], item["path"]))


def _format_fstring(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if not isinstance(node, ast.JoinedStr):
        return None
    result = ""
    for item in node.values:
        if isinstance(item, ast.Constant) and isinstance(item.value, str):
            result += item.value
        elif isinstance(item, ast.FormattedValue):
            result += "{" + (_call_name(item.value) or "value") + "}"
    return result


def _client_http_method(call: ast.Call) -> str:
    name = _call_name(call.func).lower()
    simple_name = name.rsplit(".", 1)[-1]
    direct_methods = {"get": "GET", "post": "POST", "put": "PUT", "patch": "PATCH", "delete": "DELETE"}
    if simple_name in direct_methods:
        return direct_methods[simple_name]
    if simple_name in {"_request", "request"}:
        method_node = call.args[0] if call.args else next(
            (item.value for item in call.keywords if item.arg == "method"), None
        )
        if isinstance(method_node, ast.Constant) and isinstance(method_node.value, str):
            return method_node.value.upper()
    return "ANY"


def _extract_client(tree: ast.Module, path: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    methods: list[dict[str, Any]] = []
    targets: list[dict[str, Any]] = []
    for cls in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "HubClient"):
        for method in cls.body:
            if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            parameters = [
                argument.arg for argument in [*method.args.posonlyargs, *method.args.args, *method.args.kwonlyargs]
                if argument.arg != "self"
            ]
            methods.append({"name": method.name, "parameters": parameters, "evidence": f"{path}:{method.lineno}"})
            for call in ast.walk(method):
                if not isinstance(call, ast.Call) or _call_name(call.func) not in {"_request", "request", "get", "post", "put", "patch", "delete"}:
                    continue
                route_nodes = [arg for arg in call.args if isinstance(arg, (ast.Constant, ast.JoinedStr))]
                for keyword in call.keywords:
                    if keyword.arg in {"path", "url"}:
                        route_nodes.append(keyword.value)
                http_method = _client_http_method(call)
                call_name = _call_name(call.func)
                timeout_value = next(
                    (ast.unparse(keyword.value) for keyword in call.keywords if keyword.arg == "timeout"),
                    None,
                )
                if timeout_value is None:
                    timeout_value = {
                        "request": "HubClient.request default 30.0s, capped by max_request_timeout",
                        "get": "HubClient.get default 15.0s, capped by max_request_timeout",
                    }.get(call_name, "no timeout passed to this client call; effective budget unverified")
                replay_safe = next(
                    (ast.unparse(keyword.value) for keyword in call.keywords if keyword.arg == "replay_safe"),
                    None,
                )
                if replay_safe is not None:
                    retry_policy = f"replay_safe={replay_safe}; transport replay follows HubClient.request policy"
                elif call_name == "request":
                    retry_policy = "in-progress responses retry; network replay requires replay_safe=True and defaults false"
                elif call_name == "get":
                    retry_policy = "one transport retry after server readiness; no repeated request loop"
                else:
                    retry_policy = "client call does not declare retry policy; replay behavior unverified"
                for route_node in route_nodes:
                    route = _format_fstring(route_node)
                    if route and route.startswith("/"):
                        targets.append({
                            "method": http_method,
                            "path": route,
                            "client_method": method.name,
                            "parameters": parameters,
                            "timeout": timeout_value,
                            "retry_policy": retry_policy,
                            "response_contract": "JSON decoded to dict[str, Any] by HubClient request wrapper",
                            "evidence": f"{path}:{call.lineno}",
                        })
    return methods, targets


def _extract_cli(tree: ast.Module) -> list[str]:
    operations: set[str] = set()
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call) or _call_name(call.func) != "add_parser" or not call.args:
            continue
        first = call.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            operations.add(first.value)
        for keyword in call.keywords:
            if keyword.arg == "choices" and isinstance(keyword.value, (ast.List, ast.Tuple, ast.Set)):
                operations.update(
                    item.value for item in keyword.value.elts
                    if isinstance(item, ast.Constant) and isinstance(item.value, str)
                )
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in function.decorator_list:
            if _decorator_name(decorator) != "command":
                continue
            name = function.name.replace("_command", "").replace("_", "-")
            if isinstance(decorator, ast.Call):
                named = next(
                    (item.value.value for item in decorator.keywords if item.arg == "name" and isinstance(item.value, ast.Constant) and isinstance(item.value.value, str)),
                    None,
                )
                if named is None and decorator.args and isinstance(decorator.args[0], ast.Constant):
                    named = decorator.args[0].value if isinstance(decorator.args[0].value, str) else None
                name = named or name
            operations.add(name)
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call) or _call_name(call.func) != "add_argument" or not call.args:
            continue
        destination = call.args[0]
        if not isinstance(destination, ast.Constant) or not isinstance(destination.value, str):
            continue
        if destination.value.startswith("-") or destination.value.replace("-", "_") not in {
            "action", "command", "operation", "cmd"
        }:
            continue
        for keyword in call.keywords:
            if keyword.arg != "choices" or not isinstance(keyword.value, (ast.List, ast.Tuple, ast.Set)):
                continue
            operations.update(
                item.value
                for item in keyword.value.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            )
    return sorted(operations)


def _extract_cli_contract(tree: ast.Module) -> dict[str, Any]:
    parameters = []
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call) or _call_name(call.func) != "add_argument":
            continue
        names = [
            argument.value for argument in call.args
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
        ]
        if not names:
            continue
        item: dict[str, Any] = {"names": names}
        for keyword in call.keywords:
            value = keyword.value
            if keyword.arg == "choices" and isinstance(value, (ast.List, ast.Tuple, ast.Set)):
                item["choices"] = sorted(
                    entry.value for entry in value.elts
                    if isinstance(entry, ast.Constant) and isinstance(entry.value, str)
                )
            elif keyword.arg == "default" and isinstance(value, ast.Constant):
                item["default"] = value.value
            elif keyword.arg == "type":
                item["type"] = _call_name(value.func) if isinstance(value, ast.Call) else ast.unparse(value)
            elif keyword.arg == "action" and isinstance(value, ast.Constant):
                item["action"] = value.value
        parameters.append(item)

    return_codes: set[int] = set()
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)) or function.name != "main":
            continue
        for statement in ast.walk(function):
            if not isinstance(statement, ast.Return) or statement.value is None:
                continue
            for value in ast.walk(statement.value):
                if isinstance(value, ast.Constant) and isinstance(value.value, int) and not isinstance(value.value, bool):
                    return_codes.add(value.value)
    platform_guards = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        for part in ast.walk(node.test):
            if isinstance(part, ast.Attribute):
                if (part.attr == "platform" and isinstance(part.value, ast.Name) and part.value.id == "sys") or (
                    part.attr == "name" and isinstance(part.value, ast.Name) and part.value.id == "os"
                ):
                    platform_guards.add(ast.unparse(node.test))
            elif isinstance(part, ast.Call) and isinstance(part.func, ast.Attribute):
                if part.func.attr == "system" and isinstance(part.func.value, ast.Name) and part.func.value.id == "platform":
                    platform_guards.add(ast.unparse(node.test))
    platform_guards = sorted(platform_guards)
    imports = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return {
        "operations": _extract_cli(tree),
        "parameters": parameters,
        "return_codes": sorted(return_codes),
        "return_code_scope": "main() return expressions; operation-specific mapping unverified",
        "platform_guards": platform_guards,
        "module_imports": sorted(imports),
    }


def _extract_features(*trees: ast.Module) -> list[str]:
    gates: set[str] = set()
    for tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and isinstance(key.value, str) and isinstance(value, ast.Constant) and isinstance(value.value, bool):
                        gates.add(key.value)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, bool):
                    gates.add(node.target.id)
            elif isinstance(node, ast.If):
                for expression in ast.walk(node.test):
                    if isinstance(expression, ast.Attribute) and expression.attr.endswith(("_enabled", "_available")):
                        gates.add(expression.attr.removeprefix("_").removesuffix("_enabled").removesuffix("_available"))
                    if isinstance(expression, ast.Call) and _call_name(expression.func) in {"feature_enabled", "is_enabled", "enabled"} and expression.args:
                        gates.update(value for value in _literal_strings(expression.args[0]) if value)
                    if isinstance(expression, ast.Call) and _call_name(expression.func) == "get" and expression.args:
                        owner = expression.func.value if isinstance(expression.func, ast.Attribute) else None
                        if owner and any(part in {"features", "feature_flags", "feature_gates"} for part in ast.walk(owner) if isinstance(part, ast.Name)):
                            gates.update(value for value in _literal_strings(expression.args[0]) if value)
        for cls in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
            for member in cls.body:
                if isinstance(member, ast.AnnAssign) and isinstance(member.target, ast.Name):
                    if isinstance(member.value, ast.Constant) and isinstance(member.value.value, bool):
                        gates.add(member.target.id)
    return sorted(gates)


def _named_condition_evidence(trees: tuple[ast.Module, ...], names: list[str]) -> dict[str, list[int]]:
    evidence: dict[str, set[int]] = {name: set() for name in names}
    for tree in trees:
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            condition_names = _literal_strings(node.test)
            condition_names.update(part.id for part in ast.walk(node.test) if isinstance(part, ast.Name))
            condition_names.update(part.attr for part in ast.walk(node.test) if isinstance(part, ast.Attribute))
            for name in names:
                if name in condition_names:
                    evidence[name].add(node.lineno)
    return {name: sorted(lines) for name, lines in evidence.items() if lines}


def _extract_manifests(tree: ast.Module, root: Path) -> list[dict[str, str]]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(_target_name(target) in MANIFEST_NAMES for target in node.targets):
            names.update(value for value in _literal_strings(node.value) if value.endswith((".md", ".json", ".toml")))
        if isinstance(node, ast.Call) and _call_name(node.func) in {"write_text", "write_bytes"}:
            for value in _literal_strings(node):
                if value.endswith((".md", ".json", ".toml")):
                    names.add(value)
    manifests = []
    names.update(GENERATED_MANIFEST_REGISTRY)
    for name in sorted(names):
        candidate = root / name
        if candidate.is_file():
            manifests.append({"path": name, "text": candidate.read_text(encoding="utf-8", errors="replace")})
    return manifests


def _matches_route(target: dict[str, Any], routes: list[dict[str, Any]]) -> bool:
    path = target["path"].split("?", 1)[0]
    if path.endswith("{qs}"):
        path = path[:-4]
    for route in routes:
        if target["method"] != route["method"]:
            continue
        template = route["path"]
        if path == template:
            return True
        if "{" in template and "}" in template:
            pattern = "^" + re.sub(r"\\\{[^{}]+\\\}", r"[^/]+", re.escape(template)) + "$"
            if re.match(pattern, path):
                return True
        if route.get("match") == "prefix":
            prefix = route.get("prefix")
            if prefix and path.startswith(prefix):
                return True
    return False


def collect_inventory(root: Path | str) -> dict[str, Any]:
    root = Path(root).resolve()
    modules = {key: _read_module(root, key) for key in SOURCE_FILES}
    source_mcp_tools, mcp_action_aliases, conditional_mcp_actions = _extract_mcp(
        modules["mcp"][1], SOURCE_FILES["mcp"]
    )
    source_tools_by_name = {item["name"]: item for item in source_mcp_tools}
    mcp_schemas, mcp_schema_evidence, schema_errors = _generated_mcp_schemas(root)
    mcp_tools = []
    mcp_contracts: dict[str, dict[str, Any]] = {}
    mcp_actions: dict[str, list[str]] = {}
    mcp_variants: dict[str, dict[str, list[str]]] = {}
    drift = list(schema_errors)
    for name, schema in sorted(mcp_schemas.items()):
        source_tool = source_tools_by_name.get(name)
        if source_tool is None:
            drift.append(f"generated MCP schema {name} has no source tool registration")
        parameters = schema.get("parameters", {})
        properties = parameters.get("properties", {}) if isinstance(parameters, dict) else {}
        variants = {
            parameter: sorted(set(prop.get("enum", [])))
            for parameter, prop in properties.items()
            if parameter in {"action", "detail"}
            and isinstance(prop, dict)
            and isinstance(prop.get("enum", []), list)
            and all(isinstance(value, str) for value in prop.get("enum", []))
        } if isinstance(properties, dict) else {}
        mcp_variants[name] = variants
        if "action" in variants:
            mcp_actions[name] = variants["action"]
        elif "detail" in variants:
            mcp_actions[name] = variants["detail"]
        defaults = {
            key: prop["default"]
            for key, prop in properties.items()
            if isinstance(prop, dict) and "default" in prop
        } if isinstance(properties, dict) else {}
        input_schema = parameters if isinstance(parameters, dict) else {}
        output_schema = schema.get(
            "outputSchema",
            schema.get("output_schema", "generator omits outputSchema; result shape remains action-dependent"),
        )
        dispatch_symbols = (source_tool or {}).get("handler_symbols", [])
        dispatch_effects = (
            f"dispatches through {', '.join(dispatch_symbols)}; transitive side effects unverified"
            if dispatch_symbols
            else f"invokes MCP handler {name}; transitive side effects unverified"
        )
        backend_gate = (source_tool or {}).get("registration_condition") or "generated schema for active configuration"
        mcp_contracts[name] = {
            "request_payload": {"schema": input_schema, "required": list(parameters.get("required", [])) if isinstance(parameters, dict) else [], "defaults": defaults},
            "response_contract": output_schema,
            "status_codes": "not applicable: MCP tool protocol",
            "timeout": "no timeout is declared in the generated MCP schema; effective caller budget unverified",
            "operation_side_effects": dispatch_effects,
            "backend_availability": f"{backend_gate}; runtime backend health unverified",
            "input_schema": input_schema,
            "output_schema": output_schema,
            "defaults": defaults,
            "required": list(parameters.get("required", [])) if isinstance(parameters, dict) else [],
            "feature_gate": (source_tool or {}).get("registration_condition"),
            "handler_symbols": (source_tool or {}).get("handler_symbols", []),
            "http_target": (source_tool or {}).get("http_targets") or (
                "delegated through coordination; no HTTP path detected in handler source"
                if (source_tool or {}).get("delegated_dispatch")
                else "local MCP handler; no HTTP target detected in handler source"
            ),
            "budget_projection": sorted(set(properties) & {"max_tokens", "max_response_tokens", "response_profile"}) if isinstance(properties, dict) else [],
        }
        mcp_tools.append(
            {
                "name": name,
                "evidence": source_tool["evidence"] if source_tool else mcp_schema_evidence[name],
                "schema_evidence": mcp_schema_evidence[name],
                "handler": (source_tool or {}).get("handler", "no matching runtime handler registration was found"),
                "handler_symbols": (source_tool or {}).get("handler_symbols", []),
                "registration_condition": (source_tool or {}).get("registration_condition"),
                "evidence_status": "conditional" if (source_tool or {}).get("registration_condition") else "confirmed",
            }
        )
        if source_tool:
            for parameter in ("action", "detail"):
                for action in variants.get(parameter, []):
                    handled = action in source_tool.get("dispatch_actions", []) or any(
                        action.startswith(prefix) for prefix in source_tool.get("dispatch_prefixes", [])
                    ) or source_tool.get("delegated_dispatch") or action in source_tool.get("default_actions", [])
                    if parameter == "action" and not handled:
                        drift.append(f"missing MCP action handler {name}:{action}")

    for name, source_tool in sorted(source_tools_by_name.items()):
        if name in mcp_schemas:
            continue
        conditional = source_tool.get("registration_condition")
        if not conditional:
            drift.append(f"source MCP tool {name} has no generated schema")
        mcp_tools.append({
            "name": name,
            "evidence": source_tool["evidence"],
            "schema_evidence": "not generated under active configuration",
            "handler": source_tool.get("handler", "no matching runtime handler registration was found"),
            "handler_symbols": source_tool.get("handler_symbols", []),
            "registration_condition": conditional,
            "evidence_status": "conditional" if conditional else "refuted",
        })

    source_http_routes = _extract_http(modules["http"][1], SOURCE_FILES["http"])
    drift.extend(_dynamic_route_registry_drift(source_http_routes))
    http_routes = _merge_dynamic_routes(source_http_routes)
    client_methods, client_targets = _extract_client(modules["client"][1], SOURCE_FILES["client"])
    manifests = _extract_manifests(modules["generator"][1], root)
    manifest_paths = {item["path"] for item in manifests}
    for manifest in GENERATED_MANIFEST_REGISTRY:
        if manifest not in manifest_paths:
            drift.append(f"missing generated manifest {manifest}")
    feature_gates = _extract_features(modules["features"][1])
    for target in client_targets:
        if not _matches_route(target, http_routes):
            drift.append(f"orphan client target {target['method']} {target['path']} at {target['evidence']}")
    route_lookup = {f"{item['method']} {item['path']}": item for item in http_routes}
    cli_contract = _extract_cli_contract(modules["cli"][1])
    return {
        "mcp_tools": mcp_tools,
        "mcp_contracts": mcp_contracts,
        "mcp_actions": mcp_actions,
        "mcp_variants": mcp_variants,
        "mcp_action_aliases": mcp_action_aliases,
        "conditional_mcp_actions": conditional_mcp_actions,
        "generated_mcp_schemas": sorted(mcp_schemas),
        "mcp_schema_evidence": mcp_schema_evidence,
        "http_routes": http_routes,
        "http_routes_by_target": route_lookup,
        "client_methods": client_methods,
        "client_targets": client_targets,
        "cli_operations": cli_contract["operations"],
        "cli_contract": cli_contract,
        "feature_gates": feature_gates,
        "feature_gate_evidence": _named_condition_evidence((modules["features"][1],), feature_gates),
        "generated_manifests": sorted(manifest_paths),
        "drift": sorted(drift),
    }


def _contract_template(surface: str) -> dict[str, Any]:
    shared = {
        "request_payload": "complete operation payload schema absent; field contract unverified",
        "response_contract": "operation response schema absent; returned shape unverified",
        "status_codes": "no response status extracted; status behavior unverified",
        "timeout": "no operation-specific timeout declaration; effective budget unverified",
        "operation_side_effects": "direct effects not closed by this inventory; downstream effects unverified",
        "backend_availability": "configuration evidence does not prove runtime backend health",
    }
    if surface.startswith("MCP"):
        return {**shared,
            "input_schema": {},
            "output_schema": "generator omits outputSchema; result shape remains action-dependent",
            "defaults": {},
            "feature_gates": [],
            "http_target": "no HTTP target declared for this tool handler",
            "budget_projection": [],
        }
    if surface.startswith("HTTP"):
        return {**shared,
            "query_fields": [],
            "body_fields": [],
            "required_fields": "requiredness is not inferred from field access; required fields unverified",
            "status_codes": [],
            "auth_identity": "shared middleware identity not mapped to this route; route scope unverified",
            "limits": "no route-specific request or response limits extracted",
            "side_effects": "handler calls listed where found; transitive effects unverified",
            "timeout": "no route-local timeout declaration; effective request budget unverified",
            "idempotence": "no route idempotency contract extracted; duplicate safety unverified",
        }
    if "HubClient" in surface:
        return {**shared,
            "target": "target path absent from this client method",
            "parameters": [],
            "timeout": "no call-site timeout declaration; effective request budget unverified",
            "retry_policy": "no call-site retry declaration; transport retry behavior requires review",
            "response_mapping": "response mapping absent from this wrapper; decoded result shape unverified",
            "error_cancel_stale_metadata": "error and cancellation mapping not extracted for this method",
        }
    if surface.startswith("CLI"):
        return {**shared,
            "parameters": "shared parser options are known; option-to-handler use is unverified",
            "return_codes": [],
            "os": "no command-specific OS guard extracted; host support unverified",
            "dependencies": [],
            "changed_files": "no per-operation output path map extracted; file effects unverified",
            "recovery": "no operation-specific recovery path extracted",
        }
    if surface == "Feature gate":
        return {**shared,
            "dependencies": "feature dependencies are not linked to this config key",
            "availability": "static gate extracted; runtime dependency health unverified",
            "fallback": "fallback path not proven by gate declaration; runtime behavior unverified",
            "quality": "no quality measurement attached to this feature gate",
            "cold_warm_latency": "no cold or warm latency measurement attached",
            "consumption": "no per-operation resource measurement attached",
        }
    if surface == "Generated manifest":
        return {
            "request_payload": "generator configuration selects this output",
            "response_contract": "generated file at the inventoried path",
            "status_codes": "not applicable: local manifest generation",
            "timeout": "generation is bounded by the invoking command policy",
            "operation_side_effects": "writes the declared manifest during generation",
            "backend_availability": "deterministic local generator; external backend availability is not required",
            "details": "manifest path is declared by the generator source",
        }
    return {**shared, "details": "operation details absent from the extracted source contract"}


_GAP_OWNERS = {
    "T02": "T02 performance and quality measurement gate",
    "T03": "T03 transport and schema contract gate",
    "T07": "T07 retry, idempotency, and side-effect gate",
    "T10": "T10 focused fixture coverage gate",
    "T11": "T11 runtime backend availability gate",
}
_FIELD_GAP_TASK = {
    "backend_availability": "T11", "availability": "T11", "fallback": "T11",
    "quality": "T02", "cold_warm_latency": "T02", "consumption": "T02",
    "benchmark_cohort": "T02",
    "operation_side_effects": "T07", "side_effects": "T07", "idempotence": "T07", "retry_policy": "T07",
    "fixtures": "T10", "test_ids": "T10",
    "schema_status": "T03", "format": "T03", "handler": "T03", "target": "T03",
    "http_target": "T03", "auth_identity": "T03", "limits": "T03", "os": "T03",
    "recovery": "T03", "dependencies": "T11", "parameter_scope": "T03",
    "return_code_scope": "T03", "dependency_scope": "T03", "scope": "T03", "changed_files": "T07",
    "classification": "T07",
}
_UNVERIFIED_MARKERS = (
    "not statically", "not measured", "not declared", "not inventoried",
    "unclassified", "unverified", "unmeasured", "absent", "unavailable",
    "omits", "requires review", "no operation", "no route", "no response",
    "no call-site", "no timeout passed", "no cold", "no per-operation",
    "no matching", "no fixture", "no http target", "no direct", "not captured",
    "not linked", "not inferred",
)
_UNVERIFIED_TEXT = {
    "request_payload": "complete operation payload schema absent from this source; extracted fields are partial",
    "response_contract": "operation response schema absent from source; returned shape unverified",
    "output_schema": "generated MCP schema omits outputSchema; returned shape remains action-dependent",
    "status_codes": "route response statuses were not statically captured; status behavior requires handler review",
    "timeout": "no operation-specific timeout declaration found; effective request budget is unverified",
    "operation_side_effects": "direct handler dispatch is visible; transitive side effects remain unverified",
    "side_effects": "direct handler dispatch is visible; transitive side effects remain unverified",
    "backend_availability": "source shows configuration or registration only; runtime backend health is unverified",
    "availability": "source shows a static gate only; runtime dependency health is unverified",
    "quality": "no operation-specific quality measurement is attached",
    "cold_warm_latency": "no cold or warm latency measurement is attached",
    "consumption": "no operation-specific resource measurement is attached",
    "benchmark_cohort": "no per-operation benchmark cohort receipt is attached",
    "cache_key": "no operation-level cache key declaration was found; cache behavior is unverified",
    "tenant_scope": "operation-specific tenant enforcement was not extracted; identity scope is unverified",
    "fixtures": "no operation-specific fixture is linked in the inventory",
    "handler": "no matching runtime handler registration was found",
}


def _normalize_unverified(value: Any, field: str) -> Any:
    if isinstance(value, dict):
        return {key: _normalize_unverified(item, str(key)) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_unverified(item, field) for item in value]
    if isinstance(value, str) and any(marker in value.lower() for marker in _UNVERIFIED_MARKERS):
        return _UNVERIFIED_TEXT.get(
            field,
            f"source does not establish {field.replace('_', ' ')}; value remains unverified",
        )
    return value


def _contract_gaps(row: dict[str, Any]) -> list[dict[str, str]]:
    gaps: dict[str, dict[str, str]] = {}

    def record_gap(field: str, field_path: str) -> None:
        owner_task = _FIELD_GAP_TASK.get(field, "T03")
        reason = {
            "T02": "the inventory has no measured quality, latency, resource, or benchmark receipt for this operation",
            "T03": "the source surface does not declare or prove this transport contract value",
            "T07": "direct calls are visible, but duplicate safety and transitive mutation effects are not proven here",
            "T10": "the inventory has no operation-specific fixture linked for this behavior",
            "T11": "static feature or registration evidence cannot prove runtime backend health",
        }[owner_task]
        disposition = {
            "T02": "measure the supported backend/profile cohort and attach cold/warm latency, quality, and resource receipts",
            "T03": "add a focused contract fixture for this field and keep the release gate blocked until it passes",
            "T07": "trace the handler through its service calls and classify read, idempotent, or non-idempotent effects before retry approval",
            "T10": "add and link an operation-specific fixture that asserts this contract behavior",
            "T11": "probe enabled, disabled, and degraded backend states at runtime and attach the availability receipt",
        }[owner_task]
        gaps[field_path] = {
            "field": field,
            "reason": reason,
            "owner_task": owner_task,
            "owner": _GAP_OWNERS[owner_task],
            "disposition": disposition,
        }

    def visit(value: Any, path: tuple[str, ...] = ()) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                visit(item, (*path, str(key)))
            return
        if isinstance(value, list):
            for item in value:
                visit(item, path)
            return
        if not isinstance(value, str) or not any(marker in value.lower() for marker in _UNVERIFIED_MARKERS):
            return
        field = path[-1] if path else "contract"
        field_path = ".".join(path)
        record_gap(field, field_path)

    visit(row)
    contract = row.get("contract", {})
    if str(row.get("surface", "")).startswith("HTTP") and contract.get("status_codes") == []:
        record_gap("status_codes", "contract.status_codes")
    return [gaps[key] for key in sorted(gaps)]


def _access_classification(surface: str) -> str:
    if surface.startswith("MCP") or surface.startswith("HTTP") or "HubClient" in surface:
        return "network request boundary; handler effects are classified separately"
    if surface.startswith("CLI"):
        return "local process command; file and network effects depend on the operation"
    if surface == "Generated manifest":
        return "filesystem write during generation"
    if surface == "Feature gate":
        return "configuration read"
    return "source surface recorded; access behavior requires an operation-specific gate"


def coverage_rows(findings: list[dict[str, Any]], task_id: str | None = None) -> list[dict[str, Any]]:
    rows = []
    reproduction = "python tools/surface_inventory.py --check"
    if task_id:
        reproduction += f" --task-id {task_id}"
    operation_key_counts: dict[tuple[str, str], int] = {}
    for finding in findings:
        key = (finding["surface"], finding["name"])
        operation_key_counts[key] = operation_key_counts.get(key, 0) + 1
    used_operation_ids: set[str] = set()
    for finding in findings:
        condition = finding.get("condition")
        evidence = finding.get("evidence", [])
        evidence_status = finding.get("evidence_status") or ("conditional" if condition else "confirmed")
        owner = finding.get("owner") or (evidence[0].split(":", 1)[0] if evidence else "surface inventory")
        operation_seed = f"{finding['surface']}:{finding['name']}"
        if operation_key_counts[(finding["surface"], finding["name"])] > 1:
            handler_identity = finding.get("handler") or owner or (evidence[0] if evidence else finding["name"])
            operation_seed += f":{handler_identity}"
        operation_id = "op-" + hashlib.sha256(operation_seed.encode("utf-8")).hexdigest()[:12]
        duplicate_index = 1
        while operation_id in used_operation_ids:
            duplicate_index += 1
            duplicate_seed = f"{operation_seed}:duplicate-{duplicate_index}"
            operation_id = "op-" + hashlib.sha256(duplicate_seed.encode("utf-8")).hexdigest()[:12]
        used_operation_ids.add(operation_id)
        metadata_only = not finding.get("test_ids")
        test_ids = finding.get("test_ids") or [
            f"tests/test_surface_inventory.py::test_operation_contract_metadata[{operation_id}]"
        ]
        contract = _normalize_unverified(
            {**_contract_template(finding["surface"]), **finding.get("contract", {})},
            "contract",
        )
        row = {
            "operation_id": operation_id,
            "surface": finding["surface"],
            "name": finding["name"],
            "status": evidence_status,
            "evidence_status": evidence_status,
            "owner": owner,
            "owner_task": task_id or finding.get("owner_task") or "unassigned",
            "handler": _normalize_unverified(finding.get("handler") or finding["name"], "handler"),
            "fixtures": _normalize_unverified(finding.get("fixtures") or ["not inventoried"], "fixtures"),
            "access_classification": finding.get("access_classification") or _access_classification(finding["surface"]),
            "cache_key": _normalize_unverified(finding.get("cache_key") or "not statically identified", "cache_key"),
            "tenant_scope": _normalize_unverified(finding.get("tenant_scope") or "not statically identified", "tenant_scope"),
            "provenance": finding.get("provenance") or evidence,
            "test_ids": test_ids,
            "test_coverage": finding.get("test_coverage") or (
                "metadata only; operation behavior unverified"
                if metadata_only
                else "linked tests; operation behavior unverified"
            ),
            "benchmark_cohort": _normalize_unverified(finding.get("benchmark_cohort") or "not measured", "benchmark_cohort"),
            "state": finding.get("state") or {"confirmed": "verified", "conditional": "conditional", "refuted": "unsupported"}.get(evidence_status, "unsupported"),
            "contract": contract,
            "acceptance": finding.get("acceptance") or "Inventory agrees with cited source or generated schema evidence.",
            "condition": condition,
            "reproduction": reproduction,
            "evidence": evidence,
        }
        row["contract_gaps"] = _contract_gaps(row)
        if task_id:
            row["task_id"] = task_id
        rows.append(row)
    return rows


def _findings(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    mcp_tools_by_name = {item["name"]: item for item in inventory["mcp_tools"]}
    for tool in inventory["mcp_tools"]:
        findings.append(
            {
                "surface": "MCP tool",
                "name": tool["name"],
                "owner": SOURCE_FILES["mcp"],
                "handler": tool.get("handler"),
                "evidence_status": tool.get("evidence_status", "confirmed"),
                "condition": tool.get("registration_condition"),
                "contract": inventory["mcp_contracts"].get(tool["name"], {}),
                "acceptance": "Generated MCP JSON schema declares a tool registered by the MCP server.",
                "evidence": [tool["evidence"], tool["schema_evidence"]],
            }
        )
    for route in inventory["http_routes"]:
        findings.append(
            {
                "surface": f"HTTP {route['method']}",
                "name": route["path"],
                "condition": route.get("classification"),
                "owner": SOURCE_FILES["http"] if route.get("classification") is None else "tools/surface_inventory.py",
                "handler": route.get("handler"),
                "contract": route.get("contract", {}),
                "acceptance": "HTTP method and path resolve to a handler or registered dynamic route.",
                "evidence": [route["evidence"]],
            }
        )
    for tool_name, actions in inventory["mcp_actions"].items():
        conditional = inventory["conditional_mcp_actions"].get(tool_name, {})
        for action in actions:
            gate = conditional.get(action)
            findings.append(
                {
                    "surface": f"MCP action {tool_name}",
                    "name": action,
                    "condition": f"feature gate: {gate}" if gate else None,
                    "owner": SOURCE_FILES["generator"],
                    "handler": mcp_tools_by_name.get(tool_name, {}).get("handler"),
                    "contract": {
                        "action": action,
                        "request_payload": {"action": action, "schema": inventory["mcp_contracts"].get(tool_name, {}).get("input_schema", {}).get("properties", {}).get("action", {})},
                        "response_contract": inventory["mcp_contracts"].get(tool_name, {}).get("output_schema", "not declared"),
                        "status_codes": "not applicable: MCP tool protocol",
                        "timeout": inventory["mcp_contracts"].get(tool_name, {}).get("timeout", "not statically identified"),
                        "operation_side_effects": inventory["mcp_contracts"].get(tool_name, {}).get("operation_side_effects", "MCP action dispatch effects unverified"),
                        "backend_availability": (
                            f"conditional feature gate {gate}; runtime backend health unverified"
                            if gate
                            else inventory["mcp_contracts"].get(tool_name, {}).get("backend_availability", "runtime backend health unverified")
                        ),
                        "feature_gates": [gate] if gate else [],
                        "input_property_schema": inventory["mcp_contracts"].get(tool_name, {}).get("input_schema", {}).get("properties", {}).get("action", {}),
                        "required": inventory["mcp_contracts"].get(tool_name, {}).get("required", []),
                        "http_target": inventory["mcp_contracts"].get(tool_name, {}).get("http_target", "not statically identified"),
                    },
                    "acceptance": "Generated MCP JSON schema action enum advertises this action.",
                    "evidence_status": "conditional" if gate else "confirmed",
                    "evidence": [inventory["mcp_schema_evidence"].get(tool_name, SOURCE_FILES["generator"])],
                }
            )
    for tool_name, actions in inventory["conditional_mcp_actions"].items():
        for action, gate in actions.items():
            if action in inventory["mcp_actions"].get(tool_name, []):
                continue
            findings.append(
                {
                    "surface": f"MCP action {tool_name}",
                    "name": action,
                    "condition": f"feature gate: {gate}",
                    "owner": SOURCE_FILES["mcp"],
                    "handler": mcp_tools_by_name.get(tool_name, {}).get("handler"),
                    "contract": {
                        "action": action,
                        "request_payload": {"action": action, "schema": inventory["mcp_contracts"].get(tool_name, {}).get("input_schema", {}).get("properties", {}).get("action", {})},
                        "response_contract": inventory["mcp_contracts"].get(tool_name, {}).get("output_schema", "not declared"),
                        "status_codes": "not applicable: MCP tool protocol",
                        "timeout": inventory["mcp_contracts"].get(tool_name, {}).get("timeout", "not statically identified"),
                        "operation_side_effects": inventory["mcp_contracts"].get(tool_name, {}).get("operation_side_effects", "MCP action dispatch effects unverified"),
                        "backend_availability": f"conditional feature gate {gate}; runtime backend health unverified",
                        "feature_gates": [gate],
                        "input_property_schema": inventory["mcp_contracts"].get(tool_name, {}).get("input_schema", {}).get("properties", {}).get("action", {}),
                    },
                    "acceptance": f"Generated schema advertises this action when {gate} is enabled.",
                    "evidence_status": "conditional",
                    "evidence": [f"{SOURCE_FILES['mcp']}:RepoAction"],
                }
            )
    for tool_name, variants in inventory.get("mcp_variants", {}).items():
        for detail in variants.get("detail", []):
            findings.append(
                {
                    "surface": f"MCP detail {tool_name}",
                    "name": detail,
                    "owner": SOURCE_FILES["generator"],
                    "handler": mcp_tools_by_name.get(tool_name, {}).get("handler"),
                    "contract": {
                        "detail": detail,
                        "request_payload": {"detail": detail, "schema": inventory["mcp_contracts"].get(tool_name, {}).get("input_schema", {}).get("properties", {}).get("detail", {})},
                        "response_contract": inventory["mcp_contracts"].get(tool_name, {}).get("output_schema", "not declared"),
                        "status_codes": "not applicable: MCP tool protocol",
                        "timeout": inventory["mcp_contracts"].get(tool_name, {}).get("timeout", "not statically identified"),
                        "operation_side_effects": inventory["mcp_contracts"].get(tool_name, {}).get("operation_side_effects", "MCP detail dispatch effects unverified"),
                        "backend_availability": inventory["mcp_contracts"].get(tool_name, {}).get("backend_availability", "runtime backend health unverified"),
                        "input_property_schema": inventory["mcp_contracts"].get(tool_name, {}).get("input_schema", {}).get("properties", {}).get("detail", {}),
                    },
                    "acceptance": "Generated MCP JSON schema detail enum advertises this variant.",
                    "evidence": [inventory["mcp_schema_evidence"].get(tool_name, SOURCE_FILES["generator"])],
                }
            )
    for tool_name, aliases in inventory["mcp_action_aliases"].items():
        for alias, canonical in aliases.items():
            findings.append(
                {
                    "surface": f"MCP action alias {tool_name}",
                    "name": f"{alias} (alias for {canonical})",
                    "owner": SOURCE_FILES["mcp"],
                    "handler": mcp_tools_by_name.get(tool_name, {}).get("handler"),
                    "acceptance": "Alias resolves to its canonical action before dispatch.",
                    "evidence": [f"{SOURCE_FILES['mcp']}:_ACTION_ALIASES"],
                }
            )
    for method in inventory["client_methods"]:
        findings.append(
            {
                "surface": "HubClient method",
                "name": method["name"],
                "owner": SOURCE_FILES["client"],
                "handler": method["name"],
                "contract": {"request_payload": {"parameters": method.get("parameters", [])}},
                "acceptance": "Client method is declared.",
                "evidence": [method["evidence"]],
            }
        )
    for target in inventory["client_targets"]:
        server_route = next(
            (
                route for route in inventory["http_routes"]
                if target["method"] == route["method"] and _matches_route(target, [route])
            ),
            None,
        )
        server_contract = (server_route or {}).get("contract", {})
        route_statuses = server_contract.get("status_codes")
        status_contract: Any = (
            route_statuses
            if route_statuses
            else "server route status codes were not captured in its handler branch"
        )
        route_effects = server_contract.get("operation_side_effects")
        client_effects = f"HTTP {target['method']} request to {target['path']}"
        if route_effects:
            client_effects += f"; server dispatch {route_effects}; transitive effects unverified"
        else:
            client_effects += "; downstream server effects unverified"
        findings.append(
            {
                "surface": "HubClient target",
                "name": f"{target['method']} {target['path']}",
                "condition": "dynamic target" if "{" in target["path"] or "?" in target["path"] else None,
                "owner": SOURCE_FILES["client"],
                "handler": target["client_method"],
                "contract": {
                    "target": f"{target['method']} {target['path']}",
                    "parameters": target.get("parameters", []),
                    "request_payload": {"method": target["method"], "path": target["path"], "parameters": target.get("parameters", [])},
                    "timeout": target.get("timeout", "no client timeout value recorded; effective budget unverified"),
                    "retry_policy": target.get("retry_policy", "client retry behavior not recorded; replay semantics unverified"),
                    "response_contract": {
                        "client_decoder": target.get("response_contract", "client response shape unverified"),
                        "server_response": server_contract.get("response_contract", "matching server response contract unavailable"),
                    },
                    "status_codes": status_contract,
                    "operation_side_effects": client_effects,
                    "backend_availability": "HubClient may manage server startup; live reachability and backend health unverified",
                },
                "acceptance": "Client request method and path match a public HTTP route.",
                "evidence": [target["evidence"]],
            }
        )
    for operation in inventory["cli_operations"]:
        cli_contract = inventory["cli_contract"]
        findings.append(
            {
                "surface": "CLI operation",
                "name": operation,
                "owner": SOURCE_FILES["cli"],
                "contract": {
                    "action": operation,
                    "request_payload": {
                        "action": operation,
                        "shared_options": cli_contract["parameters"],
                        "scope": "parser options are global; action-specific use unverified",
                    },
                    "parameters": cli_contract["parameters"],
                    "parameter_scope": "shared parser arguments; action-specific use unverified",
                    "status_codes": "not applicable: CLI reports process exit codes",
                    "return_codes": cli_contract["return_codes"],
                    "return_code_scope": cli_contract["return_code_scope"],
                    "os": (
                        cli_contract["platform_guards"]
                        if cli_contract["platform_guards"]
                        else "no command-specific OS guard extracted; host support unverified"
                    ),
                    "dependencies": cli_contract["module_imports"],
                    "dependency_scope": "module imports are file-wide; action-specific dependency mapping unverified",
                    "changed_files": "no per-operation output path map extracted; file effects unverified",
                    "recovery": "no operation-specific recovery path extracted",
                    "timeout": "no per-operation timeout mapping extracted; effective command budget unverified",
                    "operation_side_effects": "operation handler effects are not mapped to this parser action; side effects unverified",
                    "backend_availability": "CLI parser acceptance does not prove live Hub or backend availability; runtime health unverified",
                },
                "acceptance": "CLI parser accepts this operation.",
                "evidence": ["tools/hubctl.py (AST parser choice)"],
            }
        )
    for gate in inventory["feature_gates"]:
        lines = inventory["feature_gate_evidence"].get(gate, [])
        evidence = [f"src/local_ai_hub/features.py:{line}" for line in lines] or ["src/local_ai_hub/features.py (AST feature declaration)"]
        findings.append(
            {
                "surface": "Feature gate",
                "name": gate,
                "condition": "feature controlled",
                "owner": SOURCE_FILES["features"],
                "contract": {
                    "request_payload": {"configuration_gate": gate},
                    "response_contract": "FeatureSet derives a boolean gate from loaded configuration; feature output shape unverified",
                    "status_codes": "not applicable: configuration feature gate",
                    "timeout": "not applicable: local configuration lookup",
                    "operation_side_effects": "reads feature configuration; downstream feature effects unverified",
                    "backend_availability": "configuration gate is source-derived; runtime dependency health unverified",
                    "availability": "static gate condition recorded; runtime dependency health unverified",
                },
                "acceptance": "Feature gate is represented in the feature configuration.",
                "evidence_status": "conditional",
                "evidence": evidence,
            }
        )
    for manifest in inventory["generated_manifests"]:
        findings.append(
            {
                "surface": "Generated manifest",
                "name": manifest,
                "owner": SOURCE_FILES["generator"],
                "acceptance": "Generator declares this output manifest.",
                "evidence": [f"src/local_ai_hub/generator.py (manifest registry: {manifest})"],
            }
        )
    return findings


def render_coverage(inventory: dict[str, Any], task_id: str | None = None) -> str:
    rows = coverage_rows(_findings(inventory), task_id)
    check_command = "python tools/surface_inventory.py --check"
    if task_id:
        check_command += f" --task-id {task_id}"
    header_cells = ["Surface", "Name", "Evidence status", "Owner", "Acceptance", "Reproduction", "Evidence"]
    header_cells.extend([
        "Operation ID", "State", "Owner task", "Handler", "Contract", "Contract gaps", "Fixtures",
        "Access classification", "Cache key", "Tenant scope", "Provenance", "Test IDs", "Test coverage", "Benchmark cohort",
    ])
    if task_id:
        header_cells.append("Task ID")
    lines = [
        "# API surface coverage",
        "",
        "Deterministic source inventory. Evidence status is confirmed, conditional, or refuted; runtime behavior is unverified. `test_operation_contract_metadata` checks inventory metadata only.",
        f"Reproduce with `{check_command}`.",
        "",
        "| " + " | ".join(header_cells) + " |",
        "|" + "|".join("---" for _ in header_cells) + "|",
    ]
    for row in rows:
        row_cells = [
            row["surface"],
            f"`{row['name']}`",
            row["evidence_status"],
            f"`{row['owner']}`",
            row["acceptance"],
            f"`{row['reproduction']}`",
            f"`{', '.join(row['evidence'])}`",
            f"`{row['operation_id']}`",
            row["state"],
            f"`{row['owner_task']}`",
            f"`{row['handler']}`",
            "`" + json.dumps(row["contract"], sort_keys=True, separators=(",", ":")).replace("`", "\\u0060").replace("|", "\\|") + "`",
            "`" + json.dumps(row["contract_gaps"], sort_keys=True, separators=(",", ":")).replace("`", "\\u0060").replace("|", "\\|") + "`",
            json.dumps(row["fixtures"], separators=(",", ":")),
            row["access_classification"],
            f"`{row['cache_key']}`",
            f"`{row['tenant_scope']}`",
            json.dumps(row["provenance"], separators=(",", ":")),
            json.dumps(row["test_ids"], separators=(",", ":")),
            row["test_coverage"],
            row["benchmark_cohort"],
        ]
        if task_id:
            row_cells.append(f"`{row['task_id']}`")
        lines.append("| " + " | ".join(row_cells) + " |")
    lines.extend(
        [
            "",
            "Each row has a stable operation ID, task owner, handler, test IDs, execution classification, and an explicit contract; unobserved values remain marked as unknown.",
            "Orphan client targets, unhandled generated MCP actions, source-only MCP tools, dynamic route registry entries, and generated schemas without source registrations fail `--check`.",
            "",
        ]
    )
    if inventory["drift"]:
        lines.extend(["## Detected drift", ""])
        lines.extend(f"- `{item}`" for item in inventory["drift"])
        lines.append("")
    return "\n".join(lines)


def _coverage_table(text: str) -> list[str]:
    lines = text.splitlines()
    start = next((index for index, line in enumerate(lines) if line.startswith("| Surface |")), None)
    if start is None:
        return []
    rows = []
    for line in lines[start:]:
        if not line.startswith("|"):
            break
        rows.append(line)
    return rows


def _coverage_task_id(text: str) -> str | None:
    lines = text.splitlines()
    start = next((index for index, line in enumerate(lines) if line.startswith("| Surface |")), None)
    if start is None or "Task ID" not in [cell.strip() for cell in lines[start].strip("|").split("|")]:
        return None
    first_data = next((line for line in lines[start + 2 :] if line.startswith("|")), None)
    if first_data is None:
        return None
    cell = first_data.rsplit("|", 2)[1].strip().strip("`")
    return cell or None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--check", action="store_true", help="exit nonzero when cross-surface drift exists")
    parser.add_argument("--write-doc", action="store_true", help="write docs/API_COVERAGE.md from current AST evidence")
    parser.add_argument("--task-id", help="record task identifier when one was assigned")
    args = parser.parse_args(argv)
    if args.check and args.write_doc:
        parser.error("--check and --write-doc cannot be used together")

    inventory = collect_inventory(args.root)
    doc_path = args.root / "docs" / "API_COVERAGE.md"
    if args.check:
        current_text = doc_path.read_text(encoding="utf-8") if doc_path.is_file() else ""
        task_id = args.task_id or _coverage_task_id(current_text)
        expected_table = _coverage_table(render_coverage(inventory, task_id))
        current_table = _coverage_table(current_text)
        coverage_matches = current_table == expected_table
        if not coverage_matches:
            inventory["drift"].append("rendered coverage rows differ from docs/API_COVERAGE.md")
            inventory["drift"] = sorted(inventory["drift"])
        print(json.dumps({
            "success": not inventory["drift"],
            "coverage_matches": coverage_matches,
            "coverage_rows": max(0, len(expected_table) - 2),
            "drift": inventory["drift"],
        }, sort_keys=True))
        return 1 if inventory["drift"] else 0
    if args.write_doc:
        doc_path.write_text(render_coverage(inventory, args.task_id), encoding="utf-8")
        print(json.dumps({
            "success": not inventory["drift"],
            "written": doc_path.relative_to(args.root).as_posix(),
            "coverage_rows": len(coverage_rows(_findings(inventory), args.task_id)),
            "drift": inventory["drift"],
        }, sort_keys=True))
        return 0
    print(json.dumps(inventory, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

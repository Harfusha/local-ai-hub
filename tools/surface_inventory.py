#!/usr/bin/env python3
"""Deterministic AST inventory of the public Local AI Hub surfaces."""

from __future__ import annotations

import argparse
import ast
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
        tools.append({"name": public_name, "evidence": f"{path}:{node.lineno}"})

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
    if added_path:
        sys.path.insert(0, source_path)
    try:
        from local_ai_hub.config import load_config
        from local_ai_hub.generator import generate_mcp_tool_schemas

        config_path = root / "config.toml"
        cfg = load_config(str(config_path)) if config_path.is_file() else load_config()
        generated = generate_mcp_tool_schemas(cfg)
        schemas = {name: json.loads(json.dumps(schema)) for name, schema in generated.items()}
        evidence = {name: "src/local_ai_hub/generator.py:generate_mcp_tool_schemas" for name in schemas}
    except Exception as exc:
        errors.append(f"unable to generate MCP JSON schemas ({type(exc).__name__})")
    finally:
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
                item = {
                    "method": method,
                    "path": route,
                    "match": "prefix" if is_dynamic else "exact",
                    "prefix": route if is_dynamic else None,
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
        if prefix:
            for key, route in list(merged.items()):
                if key[0] == entry["method"] and route["path"] == prefix and route.get("match") == "prefix":
                    del merged[key]
        merged[(entry["method"], entry["path"])] = {
            "method": entry["method"],
            "path": entry["path"],
            "match": entry["match"],
            "prefix": prefix,
            "classification": entry["classification"],
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
            methods.append({"name": method.name, "evidence": f"{path}:{method.lineno}"})
            for call in ast.walk(method):
                if not isinstance(call, ast.Call) or _call_name(call.func) not in {"_request", "request", "get", "post", "put", "patch", "delete"}:
                    continue
                route_nodes = [arg for arg in call.args if isinstance(arg, (ast.Constant, ast.JoinedStr))]
                for keyword in call.keywords:
                    if keyword.arg in {"path", "url"}:
                        route_nodes.append(keyword.value)
                http_method = _client_http_method(call)
                for route_node in route_nodes:
                    route = _format_fstring(route_node)
                    if route and route.startswith("/"):
                        targets.append({"method": http_method, "path": route, "client_method": method.name, "evidence": f"{path}:{call.lineno}"})
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
    mcp_actions: dict[str, list[str]] = {}
    drift = list(schema_errors)
    for name, schema in sorted(mcp_schemas.items()):
        source_tool = source_tools_by_name.get(name)
        if source_tool is None:
            drift.append(f"generated MCP schema {name} has no source tool registration")
        mcp_tools.append(
            {
                "name": name,
                "evidence": source_tool["evidence"] if source_tool else mcp_schema_evidence[name],
                "schema_evidence": mcp_schema_evidence[name],
            }
        )
        parameters = schema.get("parameters", {})
        properties = parameters.get("properties", {}) if isinstance(parameters, dict) else {}
        action_schema = properties.get("action", {}) if isinstance(properties, dict) else {}
        actions = action_schema.get("enum", []) if isinstance(action_schema, dict) else []
        if isinstance(actions, list) and all(isinstance(action, str) for action in actions):
            mcp_actions[name] = sorted(set(actions))

    source_http_routes = _extract_http(modules["http"][1], SOURCE_FILES["http"])
    drift.extend(_dynamic_route_registry_drift(source_http_routes))
    http_routes = _merge_dynamic_routes(source_http_routes)
    client_methods, client_targets = _extract_client(modules["client"][1], SOURCE_FILES["client"])
    manifests = _extract_manifests(modules["generator"][1], root)
    feature_gates = _extract_features(modules["features"][1])
    for target in client_targets:
        if not _matches_route(target, http_routes):
            drift.append(f"orphan client target {target['method']} {target['path']} at {target['evidence']}")
    route_lookup = {f"{item['method']} {item['path']}": item for item in http_routes}
    return {
        "mcp_tools": mcp_tools,
        "mcp_actions": mcp_actions,
        "mcp_action_aliases": mcp_action_aliases,
        "conditional_mcp_actions": conditional_mcp_actions,
        "generated_mcp_schemas": sorted(mcp_schemas),
        "mcp_schema_evidence": mcp_schema_evidence,
        "http_routes": http_routes,
        "http_routes_by_target": route_lookup,
        "client_methods": client_methods,
        "client_targets": client_targets,
        "cli_operations": _extract_cli(modules["cli"][1]),
        "feature_gates": feature_gates,
        "feature_gate_evidence": _named_condition_evidence((modules["features"][1],), feature_gates),
        "generated_manifests": [item["path"] for item in manifests],
        "drift": sorted(drift),
    }


def coverage_rows(findings: list[dict[str, Any]], task_id: str | None = None) -> list[dict[str, Any]]:
    rows = []
    for finding in findings:
        condition = finding.get("condition")
        evidence = finding.get("evidence", [])
        evidence_status = finding.get("evidence_status") or ("conditional" if condition else "confirmed")
        owner = finding.get("owner") or (evidence[0].split(":", 1)[0] if evidence else "surface inventory")
        row = {
            "surface": finding["surface"],
            "name": finding["name"],
            "status": evidence_status,
            "evidence_status": evidence_status,
            "owner": owner,
            "acceptance": finding.get("acceptance") or "Inventory agrees with cited source or generated schema evidence.",
            "condition": condition,
            "reproduction": "python tools/surface_inventory.py --check",
            "evidence": evidence,
        }
        if task_id:
            row["task_id"] = task_id
        rows.append(row)
    return rows


def _findings(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for tool in inventory["mcp_tools"]:
        findings.append(
            {
                "surface": "MCP tool",
                "name": tool["name"],
                "owner": SOURCE_FILES["mcp"],
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
                    "acceptance": f"Generated schema advertises this action when {gate} is enabled.",
                    "evidence_status": "conditional",
                    "evidence": [f"{SOURCE_FILES['mcp']}:RepoAction"],
                }
            )
    for tool_name, aliases in inventory["mcp_action_aliases"].items():
        for alias, canonical in aliases.items():
            findings.append(
                {
                    "surface": f"MCP action alias {tool_name}",
                    "name": f"{alias} (alias for {canonical})",
                    "owner": SOURCE_FILES["mcp"],
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
                "acceptance": "Client method is declared.",
                "evidence": [method["evidence"]],
            }
        )
    for target in inventory["client_targets"]:
        findings.append(
            {
                "surface": "HubClient target",
                "name": f"{target['method']} {target['path']}",
                "condition": "dynamic target" if "{" in target["path"] or "?" in target["path"] else None,
                "owner": SOURCE_FILES["client"],
                "acceptance": "Client request method and path match a public HTTP route.",
                "evidence": [target["evidence"]],
            }
        )
    for operation in inventory["cli_operations"]:
        findings.append(
            {
                "surface": "CLI operation",
                "name": operation,
                "owner": SOURCE_FILES["cli"],
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
    lines = [
        "# API surface coverage",
        "",
        "Deterministic source inventory. Evidence status is confirmed, conditional, or refuted; runtime behavior is unverified.",
        "Reproduce with `python tools/surface_inventory.py --check`.",
        "",
        "| Surface | Name | Evidence status | Owner | Acceptance | Reproduction | Evidence |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| {surface} | `{name}` | {status} | `{owner}` | {acceptance} | `{reproduction}` | `{evidence}` |".format(
                surface=row["surface"],
                name=row["name"],
                status=row["evidence_status"],
                owner=row["owner"],
                acceptance=row["acceptance"],
                reproduction=row["reproduction"],
                evidence=", ".join(row["evidence"]),
            )
        )
    lines.extend(
        [
            "",
            "Inventory also records action literals, HubClient methods and targets, CLI operations, feature gates, and generated manifests in JSON output.",
            "Orphan client targets, dynamic route registry entries, and generated MCP schemas without source registrations fail `--check`.",
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--check", action="store_true", help="exit nonzero when cross-surface drift exists")
    parser.add_argument("--write-doc", action="store_true", help="write docs/API_COVERAGE.md from current AST evidence")
    parser.add_argument("--task-id", help="record task identifier when one was assigned")
    args = parser.parse_args(argv)
    inventory = collect_inventory(args.root)
    doc_path = args.root / "docs" / "API_COVERAGE.md"
    if args.write_doc:
        doc_path.write_text(render_coverage(inventory, args.task_id), encoding="utf-8")
    if args.check:
        expected_table = _coverage_table(render_coverage(inventory, args.task_id))
        current_table = _coverage_table(doc_path.read_text(encoding="utf-8")) if doc_path.is_file() else []
        if current_table != expected_table:
            inventory["drift"].append("rendered coverage rows differ from docs/API_COVERAGE.md")
            inventory["drift"] = sorted(inventory["drift"])
    print(json.dumps(inventory, indent=2, sort_keys=True))
    return 1 if args.check and inventory["drift"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

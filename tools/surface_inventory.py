#!/usr/bin/env python3
"""Deterministic AST inventory of the public Local AI Hub surfaces."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import re
import subprocess
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
        "path": "/api/browser/",
        "method": "OPTIONS",
        "match": "prefix",
        "prefix": "/api/browser/",
        "classification": "registered_dynamic",
        "handler": "do_OPTIONS",
        "registry_only": True,
    },
    {
        "path": "/api/vision/review",
        "method": "OPTIONS",
        "match": "exact",
        "classification": "registered_dynamic",
        "handler": "do_OPTIONS",
        "registry_only": True,
    },
    {
        "path": "/api/context/pack",
        "method": "POST",
        "match": "exact",
        "classification": "registered_dynamic",
        "owner_task": "T14",
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
                            if isinstance(other, ast.Name):
                                actions.update(type_aliases.get(other.id, set()))
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
    tree: ast.Module,
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    external_type_aliases: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    functions = {
        item.name: item for item in ast.walk(tree)
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if "action" not in {item.arg for item in function.args.args}:
        return {"actions": [], "action_literals": [], "detail_literals": [], "default_actions": [], "prefixes": [], "symbols": [function.name], "delegated": False, "targets": [], "action_alias_parameters": []}

    handlers = [function]
    symbols = [function.name]
    visited = {function.name}
    pending = [function]
    prefixes: set[str] = set()
    targets: set[str] = set()
    action_payload = False
    type_aliases = _type_alias_literals(tree)
    for name, values in (external_type_aliases or {}).items():
        type_aliases.setdefault(name, values)
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
    runtime_action_literals = _dispatch_literals(handlers, "action", type_aliases)
    runtime_detail_literals = _dispatch_literals(handlers, "detail", type_aliases)
    dispatch_actions = runtime_action_literals | runtime_detail_literals
    action_names = {"action"}
    for item in ast.walk(function):
        if not isinstance(item, (ast.Assign, ast.AnnAssign)) or item.value is None:
            continue
        if any(isinstance(child, ast.Name) and child.id in action_names for child in ast.walk(item.value)):
            assignment_targets = item.targets if isinstance(item, ast.Assign) else [item.target]
            action_names.update(target.id for target in assignment_targets if isinstance(target, ast.Name))
    checked_types = {
        other.value.id
        for item in ast.walk(function)
        if isinstance(item, ast.Compare)
        for part in [item.left, *item.comparators]
        if isinstance(part, ast.Name) and part.id in action_names
        for other in [item.left, *item.comparators]
        if isinstance(other, ast.Attribute)
        and other.attr == "__args__"
        and isinstance(other.value, ast.Name)
    }
    action_alias_parameters = {
        argument.arg
        for argument in function.args.args
        if argument.arg != "action"
        and isinstance(argument.annotation, ast.Name)
        and argument.annotation.id in checked_types
        and any(
            isinstance(item, (ast.Assign, ast.AnnAssign))
            and item.value is not None
            and any(isinstance(child, ast.Name) and child.id in action_names for child in ast.walk(item.value))
            and any(
                isinstance(target, ast.Name) and target.id == argument.arg
                for target in (item.targets if isinstance(item, ast.Assign) else [item.target])
            )
            for item in ast.walk(function)
        )
    }
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
        "action_literals": sorted(runtime_action_literals),
        "detail_literals": sorted(runtime_detail_literals),
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
        "action_alias_parameters": sorted(action_alias_parameters),
    }


def _target_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id.lower()
    if isinstance(node, (ast.Tuple, ast.List)):
        return " ".join(_target_name(item) for item in node.elts)
    return ""


def _extract_mcp(
    tree: ast.Module,
    path: str,
    external_type_aliases: dict[str, set[str]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]], dict[str, dict[str, str]]]:
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
        handler_analysis = _mcp_action_handlers(tree, node, external_type_aliases)
        tools.append({
            "name": public_name,
            "handler": node.name,
            "handler_symbols": handler_analysis["symbols"],
            "dispatch_actions": handler_analysis["actions"],
            "action_literals": handler_analysis["action_literals"],
            "detail_literals": handler_analysis["detail_literals"],
            "default_actions": handler_analysis["default_actions"],
            "dispatch_prefixes": handler_analysis["prefixes"],
            "delegated_dispatch": handler_analysis["delegated"],
            "action_alias_parameters": handler_analysis["action_alias_parameters"],
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


def _generated_mcp_schemas(
    root: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, str], list[str], set[str]]:
    schema_dir = root / "generated" / "schemas"
    schemas: dict[str, dict[str, Any]] = {}
    evidence: dict[str, str] = {}
    errors: list[str] = []
    # Ignored runtime artifacts and per-machine config are not reproducible
    # inputs to checked-in API coverage. Use them only in standalone fixtures
    # or when the repository explicitly tracks them.
    schema_artifacts_ignored = _git_ignores(root, "generated/schemas/local_ai_repo.json")
    if schema_dir.is_dir() and not schema_artifacts_ignored:
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
        operation_contract_path = root / "src" / "local_ai_hub" / "operation_contracts.py"
        if operation_contract_path.is_file():
            previous_dont_write_bytecode = sys.dont_write_bytecode
            sys.dont_write_bytecode = True
            try:
                spec = importlib.util.spec_from_file_location(
                    "_surface_inventory_operation_contracts", operation_contract_path
                )
                if spec is None or spec.loader is None:
                    raise ImportError("operation contract registry cannot be loaded")
                registry = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(registry)
                for name, payload in schemas.items():
                    if isinstance(payload.get("x-operation-contract"), dict):
                        continue
                    metadata = registry.operation_metadata(name)
                    if metadata:
                        payload["x-operation-contract"] = metadata
            except Exception as exc:
                errors.append(f"unable to load operation contract registry ({type(exc).__name__})")
            finally:
                sys.dont_write_bytecode = previous_dont_write_bytecode
        if not schemas and not errors:
            errors.append("generated MCP schema directory contains no tool schemas")
        return schemas, evidence, errors, set()

    source_path = str((root / "src").resolve())
    added_path = source_path not in sys.path
    previous_dont_write_bytecode = sys.dont_write_bytecode
    disabled_tools: set[str] = set()
    sys.dont_write_bytecode = True
    if added_path:
        sys.path.insert(0, source_path)
    try:
        from local_ai_hub.config import load_config
        from local_ai_hub.features import FeatureSet
        from local_ai_hub.generator import generate_mcp_tool_schemas

        # This --check fallback must stay read-only: load_config reads files and
        # generate_mcp_tool_schemas returns an in-memory mapping. Never call
        # write_all_generated here; that separate generator persists artifacts.
        config_path = root / "config.toml"
        if config_path.is_file() and not _git_ignores(root, "config.toml"):
            cfg = load_config(str(config_path))
        else:
            # Inventory generation must not inherit a developer's home config
            # or LOCAL_AI_CONFIG when this checkout has no project config.
            defaults_path = root / "defaults.toml"
            if not defaults_path.is_file():
                raise FileNotFoundError("project config.toml or defaults.toml is required")
            cfg = load_config(str(defaults_path))
        disabled_tools = set(FeatureSet.from_config(cfg).disabled_tools)
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
    return schemas, evidence, errors, disabled_tools


def _git_ignores(root: Path, relative_path: str) -> bool:
    """Return whether Git ignores a path; non-Git fixtures remain self-contained."""
    try:
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", "--no-index", "--", relative_path],
            cwd=root,
            capture_output=True,
            timeout=2,
            check=False,
            **_hidden_run_kwargs(root),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _hidden_run_kwargs(root: Path) -> dict[str, Any]:
    """Load the shared no-console subprocess options from this checkout."""
    source_path = str((root / "src").resolve())
    added_path = source_path not in sys.path
    if added_path:
        sys.path.insert(0, source_path)
    try:
        from local_ai_hub.process_utils import hidden_run_kwargs

        return hidden_run_kwargs()
    except Exception:
        if sys.platform == "win32":
            return {"creationflags": int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))}
        return {}
    finally:
        if added_path:
            try:
                sys.path.remove(source_path)
            except ValueError:
                pass


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


def _route_availability_gates(nodes: list[ast.AST]) -> list[str]:
    gates: list[str] = []
    for node in nodes:
        if not isinstance(node, ast.If) or _route_literals(node.test)[0]:
            continue
        descendants = list(ast.walk(node.test))
        has_app = any(isinstance(item, ast.Name) and item.id == "APP" for item in descendants)
        if not has_app:
            continue
        has_optional_lookup = any(
            isinstance(item, ast.Call)
            and _call_name(item.func) == "getattr"
            and item.args
            and isinstance(item.args[0], ast.Name)
            and item.args[0].id == "APP"
            for item in descendants
        )
        has_enabled_check = any(
            (isinstance(item, ast.Attribute) and item.attr in {"enabled", "available"})
            or (isinstance(item, ast.Constant) and item.value in {"enabled", "available"})
            for item in descendants
        )
        has_feature_check = any(
            (isinstance(item, ast.Attribute) and item.attr == "features")
            or (isinstance(item, ast.Constant) and item.value in {"features", "dashboard_enabled"})
            for item in descendants
        )
        has_optional_compare = any(
            isinstance(item, ast.Compare)
            and any(isinstance(operator, (ast.Is, ast.IsNot)) for operator in item.ops)
            and any(isinstance(value, ast.Constant) and value.value is None for value in item.comparators)
            for item in descendants
        )
        if has_optional_lookup or has_enabled_check or has_feature_check or has_optional_compare:
            condition = ast.unparse(node.test)
            if condition not in gates:
                gates.append(condition)
    return gates


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

                conditional_gates = _route_availability_gates(route_nodes)
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
                        "conditional_gates": conditional_gates,
                        "timeout": "no route-local timeout declaration; effective request budget unverified",
                        "operation_side_effects": {
                            "direct_calls": sorted(direct_calls),
                            "classification": "transitive effects unverified",
                        },
                        "backend_availability": (
                            "route availability depends on the listed source gates; downstream runtime health unverified"
                            if conditional_gates
                            else "handler route is registered; downstream runtime health unverified"
                        ),
                    },
                    "conditional_gates": conditional_gates,
                    "evidence_status": "conditional" if conditional_gates else "confirmed",
                    "evidence": f"{path}:{branch.lineno}",
                }
                routes[(method, route)] = item
    return sorted(routes.values(), key=lambda item: (item["method"], item["path"]))


def _extract_registered_http(tree: ast.Module, path: str) -> list[dict[str, Any]]:
    assignments: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and value is not None:
                assignments[target.id] = value

    def string_mapping(name: str) -> dict[str, str]:
        value = assignments.get(name)
        if isinstance(value, ast.Call) and _call_name(value.func) == "MappingProxyType" and value.args:
            value = value.args[0]
        if not isinstance(value, ast.Dict):
            return {}
        return {
            key.value: item.value
            for key, item in zip(value.keys, value.values)
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
            and isinstance(item, ast.Constant) and isinstance(item.value, str)
        }

    registered: list[tuple[str, str, str, int]] = []
    get_handlers = string_mapping("GET_ROUTE_HANDLER_BOUNDARIES")
    node_lines = {
        target.id: node.lineno
        for node in tree.body if isinstance(node, ast.Assign)
        for target in node.targets if isinstance(target, ast.Name)
    }
    registered.extend(
        ("GET", route, handler, node_lines.get("GET_ROUTE_HANDLER_BOUNDARIES", 1))
        for route, handler in get_handlers.items()
    )

    post_handlers = string_mapping("POST_ROUTE_HANDLER_BOUNDARIES")
    post_registry = assignments.get("POST_ROUTE_REGISTRY")
    if isinstance(post_registry, (ast.Tuple, ast.List)):
        for entry in post_registry.elts:
            if isinstance(entry, ast.Call) and _call_name(entry.func) == "RouteRule" and len(entry.args) >= 2:
                route_id, paths = entry.args[:2]
            elif isinstance(entry, (ast.Tuple, ast.List)) and len(entry.elts) == 2:
                route_id, paths = entry.elts
            else:
                continue
            if not isinstance(route_id, ast.Constant) or not isinstance(route_id.value, str):
                continue
            if isinstance(paths, ast.Call) and _call_name(paths.func) == "frozenset" and paths.args:
                paths = paths.args[0]
            if not isinstance(paths, (ast.Tuple, ast.List, ast.Set)):
                continue
            handler = post_handlers.get(route_id.value, "registered POST handler")
            registered.extend(
                ("POST", route.value, handler, entry.lineno)
                for route in paths.elts
                if isinstance(route, ast.Constant) and isinstance(route.value, str)
            )

    return [
        {
            "method": method,
            "path": route,
            "match": "exact",
            "prefix": None,
            "handler": handler,
            "action": [handler],
            "contract": {
                "method": method,
                "path_pattern": route,
                "match": "exact",
                "action": [handler],
            },
            "evidence": f"{path}:{line}",
        }
        for method, route, handler, line in registered
    ]


def _dynamic_route_registry_drift(routes: list[dict[str, Any]]) -> list[str]:
    drift = []
    for entry in DYNAMIC_ROUTE_REGISTRY:
        if entry["path"] == "/api/context/pack" or entry.get("registry_only"):
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
        contract = {
            "method": entry["method"],
            "path_pattern": entry["path"],
            "match": entry["match"],
            "action": (source_route or {}).get("action", []),
        }
        if owner_gate := entry.get("owner_gate"):
            contract["owner_gate"] = owner_gate
        merged[(entry["method"], entry["path"])] = {
            "method": entry["method"],
            "path": entry["path"],
            "match": entry["match"],
            "prefix": prefix,
            "classification": entry["classification"],
            "owner_task": entry.get("owner_task"),
            "handler": (source_route or {}).get("handler", "dynamic registry handler not inspected"),
            "action": (source_route or {}).get("action", []),
            "contract": contract,
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


def _urllib_request_target(
    call: ast.Call, assignments: dict[str, ast.AST]
) -> tuple[str, str] | None:
    request_node = call.args[0] if call.args else next(
        (item.value for item in call.keywords if item.arg == "url"), None
    )
    visited: set[str] = set()
    while isinstance(request_node, ast.Name) and request_node.id in assignments:
        if request_node.id in visited:
            return None
        visited.add(request_node.id)
        request_node = assignments[request_node.id]
    if not isinstance(request_node, ast.Call) or _call_name(request_node.func) != "Request":
        return None
    route_node = request_node.args[0] if request_node.args else next(
        (item.value for item in request_node.keywords if item.arg == "url"), None
    )
    if route_node is None:
        return None
    visited.clear()
    while isinstance(route_node, ast.Name) and route_node.id in assignments:
        if route_node.id in visited:
            return None
        visited.add(route_node.id)
        route_node = assignments[route_node.id]
    route = _format_fstring(route_node)
    if route is None:
        return None
    if route.startswith("{base_url}"):
        route = route[len("{base_url}"):]
    for query_suffix in ("{qs}", "{query}"):
        if route.endswith(query_suffix):
            route = route[:-len(query_suffix)]
            break
    if not route.startswith("/"):
        return None

    method_node = next(
        (item.value for item in request_node.keywords if item.arg == "method"), None
    )
    if method_node is None and len(request_node.args) > 5:
        method_node = request_node.args[5]
    data_node = request_node.args[1] if len(request_node.args) > 1 else next(
        (item.value for item in request_node.keywords if item.arg == "data"), None
    )
    visited.clear()
    while isinstance(data_node, ast.Name) and data_node.id in assignments:
        if data_node.id in visited:
            data_node = None
            break
        visited.add(data_node.id)
        data_node = assignments[data_node.id]
    if isinstance(method_node, ast.Constant) and isinstance(method_node.value, str):
        method = method_node.value.upper()
    elif method_node is not None:
        method = "ANY"
    elif data_node is None or (
        isinstance(data_node, ast.Constant) and data_node.value is None
    ):
        method = "GET"
    elif isinstance(data_node, ast.Constant):
        method = "POST"
    else:
        method = "ANY"
    return method, route


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
            parameter_names = set(parameters)
            if method.args.vararg is not None:
                parameter_names.add(method.args.vararg.arg)
            if method.args.kwarg is not None:
                parameter_names.add(method.args.kwarg.arg)
            methods.append({"name": method.name, "parameters": parameters, "evidence": f"{path}:{method.lineno}"})
            assignments: dict[str, ast.AST] = {}
            assignment_nodes = (
                item for item in ast.walk(method) if isinstance(item, (ast.Assign, ast.AnnAssign))
            )
            ambiguous_assignment = "__ambiguous_assignment__"
            for statement in sorted(assignment_nodes, key=lambda item: item.lineno):
                if isinstance(statement, ast.Assign):
                    for target in statement.targets:
                        if isinstance(target, ast.Name):
                            if target.id in parameter_names:
                                assignments[target.id] = ast.Name(
                                    id=ambiguous_assignment, ctx=ast.Load()
                                )
                                continue
                            previous = assignments.get(target.id)
                            if (
                                previous is not None
                                and ast.dump(previous) != ast.dump(statement.value)
                            ):
                                assignments[target.id] = ast.Name(
                                    id=ambiguous_assignment, ctx=ast.Load()
                                )
                            elif not (
                                isinstance(previous, ast.Name)
                                and previous.id == ambiguous_assignment
                            ):
                                assignments[target.id] = statement.value
                elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                    if statement.target.id in parameter_names:
                        assignments[statement.target.id] = ast.Name(
                            id=ambiguous_assignment, ctx=ast.Load()
                        )
                        continue
                    previous = assignments.get(statement.target.id)
                    if (
                        previous is not None
                        and statement.value is not None
                        and ast.dump(previous) != ast.dump(statement.value)
                    ):
                        assignments[statement.target.id] = ast.Name(
                            id=ambiguous_assignment, ctx=ast.Load()
                        )
                    elif not (
                        isinstance(previous, ast.Name)
                        and previous.id == ambiguous_assignment
                    ):
                        assignments[statement.target.id] = statement.value
            for call in ast.walk(method):
                if not isinstance(call, ast.Call):
                    continue
                call_name = _call_name(call.func)
                is_urllib_open = call_name == "urlopen"
                if is_urllib_open:
                    urllib_target = _urllib_request_target(call, assignments)
                    if urllib_target is None:
                        continue
                    http_method, urllib_route = urllib_target
                    route_nodes = [None]
                elif call_name in {"_request", "request", "get", "post", "put", "patch", "delete"}:
                    route_nodes = [arg for arg in call.args if isinstance(arg, (ast.Constant, ast.JoinedStr))]
                    for keyword in call.keywords:
                        if keyword.arg in {"path", "url"}:
                            route_nodes.append(keyword.value)
                    http_method = _client_http_method(call)
                else:
                    continue
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
                    route = urllib_route if is_urllib_open else _format_fstring(route_node)
                    if route and route.startswith("/"):
                        targets.append({
                            "method": http_method,
                            "path": route,
                            "client_method": method.name,
                            "parameters": parameters,
                            "timeout": timeout_value,
                            "retry_policy": retry_policy,
                            "response_contract": (
                                "urllib HTTP response consumed by HubClient method"
                                if is_urllib_open
                                else "JSON decoded to dict[str, Any] by HubClient request wrapper"
                            ),
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


def _literal_path_expression(node: ast.AST) -> str | None:
    parts = []
    current = node
    while isinstance(current, ast.BinOp) and isinstance(current.op, ast.Div):
        if not isinstance(current.right, ast.Constant) or not isinstance(current.right.value, str):
            return None
        parts.append(current.right.value)
        current = current.left
    if not isinstance(current, ast.Name) or not parts:
        return None
    return "/".join(reversed(parts))


def _extract_manifests(tree: ast.Module, root: Path) -> tuple[list[dict[str, str]], list[str]]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(_target_name(target) in MANIFEST_NAMES for target in node.targets):
            names.update(value for value in _literal_strings(node.value) if value.endswith((".md", ".json", ".toml")))
        if isinstance(node, ast.Call) and _call_name(node.func) in {"write_text", "write_bytes"}:
            receiver = node.func.value
            if isinstance(receiver, ast.BinOp) and isinstance(receiver.op, ast.Div):
                path = _literal_path_expression(receiver)
                values = [path] if path else []
            else:
                values = _literal_strings(receiver)
            for value in values:
                if value.endswith((".md", ".json", ".toml")):
                    names.add(value)
    manifests = []
    missing = []
    for name in sorted(names):
        candidate = root / name
        if candidate.is_file():
            manifests.append({"path": name, "text": candidate.read_text(encoding="utf-8", errors="replace")})
        else:
            missing.append(name)
    return manifests, missing


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


def _behavioral_test_links(root: Path, inventory: dict[str, Any]) -> dict[str, list[str]]:
    """Link only asserted test calls that name a concrete inventoried operation."""
    links: dict[str, set[str]] = {}
    tests_root = root / "tests"
    if not tests_root.is_dir():
        return {}

    tools = {item["name"] for item in inventory["mcp_tools"]}
    client_methods = {item["name"] for item in inventory["client_methods"]}
    aliases = inventory["mcp_action_aliases"]

    def add(key: str, selector: str) -> None:
        links.setdefault(key, set()).add(selector)

    def string_value(node: ast.AST) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr):
            return "".join(
                item.value if isinstance(item, ast.Constant) and isinstance(item.value, str) else ""
                for item in node.values
            )
        return None

    def url_path(value: str) -> str | None:
        match = re.search(r"(?:https?://[^/]+)?(/[^?#\s'\"]*)", value)
        return match.group(1) if match else None

    def static_url_text(
        node: ast.AST,
        nodes: list[ast.AST],
        before: tuple[int, int],
        seen: frozenset[str] = frozenset(),
    ) -> str:
        value = string_value(node)
        if value is not None:
            return value
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return static_url_text(node.left, nodes, before, seen) + static_url_text(
                node.right, nodes, before, seen
            )
        if isinstance(node, ast.Name) and node.id not in seen:
            assignments = sorted(
                (
                    assignment
                    for assignment in nodes
                    if isinstance(assignment, (ast.Assign, ast.AnnAssign, ast.NamedExpr))
                    and (assignment.lineno, assignment.col_offset) < before
                    and node.id
                    in (
                        set().union(*(target_names(target) for target in assignment.targets))
                        if isinstance(assignment, ast.Assign)
                        else target_names(assignment.target)
                    )
                ),
                key=lambda assignment: (assignment.lineno, assignment.col_offset),
            )
            if assignments:
                assignment = assignments[-1]
                return static_url_text(
                    assignment.value,
                    nodes,
                    (assignment.lineno, assignment.col_offset),
                    seen | {node.id},
                )
        return ""

    def route_matches(method: str, path: str, route: dict[str, Any]) -> bool:
        if method != route["method"]:
            return False
        candidate = path.split("?", 1)[0]
        template = route["path"]
        if candidate == template:
            return True
        if "{" in template and "}" in template:
            pattern = "^" + re.sub(r"\\\{[^{}]+\\\}", r"[^/]+", re.escape(template)) + "$"
            return bool(re.match(pattern, candidate))
        return route.get("match") == "prefix" and bool(route.get("prefix")) and candidate.startswith(route["prefix"])

    def scoped_nodes(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
        nodes: list[ast.AST] = []
        pending = list(function.body)
        while pending:
            node = pending.pop()
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            nodes.append(node)
            pending.extend(ast.iter_child_nodes(node))
        return nodes

    def test_functions(tree: ast.Module) -> list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, tuple[str, ...]]]:
        functions: list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, tuple[str, ...]]] = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                functions.append((node, ()))
            elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                functions.extend(
                    (member, (node.name,))
                    for member in node.body
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and member.name.startswith("test_")
                )
        return functions

    def names_in(node: ast.AST) -> set[str]:
        return {item.id for item in ast.walk(node) if isinstance(item, ast.Name)}

    def target_names(node: ast.AST) -> set[str]:
        if isinstance(node, ast.Name):
            return {node.id}
        if isinstance(node, (ast.Tuple, ast.List)):
            return set().union(*(target_names(item) for item in node.elts)) if node.elts else set()
        return set()

    def asserted_calls(nodes: list[ast.AST]) -> set[int]:
        origins: dict[str, set[int]] = {}
        asserted: set[int] = set()
        ordered = sorted(nodes, key=lambda item: (getattr(item, "lineno", 0), getattr(item, "col_offset", 0)))
        for node in ordered:
            if isinstance(node, ast.Assert):
                for name in names_in(node.test):
                    asserted.update(origins.get(name, set()))
                asserted.update(id(item) for item in ast.walk(node.test) if isinstance(item, ast.Call))
                continue
            if isinstance(node, ast.Assign):
                names = set().union(*(target_names(target) for target in node.targets))
                value = node.value
            elif isinstance(node, ast.AnnAssign):
                names = target_names(node.target)
                value = node.value
            elif isinstance(node, ast.NamedExpr):
                names = target_names(node.target)
                value = node.value
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    if item.optional_vars is not None:
                        assigned = target_names(item.optional_vars)
                        value_origins = {id(item.context_expr)} if isinstance(item.context_expr, ast.Call) else set()
                        for name in names_in(item.context_expr):
                            value_origins.update(origins.get(name, set()))
                        for name in assigned:
                            origins[name] = value_origins
                continue
            else:
                continue
            if value is None:
                continue
            value_origins = {id(item) for item in ast.walk(value) if isinstance(item, ast.Call)}
            for name in names_in(value):
                value_origins.update(origins.get(name, set()))
            for name in names:
                origins[name] = value_origins
        return asserted

    def hubclient_receivers(nodes: list[ast.AST], function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
        receivers = {
            arg.arg for arg in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
            if isinstance(arg.annotation, ast.Name) and arg.annotation.id == "HubClient"
        }
        ordered = sorted(nodes, key=lambda item: (getattr(item, "lineno", 0), getattr(item, "col_offset", 0)))
        for node in ordered:
            if isinstance(node, ast.Assign):
                names = set().union(*(target_names(target) for target in node.targets))
                value = node.value
            elif isinstance(node, ast.AnnAssign):
                names = target_names(node.target)
                value = node.value
                if isinstance(node.annotation, ast.Name) and node.annotation.id == "HubClient":
                    receivers.update(names)
            else:
                continue
            if value is None:
                continue
            if isinstance(value, ast.Name) and value.id == "running_app_client":
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, (ast.Tuple, ast.List)) and target.elts:
                        receivers.update(target_names(target.elts[0]))
            is_hubclient = False
            if isinstance(value, ast.Call):
                if isinstance(value.func, ast.Name) and value.func.id == "HubClient":
                    is_hubclient = True
                elif isinstance(value.func, ast.Attribute) and value.func.attr == "__new__":
                    is_hubclient = "HubClient" in names_in(value)
            if is_hubclient or names_in(value) & receivers:
                receivers.update(names)
        return receivers

    def http_client_receivers(nodes: list[ast.AST], function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
        client_types = {"Client", "AsyncClient", "TestClient", "FlaskClient", "WebTestClient"}
        receivers = {
            arg.arg for arg in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
            if isinstance(arg.annotation, ast.Name) and arg.annotation.id in client_types
            or isinstance(arg.annotation, ast.Attribute) and arg.annotation.attr in client_types
        }
        ordered = sorted(nodes, key=lambda item: (getattr(item, "lineno", 0), getattr(item, "col_offset", 0)))
        for node in ordered:
            if isinstance(node, ast.Assign):
                names = set().union(*(target_names(target) for target in node.targets))
                value = node.value
            elif isinstance(node, ast.AnnAssign):
                names = target_names(node.target)
                value = node.value
                annotation = node.annotation
                if isinstance(annotation, ast.Name) and annotation.id in client_types:
                    receivers.update(names)
                elif isinstance(annotation, ast.Attribute) and annotation.attr in client_types:
                    receivers.update(names)
            else:
                continue

            if value is None:
                continue

            if isinstance(value, ast.Name) and value.id == "running_app_client":
                for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                    if isinstance(target, (ast.Tuple, ast.List)) and target.elts:
                        receivers.update(target_names(target.elts[0]))
            elif isinstance(value, ast.Call):
                called_type = (
                    value.func.id if isinstance(value.func, ast.Name)
                    else value.func.attr if isinstance(value.func, ast.Attribute)
                    else ""
                )
                if called_type in client_types:
                    receivers.update(names)
            if names_in(value) & receivers:
                receivers.update(names)
        return receivers

    def imported_symbols(statements: list[ast.stmt], module_path: str) -> dict[str, str]:
        return {
            alias.asname or alias.name: alias.name
            for statement in statements
            if isinstance(statement, ast.ImportFrom) and statement.module == module_path
            for alias in statement.names
        }

    def urllib_request_imports(statements: list[ast.stmt]) -> tuple[set[str], dict[str, str]]:
        modules: set[str] = set()
        symbols: dict[str, str] = {}
        for statement in statements:
            if isinstance(statement, ast.Import):
                for alias in statement.names:
                    if alias.name == "urllib.request":
                        modules.add(alias.asname or alias.name)
            elif isinstance(statement, ast.ImportFrom):
                if statement.module == "urllib":
                    modules.update(alias.asname or alias.name for alias in statement.names if alias.name == "request")
                elif statement.module == "urllib.request":
                    symbols.update(
                        {alias.asname or alias.name: alias.name for alias in statement.names
                         if alias.name in {"Request", "urlopen"}}
                    )
        return modules, symbols

    def is_urllib_request_call(
        call: ast.Call,
        name: str,
        modules: set[str],
        symbols: dict[str, str],
    ) -> bool:
        if isinstance(call.func, ast.Name):
            return symbols.get(call.func.id) == name
        qualified = dotted_name(call.func)
        if not qualified or qualified.rsplit(".", 1)[-1] != name:
            return False
        return qualified.rsplit(".", 1)[0] in modules

    def urllib_request_spec(call: ast.Call) -> tuple[ast.AST, str | None] | None:
        url_node = call.args[0] if call.args else next(
            (keyword.value for keyword in call.keywords if keyword.arg == "url"), None
        )
        if url_node is None:
            return None
        method_node = next((keyword.value for keyword in call.keywords if keyword.arg == "method"), None)
        if method_node is not None and not (isinstance(method_node, ast.Constant) and method_node.value is None):
            method_value = string_value(method_node)
            return url_node, method_value.upper() if method_value else None
        data_node = call.args[1] if len(call.args) > 1 else next(
            (keyword.value for keyword in call.keywords if keyword.arg == "data"), None
        )
        if data_node is None or isinstance(data_node, ast.Constant) and data_node.value is None:
            return url_node, "GET"
        if isinstance(data_node, ast.Constant):
            return url_node, "POST"
        return url_node, None

    def urllib_request_bindings(
        nodes: list[ast.AST],
        modules: set[str],
        symbols: dict[str, str],
    ) -> dict[str, list[tuple[tuple[int, int], tuple[ast.AST, str | None] | None]]]:
        bindings: dict[str, list[tuple[tuple[int, int], tuple[ast.AST, str | None] | None]]] = {}
        assignments = sorted(
            (node for node in nodes if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr, ast.AugAssign))),
            key=lambda node: (getattr(node, "lineno", 0), getattr(node, "col_offset", 0)),
        )
        for node in assignments:
            if isinstance(node, ast.Assign):
                targets = set().union(*(target_names(target) for target in node.targets))
                value = node.value
            elif isinstance(node, ast.AnnAssign):
                targets, value = target_names(node.target), node.value
            elif isinstance(node, ast.NamedExpr):
                targets, value = target_names(node.target), node.value
            else:
                targets, value = target_names(node.target), None
            if not targets:
                continue
            spec: tuple[ast.AST, str | None] | None = None
            if isinstance(value, ast.Call) and is_urllib_request_call(value, "Request", modules, symbols):
                spec = urllib_request_spec(value)
            elif isinstance(value, ast.Name):
                spec = urllib_request_binding_at(
                    bindings, value.id, (getattr(node, "lineno", 0), getattr(node, "col_offset", 0))
                )
            position = (getattr(node, "lineno", 0), getattr(node, "col_offset", 0))
            for name in targets:
                bindings.setdefault(name, []).append((position, spec))
        return bindings

    def urllib_request_binding_at(
        bindings: dict[str, list[tuple[tuple[int, int], tuple[ast.AST, str | None] | None]]],
        name: str,
        before: tuple[int, int],
    ) -> tuple[ast.AST, str | None] | None:
        latest = None
        for position, spec in bindings.get(name, []):
            if position >= before:
                break
            latest = spec
        return latest

    def urllib_result_returned(call: ast.Call, nodes: list[ast.AST]) -> bool:
        response_names: set[str] = set()
        for node in nodes:
            if isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    if item.context_expr is call and item.optional_vars is not None:
                        response_names.update(target_names(item.optional_vars))
            elif isinstance(node, ast.Assign) and node.value is call:
                response_names.update(set().union(*(target_names(target) for target in node.targets)))
            elif isinstance(node, ast.AnnAssign) and node.value is call:
                response_names.update(target_names(node.target))
            elif isinstance(node, ast.Return) and node.value is not None:
                if any(item is call for item in ast.walk(node.value)):
                    return True
        if not response_names:
            return False
        return any(
            isinstance(node, ast.Return) and node.value is not None and bool(names_in(node.value) & response_names)
            for node in nodes
        )

    def direct_http_handler_pairs(
        nodes: list[ast.AST],
        function: ast.FunctionDef | ast.AsyncFunctionDef,
        handler_types: set[str],
    ) -> list[tuple[str, str]]:
        ordered = sorted(nodes, key=lambda item: (getattr(item, "lineno", 0), getattr(item, "col_offset", 0)))
        receivers = {
            argument.arg
            for argument in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
            if (
                isinstance(argument.annotation, ast.Name) and argument.annotation.id in handler_types
                or dotted_name(argument.annotation) in handler_types
            )
        }
        paths: dict[str, str] = {}
        sinks: dict[str, set[str]] = {}
        pairs: list[tuple[str, str]] = []
        assertions = [node for node in ordered if isinstance(node, ast.Assert)]
        for node in ordered:
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign):
                targets, value = [node.target], node.value
                if (
                    isinstance(node.annotation, ast.Name) and node.annotation.id in handler_types
                    or dotted_name(node.annotation) in handler_types
                ):
                    receivers.update(target_names(node.target))
            else:
                targets, value = [], None

            for target in targets:
                if isinstance(target, ast.Name) and isinstance(value, ast.Call):
                    is_handler_constructor = (
                        isinstance(value.func, ast.Name) and value.func.id in handler_types
                        or dotted_name(value.func) in handler_types
                    )
                    is_handler_new = (
                        isinstance(value.func, ast.Attribute) and value.func.attr == "__new__"
                        and dotted_name(value.func.value) in handler_types
                    )
                    if is_handler_constructor or is_handler_new:
                        receivers.add(target.id)
                if not isinstance(target, ast.Attribute) or not isinstance(target.value, ast.Name):
                    continue
                receiver = target.value.id
                if receiver not in receivers:
                    continue
                if target.attr == "path" and value is not None:
                    path = string_value(value)
                    if path:
                        paths[receiver] = path
                elif target.attr == "_send" and isinstance(value, ast.Lambda):
                    sinks[receiver] = {
                        call.func.value.id
                        for call in ast.walk(value.body)
                        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "append" and isinstance(call.func.value, ast.Name)
                    }

            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in {f"do_{method}" for method in HTTP_METHODS.values()}:
                continue
            if not isinstance(node.func.value, ast.Name):
                continue
            receiver = node.func.value.id
            path = paths.get(receiver)
            response_sinks = sinks.get(receiver, set())
            if not path or not response_sinks:
                continue
            call_position = (node.lineno, node.col_offset)
            if any(
                (assertion.lineno, assertion.col_offset) > call_position
                and names_in(assertion.test) & response_sinks
                for assertion in assertions
            ):
                pairs.append((node.func.attr[3:], path))
        return pairs

    def cli_argv_operation(node: ast.AST) -> str | None:
        if not isinstance(node, (ast.List, ast.Tuple)):
            return None
        values = [string_value(item) for item in node.elts]
        if not values or values[0] is None:
            return None
        if values[0].endswith(".py"):
            return values[1] if len(values) > 1 else None
        return values[0]

    def cli_argv_mutation_operation(node: ast.AST) -> str | None:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
            return None
        if not isinstance(node.value.value, str):
            return None
        for target in node.targets:
            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Attribute)
                and target.value.attr == "argv"
                and isinstance(target.value.value, ast.Name)
                and target.value.value.id == "sys"
                and isinstance(target.slice, ast.Constant)
                and target.slice.value == 1
            ):
                return node.value.value
        return None

    def is_cli_argv_index_mutation(node: ast.AST) -> bool:
        return isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Subscript)
            and isinstance(target.value, ast.Attribute)
            and target.value.attr == "argv"
            and isinstance(target.value.value, ast.Name)
            and target.value.value.id == "sys"
            and isinstance(target.slice, ast.Constant)
            and target.slice.value == 1
            for target in node.targets
        )

    def cli_argv_patch(node: ast.AST) -> ast.AST | None:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Attribute) and target.attr == "argv"
            and isinstance(target.value, ast.Name) and target.value.id == "sys"
            for target in node.targets
        ):
            return node.value
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr != "setattr":
            return None
        if len(node.args) == 2 and string_value(node.args[0]) == "sys.argv":
            return node.args[1]
        if len(node.args) >= 3 and string_value(node.args[0]) == "sys.argv":
            return node.args[1]
        if (
            len(node.args) >= 3 and isinstance(node.args[0], ast.Name) and node.args[0].id == "sys"
            and string_value(node.args[1]) == "argv"
        ):
            return node.args[2]
        return None

    def module_import_bindings(statements: list[ast.stmt], module_path: str) -> tuple[set[str], set[str]]:
        parent, leaf = module_path.rsplit(".", 1)
        aliases: set[str] = set()
        dotted_imports: set[str] = set()
        for statement in statements:
            if isinstance(statement, ast.Import):
                for alias in statement.names:
                    if alias.name == module_path:
                        aliases.add(alias.asname or alias.name.split(".", 1)[0])
                        dotted_imports.add(module_path)
            elif isinstance(statement, ast.ImportFrom) and statement.module == parent:
                aliases.update(
                    alias.asname or alias.name for alias in statement.names if alias.name == leaf
                )
        return aliases, dotted_imports

    def dotted_name(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            prefix = dotted_name(node.value)
            return f"{prefix}.{node.attr}" if prefix else None
        return None

    def is_cli_main(
        call: ast.Call,
        imported_cli_modules: set[str],
        imported_cli_paths: set[str],
        imported_cli_functions: set[str],
    ) -> bool:
        if isinstance(call.func, ast.Name):
            return call.func.id in imported_cli_functions
        return (
            isinstance(call.func, ast.Attribute) and call.func.attr == "main"
            and (
                isinstance(call.func.value, ast.Name) and call.func.value.id in imported_cli_modules
                or dotted_name(call.func.value) in imported_cli_paths
            )
        )

    def cli_operation_for_call(call: ast.Call, nodes: list[ast.AST]) -> str | None:
        argv = call.args[0] if call.args else next(
            (keyword.value for keyword in call.keywords if keyword.arg == "argv"), None
        )
        operation = cli_argv_operation(argv) if argv is not None else None
        if operation is not None:
            return operation
        call_position = (getattr(call, "lineno", 0), getattr(call, "col_offset", 0))
        prior_events: list[tuple[tuple[int, int], str | None]] = []
        for node in nodes:
            position = (getattr(node, "lineno", 0), getattr(node, "col_offset", 0))
            if position >= call_position:
                continue
            patch = cli_argv_patch(node)
            mutation = cli_argv_mutation_operation(node)
            if patch is not None:
                prior_events.append((position, cli_argv_operation(patch)))
            elif is_cli_argv_index_mutation(node):
                prior_events.append((position, mutation))
        return max(prior_events, key=lambda item: item[0])[1] if prior_events else None

    def mcp_tool_imports(statements: list[ast.stmt]) -> dict[str, str]:
        imports: dict[str, str] = {}
        for statement in statements:
            if not isinstance(statement, ast.ImportFrom) or statement.module != "local_ai_hub.mcp_server":
                continue
            for alias in statement.names:
                if alias.name in tools:
                    imports[alias.asname or alias.name] = alias.name
        return imports

    def module_http_request_helpers_for(
        tree: ast.Module,
    ) -> dict[str, tuple[ast.FunctionDef | ast.AsyncFunctionDef, str, str | None, str | None, bool]]:
        module_http_request_helpers: dict[
            str, tuple[ast.FunctionDef | ast.AsyncFunctionDef, str, str | None, str | None, bool]
        ] = {}
        for helper in (node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
            helper_parameters = [
                argument.arg for argument in [*helper.args.posonlyargs, *helper.args.args, *helper.args.kwonlyargs]
            ]
            helper_nodes = scoped_nodes(helper)
            helper_modules, helper_symbols = urllib_request_imports([*tree.body, *helper_nodes])
            helper_request_specs = urllib_request_bindings(helper_nodes, helper_modules, helper_symbols)
            for helper_node in helper_nodes:
                if not isinstance(helper_node, ast.Call) or not is_urllib_request_call(
                    helper_node, "urlopen", helper_modules, helper_symbols
                ) or not urllib_result_returned(helper_node, helper_nodes):
                    continue
                helper_url = helper_node.args[0] if helper_node.args else next(
                    (keyword.value for keyword in helper_node.keywords if keyword.arg == "url"), None
                )
                request_name = helper_url.id if isinstance(helper_url, ast.Name) else None
                spec = urllib_request_binding_at(
                    helper_request_specs,
                    request_name or "",
                    (getattr(helper_node, "lineno", 0), getattr(helper_node, "col_offset", 0)),
                )
                request_call = helper_url if isinstance(helper_url, ast.Call) and is_urllib_request_call(
                    helper_url, "Request", helper_modules, helper_symbols
                ) else None
                if request_name:
                    request_calls = [
                        assignment
                        for assignment in helper_nodes
                        if isinstance(assignment, (ast.Assign, ast.AnnAssign))
                        and (
                            request_name in (
                                set().union(*(target_names(target) for target in assignment.targets))
                                if isinstance(assignment, ast.Assign)
                                else target_names(assignment.target)
                            )
                        )
                        and isinstance(assignment.value, ast.Call)
                        and is_urllib_request_call(
                            assignment.value, "Request", helper_modules, helper_symbols
                        )
                        and (assignment.lineno, assignment.col_offset)
                        < (getattr(helper_node, "lineno", 0), getattr(helper_node, "col_offset", 0))
                    ]
                    if request_calls:
                        request_call = max(
                            request_calls,
                            key=lambda assignment: (assignment.lineno, assignment.col_offset),
                        ).value
                if spec is None and isinstance(helper_url, ast.Name) and helper_url.id in helper_parameters:
                    module_http_request_helpers[helper.name] = (
                        helper, helper_url.id, None, None, True,
                    )
                    continue
                if spec is None or not isinstance(spec[0], ast.Name):
                    continue
                url_parameter = spec[0].id
                if url_parameter not in helper_parameters:
                    continue
                method_node = next(
                    (keyword.value for keyword in request_call.keywords if keyword.arg == "method"), None
                ) if request_call is not None else None
                method_parameter = (
                    method_node.id
                    if isinstance(method_node, ast.Name) and method_node.id in helper_parameters
                    else None
                )
                method_value = spec[1] or (string_value(method_node) if method_node is not None else None)
                if method_parameter and not method_value:
                    positional = [*helper.args.posonlyargs, *helper.args.args]
                    positional_defaults = dict(
                        zip(
                            (argument.arg for argument in positional[-len(helper.args.defaults):]),
                            helper.args.defaults,
                        )
                    ) if helper.args.defaults else {}
                    keyword_defaults = dict(zip(
                        (argument.arg for argument in helper.args.kwonlyargs),
                        helper.args.kw_defaults,
                    ))
                    method_default = positional_defaults.get(
                        method_parameter, keyword_defaults.get(method_parameter)
                    )
                    method_value = string_value(method_default) if method_default is not None else None
                if method_parameter or method_value:
                    module_http_request_helpers[helper.name] = (
                        helper,
                        url_parameter,
                        method_parameter,
                        method_value.upper() if method_value else None,
                        False,
                    )
        return module_http_request_helpers

    for test_file in sorted(tests_root.rglob("test_*.py")):
        if test_file.name == "test_surface_inventory.py":
            continue
        try:
            tree = ast.parse(test_file.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        relative = test_file.relative_to(root).as_posix()
        module_http_request_helpers = module_http_request_helpers_for(tree)
        imported_cli_modules, imported_cli_paths = module_import_bindings(tree.body, "tools.hubctl")
        imported_mcp_modules, imported_mcp_paths = module_import_bindings(
            tree.body, "local_ai_hub.mcp_server"
        )
        for function, class_path in test_functions(tree):
            body_nodes = scoped_nodes(function)
            cli_modules = set(imported_cli_modules)
            local_cli_modules, local_cli_paths = module_import_bindings(body_nodes, "tools.hubctl")
            cli_modules.update(local_cli_modules)
            cli_paths = imported_cli_paths | local_cli_paths
            imported_cli_functions = imported_symbols(tree.body, "tools.hubctl")
            imported_cli_functions.update(imported_symbols(body_nodes, "tools.hubctl"))
            imported_cli_main_names = {
                alias for alias, imported_name in imported_cli_functions.items()
                if imported_name == "main"
            }
            mcp_modules = set(imported_mcp_modules)
            local_mcp_modules, local_mcp_paths = module_import_bindings(
                body_nodes, "local_ai_hub.mcp_server"
            )
            mcp_modules.update(local_mcp_modules)
            mcp_paths = imported_mcp_paths | local_mcp_paths
            http_handler_imports = imported_symbols(tree.body, "local_ai_hub.http_server")
            http_handler_imports.update(imported_symbols(body_nodes, "local_ai_hub.http_server"))
            http_handler_modules, http_handler_paths = module_import_bindings(
                tree.body, "local_ai_hub.http_server"
            )
            local_handler_modules, local_handler_paths = module_import_bindings(
                body_nodes, "local_ai_hub.http_server"
            )
            http_handler_modules.update(local_handler_modules)
            http_handler_paths.update(local_handler_paths)
            http_handler_types = {
                alias for alias, imported_name in http_handler_imports.items()
                if imported_name == "Handler"
            }
            http_handler_types.update(f"{module}.Handler" for module in http_handler_modules | http_handler_paths)
            imported_mcp_tools = mcp_tool_imports(tree.body)
            imported_mcp_tools.update(mcp_tool_imports(body_nodes))
            asserted = asserted_calls(body_nodes)
            if not asserted and not any(isinstance(node, ast.Assert) for node in body_nodes):
                continue
            selector = f"{relative}::{'::'.join((*class_path, function.name))}"
            calls = [node for node in body_nodes if isinstance(node, ast.Call)]
            literals = {value for node in body_nodes if (value := string_value(node)) is not None}

            for call in calls:
                if id(call) not in asserted:
                    continue
                tool = imported_mcp_tools.get(call.func.id, "") if isinstance(call.func, ast.Name) else ""
                protocol_arguments: dict[str, str | None] = {}
                if (
                    not tool and isinstance(call.func, ast.Attribute) and call.func.attr == "call_tool"
                    and isinstance(call.func.value, ast.Attribute) and call.func.value.attr == "mcp"
                    and (
                        isinstance(call.func.value.value, ast.Name)
                        and call.func.value.value.id in mcp_modules
                        or dotted_name(call.func.value.value) in mcp_paths
                    )
                    and call.args
                ):
                    protocol_tool = string_value(call.args[0])
                    if protocol_tool in tools:
                        tool = protocol_tool
                        if len(call.args) > 1 and isinstance(call.args[1], ast.Dict):
                            protocol_arguments = {
                                key_value: string_value(value)
                                for key, value in zip(call.args[1].keys, call.args[1].values)
                                if (key_value := string_value(key)) is not None
                            }
                if (
                    not tool and isinstance(call.func, ast.Attribute) and call.func.attr in tools
                    and (
                        isinstance(call.func.value, ast.Name) and call.func.value.id in mcp_modules
                        or dotted_name(call.func.value) in mcp_paths
                    )
                ):
                    tool = call.func.attr
                if tool not in tools:
                    continue
                add(f"MCP tool::{tool}", selector)
                keyword_values = {
                    keyword.arg: string_value(keyword.value)
                    for keyword in call.keywords if keyword.arg
                }
                action = keyword_values.get("action") or protocol_arguments.get("action")
                detail = keyword_values.get("detail") or protocol_arguments.get("detail")
                if action:
                    alias = aliases.get(tool, {}).get(action)
                    if alias:
                        add(f"MCP action alias {tool}::{action} (alias for {alias})", selector)
                    else:
                        known_actions = set(inventory.get("mcp_actions", {}).get(tool, []))
                        known_actions.update(inventory.get("conditional_mcp_actions", {}).get(tool, {}))
                        if action in known_actions:
                            add(f"MCP action {tool}::{action}", selector)
                        elif any(
                            item["name"] == tool and action in item.get("runtime_action_literals", [])
                            for item in inventory.get("mcp_tools", [])
                        ):
                            add(f"MCP action schema gap {tool}::{action}", selector)
                if detail:
                    advertised_details = set(inventory.get("mcp_variants", {}).get(tool, {}).get("detail", []))
                    runtime_details = next(
                        (set(item.get("runtime_detail_literals", [])) for item in inventory.get("mcp_tools", []) if item["name"] == tool),
                        set(),
                    )
                    if detail in advertised_details:
                        add(f"MCP detail {tool}::{detail}", selector)
                    elif detail in runtime_details:
                        add(f"MCP detail schema gap {tool}::{detail}", selector)

            receivers = hubclient_receivers(body_nodes, function)
            for call in calls:
                if id(call) not in asserted or not isinstance(call.func, ast.Attribute):
                    continue
                method = call.func.attr
                if method not in client_methods or not isinstance(call.func.value, ast.Name):
                    continue
                if call.func.value.id not in receivers:
                    continue
                add(f"HubClient method::{method}", selector)
                method_targets = [
                    target for target in inventory["client_targets"]
                    if target["client_method"] == method
                ]
                for target in method_targets:
                    target_path = target["path"].split("?", 1)[0]
                    same_method_target = [
                        candidate for candidate in method_targets
                        if candidate["method"] == target["method"]
                        and candidate["path"] == target["path"]
                    ]
                    if len(same_method_target) == 1 and (
                        target_path in literals or len(method_targets) == 1
                    ):
                        target_name = f"{target['method']} {target['path']}"
                        add(f"HubClient target::{target_name}::{method}", selector)

            http_receivers = http_client_receivers(body_nodes, function)
            http_request_helpers: dict[str, tuple[str, int]] = {}
            urllib_modules, urllib_symbols = urllib_request_imports([*tree.body, *body_nodes])
            request_specs = urllib_request_bindings(body_nodes, urllib_modules, urllib_symbols)
            for helper in (node for node in function.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
                helper_parameters = [
                    argument.arg for argument in [*helper.args.posonlyargs, *helper.args.args, *helper.args.kwonlyargs]
                ]
                helper_nodes = scoped_nodes(helper)
                helper_modules, helper_symbols = urllib_request_imports([*tree.body, *body_nodes, *helper_nodes])
                helper_request_specs = urllib_request_bindings(helper_nodes, helper_modules, helper_symbols)
                for helper_node in helper_nodes:
                    if not isinstance(helper_node, ast.Call) or not is_urllib_request_call(
                        helper_node, "urlopen", helper_modules, helper_symbols
                    ):
                        continue
                    helper_url = helper_node.args[0] if helper_node.args else next(
                        (keyword.value for keyword in helper_node.keywords if keyword.arg == "url"), None
                    )
                    if helper_url is None:
                        continue
                    request_name = helper_url.id if isinstance(helper_url, ast.Name) else None
                    spec = urllib_request_binding_at(
                        helper_request_specs,
                        request_name or "",
                        (getattr(helper_node, "lineno", 0), getattr(helper_node, "col_offset", 0)),
                    )
                    if isinstance(helper_url, ast.Call) and is_urllib_request_call(
                        helper_url, "Request", helper_modules, helper_symbols
                    ):
                        spec = urllib_request_spec(helper_url)
                    if (
                        spec is None or not isinstance(spec[0], ast.JoinedStr) or not spec[1]
                        or not urllib_result_returned(helper_node, helper_nodes)
                    ):
                        continue
                    path_parameters = {
                        name for part in spec[0].values if isinstance(part, ast.FormattedValue)
                        for name in names_in(part.value) if name in helper_parameters
                    }
                    if len(path_parameters) == 1:
                        http_request_helpers[helper.name] = (spec[1].upper(), helper_parameters.index(next(iter(path_parameters))))
            pairs: list[tuple[str, str, ast.Call]] = []
            for call in calls:
                if id(call) not in asserted:
                    continue
                call_name = (
                    call.func.attr if isinstance(call.func, ast.Attribute)
                    else call.func.id if isinstance(call.func, ast.Name)
                    else ""
                )
                method: str | None = None
                url_node: ast.AST | None = None
                module_helper = module_http_request_helpers.get(call_name)
                if module_helper is not None and isinstance(call.func, ast.Name):
                    helper, url_parameter, method_parameter, default_method, receives_request = module_helper
                    positional_parameters = [
                        argument.arg for argument in [*helper.args.posonlyargs, *helper.args.args]
                    ]

                    def helper_argument(name: str) -> ast.AST | None:
                        if name in positional_parameters:
                            index = positional_parameters.index(name)
                            if index < len(call.args):
                                return call.args[index]
                        return next((keyword.value for keyword in call.keywords if keyword.arg == name), None)

                    url_node = helper_argument(url_parameter)
                    method_node = helper_argument(method_parameter) if method_parameter else None
                    method = string_value(method_node) if method_node is not None else default_method
                    if receives_request:
                        request_spec = (
                            urllib_request_binding_at(
                                request_specs,
                                url_node.id,
                                (getattr(call, "lineno", 0), getattr(call, "col_offset", 0)),
                            )
                            if isinstance(url_node, ast.Name)
                            else urllib_request_spec(url_node)
                            if isinstance(url_node, ast.Call)
                            and is_urllib_request_call(url_node, "Request", urllib_modules, urllib_symbols)
                            else None
                        )
                        if request_spec is None:
                            continue
                        url_node, request_method = request_spec
                        method = request_method or method
                    url_text = static_url_text(
                        url_node,
                        body_nodes,
                        (getattr(call, "lineno", 0), getattr(call, "col_offset", 0)),
                    ) if url_node is not None else ""
                    path = url_path(url_text) if url_text else None
                    if method and path:
                        pairs.append((method.upper(), path, call))
                elif is_urllib_request_call(call, "urlopen", urllib_modules, urllib_symbols):
                    request_arg = call.args[0] if call.args else next(
                        (keyword.value for keyword in call.keywords if keyword.arg == "url"), None
                    )
                    if request_arg is None:
                        continue
                    request_spec = (
                        urllib_request_binding_at(
                            request_specs, request_arg.id,
                            (getattr(call, "lineno", 0), getattr(call, "col_offset", 0)),
                        ) if isinstance(request_arg, ast.Name)
                        else urllib_request_spec(request_arg)
                        if isinstance(request_arg, ast.Call) and is_urllib_request_call(
                            request_arg, "Request", urllib_modules, urllib_symbols
                        )
                        else None
                    )
                    if request_spec is not None:
                        url_node, method = request_spec
                    else:
                        url_node = request_arg
                        data_node = call.args[1] if len(call.args) > 1 else next(
                            (keyword.value for keyword in call.keywords if keyword.arg == "data"), None
                        )
                        if data_node is None or isinstance(data_node, ast.Constant) and data_node.value is None:
                            method = "GET"
                        elif isinstance(data_node, ast.Constant):
                            method = "POST"
                elif call_name == "request":
                    if call.args:
                        method_value = string_value(call.args[0])
                        method = method_value.upper() if method_value else None
                    url_node = call.args[1] if len(call.args) > 1 else None
                    for keyword in call.keywords:
                        if keyword.arg == "method":
                            method_value = string_value(keyword.value)
                            method = method_value.upper() if method_value else method
                        elif keyword.arg in {"url", "path"}:
                            url_node = keyword.value
                elif call_name in http_request_helpers:
                    method, argument_index = http_request_helpers[call_name]
                    url_node = call.args[argument_index] if len(call.args) > argument_index else None
                elif call_name in {"_get", "_post", "_put", "_patch", "_delete"}:
                    method = call_name[1:].upper()
                    url_node = call.args[0] if call.args else None
                elif (
                    call_name in {"get", "post", "put", "patch", "delete"}
                    and isinstance(call.func, ast.Attribute)
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id in http_receivers
                ):
                    method = call_name.upper()
                    url_node = call.args[0] if call.args else None

                if method in HTTP_METHODS.values() and url_node is not None:
                    value = string_value(url_node)
                    if not value:
                        value = static_url_text(
                            url_node,
                            body_nodes,
                            (getattr(call, "lineno", 0), getattr(call, "col_offset", 0)),
                        )
                    path = url_path(value) if value else None
                    if path:
                        pairs.append((method, path, call))

            for method, path, call in pairs:
                if id(call) not in asserted:
                    continue
                for route in inventory["http_routes"]:
                    if route["path"] == "/api/context/pack":
                        continue
                    if route_matches(method, path, route):
                        add(f"HTTP {route['method']}::{route['path']}", selector)

            for method, path in direct_http_handler_pairs(body_nodes, function, http_handler_types):
                for route in inventory["http_routes"]:
                    if route["path"] == "/api/context/pack":
                        continue
                    if route_matches(method, path, route):
                        add(f"HTTP {route['method']}::{route['path']}", selector)

            for call in calls:
                if id(call) not in asserted or not is_cli_main(
                    call, cli_modules, cli_paths, imported_cli_main_names
                ):
                    continue
                operation = cli_operation_for_call(call, body_nodes)
                if operation in inventory["cli_operations"]:
                    add(f"CLI operation::{operation}", selector)

    return {key: sorted(selectors) for key, selectors in sorted(links.items())}

def collect_inventory(root: Path | str) -> dict[str, Any]:
    root = Path(root).resolve()
    modules = {key: _read_module(root, key) for key in SOURCE_FILES}
    contract_path = root / "src" / "local_ai_hub" / "operation_contracts.py"
    contract_aliases = (
        _type_alias_literals(ast.parse(contract_path.read_text(encoding="utf-8"), filename=str(contract_path)))
        if contract_path.is_file()
        else {}
    )
    source_mcp_tools, mcp_action_aliases, conditional_mcp_actions = _extract_mcp(
        modules["mcp"][1], SOURCE_FILES["mcp"], contract_aliases
    )
    source_tools_by_name = {item["name"]: item for item in source_mcp_tools}
    mcp_schemas, mcp_schema_evidence, schema_errors, disabled_mcp_tools = _generated_mcp_schemas(root)
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
        operation_metadata = schema.get("x-operation-contract", {})
        if not isinstance(operation_metadata, dict):
            operation_metadata = {}
        output_schema = schema.get(
            "outputSchema",
            schema.get("output_schema", "generator omits outputSchema; result shape remains action-dependent"),
        )
        operation_contract = schema.get("x-operation-contract", {})
        if not isinstance(operation_contract, dict):
            operation_contract = {}
        dispatch_symbols = (source_tool or {}).get("handler_symbols", [])
        dispatch_effects = (
            f"dispatches through {', '.join(dispatch_symbols)}; transitive side effects unverified"
            if dispatch_symbols
            else f"invokes MCP handler {name}; transitive side effects unverified"
        )
        backend_gate = operation_metadata.get("feature_gate") or (source_tool or {}).get("registration_condition") or "generated schema for active configuration"
        mcp_contracts[name] = {
            "request_payload": {"schema": input_schema, "required": list(parameters.get("required", [])) if isinstance(parameters, dict) else [], "defaults": defaults},
            "response_contract": output_schema,
            "status_codes": "not applicable: MCP tool protocol",
            "timeout": operation_metadata.get("timeout", "no timeout is declared in the generated MCP schema; effective caller budget unverified"),
            "operation_side_effects": operation_metadata.get("actions") or dispatch_effects,
            "backend_availability": f"{backend_gate}; runtime backend health unverified",
            "input_schema": input_schema,
            "output_schema": output_schema,
            "defaults": defaults,
            "required": list(parameters.get("required", [])) if isinstance(parameters, dict) else [],
            "feature_gate": backend_gate,
            "operation_contract": operation_metadata,
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
                "dispatch_actions": (source_tool or {}).get("dispatch_actions", []),
                "runtime_action_literals": (source_tool or {}).get("action_literals", []),
                "runtime_detail_literals": (source_tool or {}).get("detail_literals", []),
                "registration_condition": (source_tool or {}).get("registration_condition"),
                "evidence_status": "conditional" if (source_tool or {}).get("registration_condition") else "confirmed",
            }
        )
        if source_tool:
            for parameter in ("action", "detail"):
                for action in variants.get(parameter, []):
                    handled = action in source_tool.get("dispatch_actions", []) or any(
                        action.startswith(prefix) for prefix in source_tool.get("dispatch_prefixes", [])
                    ) or source_tool.get("delegated_dispatch") or action in source_tool.get("default_actions", []) or any(
                        action in variants.get(parameter, [])
                        for parameter in source_tool.get("action_alias_parameters", [])
                    )
                    if parameter == "action" and not handled:
                        drift.append(f"missing MCP action handler {name}:{action}")

    for name, source_tool in sorted(source_tools_by_name.items()):
        if name in mcp_schemas:
            continue
        conditional = source_tool.get("registration_condition")
        if name in disabled_mcp_tools:
            conditional = conditional or "disabled by active feature configuration"
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
    route_registry_path = root / "src/local_ai_hub/http_route_registry.py"
    if route_registry_path.is_file():
        registry_tree = ast.parse(route_registry_path.read_text(encoding="utf-8"), filename=str(route_registry_path))
        source_http_routes.extend(
            _extract_registered_http(registry_tree, "src/local_ai_hub/http_route_registry.py")
        )
    drift.extend(_dynamic_route_registry_drift(source_http_routes))
    http_routes = _merge_dynamic_routes(source_http_routes)
    client_methods, client_targets = _extract_client(modules["client"][1], SOURCE_FILES["client"])
    manifests, missing_manifests = _extract_manifests(modules["generator"][1], root)
    manifest_paths = {item["path"] for item in manifests}
    drift.extend(f"missing generated manifest {name}" for name in missing_manifests)
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
        "behavioral_test_links": _behavioral_test_links(root, {
            "mcp_tools": mcp_tools,
            "mcp_action_aliases": mcp_action_aliases,
            "client_methods": client_methods,
            "client_targets": client_targets,
            "http_routes": http_routes,
            "mcp_actions": mcp_actions,
            "conditional_mcp_actions": conditional_mcp_actions,
            "mcp_variants": mcp_variants,
            "cli_operations": cli_contract["operations"],
        }),
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

_OPERATION_OWNER_TASKS = frozenset(f"T{number:02d}" for number in range(1, 22))
_MCP_TOOL_OWNER_TASK = {
    "local_ai_status": "T18",
    "local_ai_repo": "T10",
    "local_ai_task": "T12",
    "local_ai_coord": "T08",
    "local_ai_rag": "T11",
    "local_ai_artifact": "T14",
    "local_ai_work": "T16",
}


def _http_operation_owner_task(path: str) -> str:
    normalized = path.split(" ", 1)[-1].lower()
    if normalized == "/api/context/pack":
        return "T14"
    if normalized == "/api/search":
        return "T21"
    if "/benchmark" in normalized or normalized.endswith("/benchmark"):
        return "T02"
    if "/release" in normalized or "/selftest" in normalized:
        return "T20"
    if normalized.startswith("/api/agent-state/memory") or normalized.startswith(("/api/memory", "/api/leases")):
        return "T05"
    if normalized.startswith(("/api/agent-state/verification", "/api/evidence", "/api/worktrees")):
        return "T09"
    if normalized.startswith("/api/agent-state") or normalized.startswith("/api/coord"):
        return "T08"
    if normalized.startswith(("/api/project-config", "/api/project/", "/api/path-hints")):
        return "T21"
    if normalized.startswith(("/api/repo", "/api/code", "/api/git", "/api/ast", "/api/preprocess", "/api/affected_tests", "/api/topology")):
        return "T10"
    if normalized.startswith(("/api/rag", "/api/embed", "/api/rerank", "/api/ingest")):
        return "T11"
    if normalized.startswith(("/api/models", "/api/model", "/api/router", "/api/inference", "/api/ollama", "/api/llama", "/api/hardware", "/api/scheduler")):
        return "T12"
    if normalized.startswith(("/api/jobs", "/api/conversation", "/api/async", "/api/task")):
        return "T13"
    if normalized.startswith(("/api/artifact", "/api/context", "/api/cache", "/api/token", "/api/ledger")):
        return "T14"
    if normalized.startswith(("/api/command", "/api/stream", "/api/speculative")):
        return "T15"
    if normalized.startswith(("/api/work", "/api/orchestrator")):
        return "T16"
    if normalized.startswith(("/api/browser", "/api/vision", "/api/audio", "/api/transcri", "/api/generate")):
        return "T17"
    if normalized.startswith(("/api/status", "/api/health", "/api/queue", "/api/telemetry", "/api/debug", "/api/live", "/api/adoption", "/api/mode", "/api/maintenance", "/api/capabilities", "/api/metrics", "/api/db", "/dashboard")):
        return "T18"
    if normalized.startswith(("/api/install", "/api/setup", "/api/doctor", "/api/config", "/api/bundle", "/api/cli")):
        return "T19"
    return "T04"




def _operation_owner_task(finding: dict[str, Any]) -> str | None:
    explicit = finding.get("owner_task")
    if explicit in _OPERATION_OWNER_TASKS:
        return explicit
    surface = str(finding.get("surface", ""))
    name = str(finding.get("name", ""))
    if surface == "MCP tool" or surface.startswith("MCP action schema gap "):
        return "T03"
    if surface.startswith("MCP detail "):
        return "T08" if name.lower() == "agent_state" else "T18"
    if surface.startswith("MCP action "):
        family = surface.removeprefix("MCP action ").removeprefix("alias ")
        return _mcp_action_owner_task(family, name)
    if surface.startswith("HTTP ") or surface == "HubClient target":
        return _http_operation_owner_task(name)
    if surface == "HubClient method":
        return "T04"
    if surface == "CLI operation":
        action = name.lower().replace("_", "-")
        if "benchmark" in action:
            return "T02"
        if any(word in action for word in ("release", "selftest", "self-test")):
            return "T20"
        if action in {"status", "dashboard", "logs", "service-status", "watch"}:
            return "T18"
        if action == "memory":
            return "T05"
        if action in {"agent-state", "tasks"}:
            return "T08"
        if action in {"clean", "cleanup", "start", "stop", "restart", "pause", "resume"}:
            return "T06"
        return "T19"
    if surface == "Generated manifest":
        return "T19"
    return None

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
    "scope_boundary": "operation-specific project/task/session confinement was not extracted; scope boundary is unverified",
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




def _mcp_action_owner_task(tool_name: str, action: str) -> str:
    canonical = re.sub(r"\s+\(alias for .+\)$", "", action).lower()
    if tool_name == "local_ai_status":
        return "T08" if canonical == "agent_state" else "T18"
    if tool_name == "local_ai_repo":
        if canonical == "search":
            return "T21"
        if canonical in {"context_budget", "artifact", "artifacts", "cache"}:
            return "T14"
        if canonical in {"project_config", "path_hints"}:
            return "T21"
        return "T10"
    if tool_name == "local_ai_task":
        if any(word in canonical for word in ("conversation", "async", "wait", "continue", "cancel", "resume")):
            return "T13"
        if any(word in canonical for word in ("vision", "transcribe", "audio", "image")):
            return "T17"
        if any(word in canonical for word in ("benchmark", "evaluation", "candidate")):
            return "T02"
        return "T12"
    if tool_name == "local_ai_coord":
        if any(word in canonical for word in ("verify", "receipt", "evidence", "worktree", "completion")):
            return "T09"
        return "T08"
    return _MCP_TOOL_OWNER_TASK.get(tool_name, "T03")




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
        behavioral_test_ids = finding.get("behavioral_test_ids") or []
        metadata_only = not behavioral_test_ids and not finding.get("test_ids")
        test_ids = behavioral_test_ids or finding.get("test_ids") or [
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
            "owner_task": _operation_owner_task(finding) or task_id,
            "handler": _normalize_unverified(finding.get("handler") or finding["name"], "handler"),
            "fixtures": (
                behavioral_test_ids
                if behavioral_test_ids
                else _normalize_unverified(finding.get("fixtures") or ["not inventoried"], "fixtures")
            ),
            "access_classification": finding.get("access_classification") or _access_classification(finding["surface"]),
            "cache_key": _normalize_unverified(finding.get("cache_key") or "not statically identified", "cache_key"),
            "scope_boundary": _normalize_unverified(finding.get("scope_boundary") or "not statically identified", "scope_boundary"),
            "provenance": finding.get("provenance") or evidence,
            "test_ids": test_ids,
            "test_coverage": finding.get("test_coverage") or (
                "metadata only; operation behavior unverified"
                if metadata_only
                else "behavioral tests linked; coverage bounded to cited assertions"
                if behavioral_test_ids
                else "linked tests; operation behavior unverified"
            ),
            "behavioral_disposition": (
                "asserted behavior test linked"
                if behavioral_test_ids
                else "test selector linked; behavior unverified"
                if finding.get("test_ids")
                else "no asserted operation test linked; behavior unverified"
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
        conditional_gates = route.get("conditional_gates", [])
        condition = "; ".join(conditional_gates) or route.get("classification")
        findings.append(
            {
                "surface": f"HTTP {route['method']}",
                "name": route["path"],
                "condition": condition,
                "evidence_status": route.get("evidence_status") or ("conditional" if condition else "confirmed"),
                "owner": SOURCE_FILES["http"] if route.get("classification") is None else "tools/surface_inventory.py",
                "owner_task": route.get("owner_task"),
                "handler": route.get("handler"),
                "contract": route.get("contract", {}),
                "acceptance": "HTTP method and path resolve to a handler or registered dynamic route.",
                "evidence": [route["evidence"]],
            }
        )
    for tool_name, actions in inventory["mcp_actions"].items():
        conditional = inventory["conditional_mcp_actions"].get(tool_name, {})
        tool_contract = inventory["mcp_contracts"].get(tool_name, {})
        operation_contract = tool_contract.get("operation_contract", {})
        operation_actions = operation_contract.get("actions", {})
        if not isinstance(operation_actions, dict):
            operation_actions = {}
        for action in actions:
            gate = conditional.get(action)
            action_contract = operation_actions.get(action, {})
            if not isinstance(action_contract, dict):
                action_contract = {}
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
                        "response_contract": tool_contract.get("output_schema", "not declared"),
                        "status_codes": "not applicable: MCP tool protocol",
                        "timeout": inventory["mcp_contracts"].get(tool_name, {}).get("timeout", "not statically identified"),
                        "operation_side_effects": action_contract.get(
                            "side_effects",
                            tool_contract.get("operation_side_effects", "MCP action dispatch effects unverified"),
                        ),
                        "backend_availability": (
                            f"conditional feature gate {gate}; runtime backend health unverified"
                            if gate
                            else inventory["mcp_contracts"].get(tool_name, {}).get("backend_availability", "runtime backend health unverified")
                        ),
                        "feature_gates": [gate] if gate else [],
                        "input_property_schema": inventory["mcp_contracts"].get(tool_name, {}).get("input_schema", {}).get("properties", {}).get("action", {}),
                        "required": inventory["mcp_contracts"].get(tool_name, {}).get("required", []),
                        "http_target": inventory["mcp_contracts"].get(tool_name, {}).get("http_target", "not statically identified"),
                        "required_fields": list(action_contract.get("required", ())),
                        "idempotent": bool(action_contract.get("idempotent", False)),
                        "retry_safe": bool(action_contract.get("retry_safe", False)),
                        "automatic_replay": bool(action_contract.get("automatic_replay", False)),
                        "projection": operation_contract.get("projection", "unverified"),
                    },
                    "acceptance": "Generated MCP JSON schema action enum advertises this action.",
                    "evidence_status": "conditional" if gate else "confirmed",
                    "evidence": [
                        inventory["mcp_schema_evidence"].get(tool_name, SOURCE_FILES["generator"]),
                        "src/local_ai_hub/operation_contracts.py:OPERATION_CONTRACTS",
                    ],
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
    for tool in inventory["mcp_tools"]:
        tool_name = tool["name"]
        advertised = set(inventory["mcp_actions"].get(tool_name, []))
        conditional = set(inventory["conditional_mcp_actions"].get(tool_name, {}))
        for action in tool.get("runtime_action_literals", []):
            if action in advertised or action in conditional:
                continue
            findings.append(
                {
                    "surface": f"MCP action schema gap {tool_name}",
                    "name": action,
                    "condition": "runtime dispatch action is absent from the generated action enum",
                    "owner": SOURCE_FILES["mcp"],
                    "handler": tool.get("handler"),
                    "contract": {
                        "action": action,
                        "request_payload": {"action": action},
                        "input_property_schema": inventory["mcp_contracts"].get(tool_name, {}).get("input_schema", {}).get("properties", {}).get("action", {}),
                        "schema_gap": "handler accepts this action but the generated action enum does not advertise it",
                        "response_contract": inventory["mcp_contracts"].get(tool_name, {}).get("output_schema", "not declared"),
                        "status_codes": "not applicable: MCP tool protocol",
                        "operation_side_effects": "runtime dispatch branch exists; action effects need operation-specific verification",
                        "backend_availability": "runtime backend health unverified",
                    },
                    "acceptance": "Source handler dispatches this action, while the generated MCP input schema omits it.",
                    "evidence_status": "confirmed",
                    "evidence": [tool["evidence"], tool["schema_evidence"]],
                }
            )
    for tool in inventory["mcp_tools"]:
        tool_name = tool["name"]
        advertised = set(inventory.get("mcp_variants", {}).get(tool_name, {}).get("detail", []))
        for detail in tool.get("runtime_detail_literals", []):
            if detail in advertised:
                continue
            findings.append(
                {
                    "surface": f"MCP detail schema gap {tool_name}",
                    "name": detail,
                    "condition": "runtime detail dispatch is absent from the generated detail enum",
                    "owner": SOURCE_FILES["mcp"],
                    "handler": tool.get("handler"),
                    "contract": {
                        "detail": detail,
                        "request_payload": {"detail": detail},
                        "input_property_schema": inventory["mcp_contracts"].get(tool_name, {}).get("input_schema", {}).get("properties", {}).get("detail", {}),
                        "schema_gap": "handler accepts this detail but the generated detail enum does not advertise it",
                        "response_contract": inventory["mcp_contracts"].get(tool_name, {}).get("output_schema", "not declared"),
                        "status_codes": "not applicable: MCP tool protocol",
                        "operation_side_effects": "runtime detail branch exists; detail effects need operation-specific verification",
                        "backend_availability": "runtime backend health unverified",
                    },
                    "acceptance": "Source handler dispatches this detail, while the generated MCP input schema omits it.",
                    "evidence_status": "confirmed",
                    "evidence": [tool["evidence"], tool["schema_evidence"]],
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
    behavioral_links = inventory.get("behavioral_test_links", {})
    for finding in findings:
        key = f"{finding['surface']}::{finding['name']}"
        if finding["surface"] == "HubClient target":
            key += f"::{finding.get('handler', '')}"
        test_ids = behavioral_links.get(key)
        if test_ids:
            finding["behavioral_test_ids"] = test_ids
    return findings


def render_coverage(inventory: dict[str, Any], task_id: str | None = None) -> str:
    rows = coverage_rows(_findings(inventory), task_id)
    check_command = "python tools/surface_inventory.py --check"
    if task_id:
        check_command += f" --task-id {task_id}"
    lines = [
        "# API surface coverage",
        "",
        "Deterministic source inventory. Status describes static evidence, not runtime health or asserted behavior. Full contracts, fixtures, provenance, and coverage details live in `API_COVERAGE.json`.",
        f"Reproduce with `{check_command}`.",
        f"<!-- coverage-task-id: {task_id or ''} -->",
        "",
        "| Surface | Name | Evidence status | Owner | Operation ID |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        cells = (row["surface"], row["name"], row["evidence_status"], row["owner"], row["operation_id"])
        lines.append("| " + " | ".join(_coverage_markdown_cell(value) for value in cells) + " |")
    lines.extend(["", "Orphan client targets, unhandled generated MCP actions, source-only MCP tools, dynamic route registry entries, and generated schemas without source registrations fail `--check`.", ""])
    if inventory["drift"]:
        lines.extend(["## Detected drift", ""])
        lines.extend(f"- `{item}`" for item in inventory["drift"])
        lines.append("")
    return "\n".join(lines)


def _coverage_markdown_cell(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def render_coverage_artifact(inventory: dict[str, Any], task_id: str | None = None) -> str:
    rows = coverage_rows(_findings(inventory), task_id)
    artifact = {
        "schema_version": 1,
        "description": "Deterministic static API surface coverage; not runtime or behavioral verification.",
        "task_id": task_id,
        "coverage_rows": rows,
    }
    return json.dumps(artifact, separators=(",", ":"), sort_keys=True) + "\n"


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
    marker = re.search(r"<!-- coverage-task-id: ([^>]*) -->", text)
    if marker:
        return marker.group(1).strip() or None
    lines = text.splitlines()
    start = next((index for index, line in enumerate(lines) if line.startswith("| Surface |")), None)
    if start is None or "Task ID" not in [cell.strip() for cell in lines[start].strip("|").split("|")]:
        return None
    first_data = next((line for line in lines[start + 2 :] if line.startswith("|")), None)
    if first_data is None:
        return None
    cell = first_data.rsplit("|", 2)[1].strip().strip("`")
    return cell or None


def _coverage_artifact_task_id(text: str) -> str | None:
    try:
        artifact = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None
    task_id = artifact.get("task_id") if isinstance(artifact, dict) else None
    return task_id if isinstance(task_id, str) and task_id else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--check",
        action="store_true",
        help="check human and structured coverage artifact drift without writing files",
    )
    parser.add_argument("--write-doc", action="store_true", help="write human and structured coverage artifacts from current AST evidence")
    parser.add_argument("--task-id", help="record task identifier when one was assigned")
    args = parser.parse_args(argv)
    if args.check and args.write_doc:
        parser.error("--check and --write-doc cannot be used together")

    inventory = collect_inventory(args.root)
    doc_path = args.root / "docs" / "API_COVERAGE.md"
    artifact_path = args.root / "docs" / "API_COVERAGE.json"
    if args.check:
        current_text = doc_path.read_text(encoding="utf-8") if doc_path.is_file() else ""
        current_artifact = artifact_path.read_text(encoding="utf-8") if artifact_path.is_file() else ""
        task_id = args.task_id or _coverage_task_id(current_text) or _coverage_artifact_task_id(current_artifact)
        expected_document = render_coverage(inventory, task_id)
        expected_artifact = render_coverage_artifact(inventory, task_id)
        coverage_matches = current_text == expected_document
        artifact_matches = current_artifact == expected_artifact
        if not coverage_matches:
            inventory["drift"].append("rendered coverage document differs from docs/API_COVERAGE.md")
        if not artifact_matches:
            inventory["drift"].append("rendered coverage artifact differs from docs/API_COVERAGE.json")
        inventory["drift"] = sorted(inventory["drift"])
        print(json.dumps({
            "success": not inventory["drift"],
            "coverage_matches": coverage_matches,
            "artifact_matches": artifact_matches,
            "coverage_rows": len(coverage_rows(_findings(inventory), task_id)),
            "drift": inventory["drift"],
        }, sort_keys=True))
        return 1 if inventory["drift"] else 0
    if args.write_doc:
        doc_path.write_text(render_coverage(inventory, args.task_id), encoding="utf-8")
        artifact_path.write_text(render_coverage_artifact(inventory, args.task_id), encoding="utf-8")
        print(json.dumps({
            "success": not inventory["drift"],
            "written": doc_path.relative_to(args.root).as_posix(),
            "written_artifact": artifact_path.relative_to(args.root).as_posix(),
            "coverage_rows": len(coverage_rows(_findings(inventory), args.task_id)),
            "drift": inventory["drift"],
        }, sort_keys=True))
        return 0
    print(json.dumps(inventory, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

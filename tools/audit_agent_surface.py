"""Source-bound audit inventory. Unreviewed operations fail the coverage gate.

Unlike an installed/cached catalog this reads this checkout. It does not start
the application, probe hardware or run inference. Imports only authored registries.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
import sys


def _schema_fields(schema: object, prefix: str = "") -> set[str]:
    if not isinstance(schema, dict):
        return set()
    fields = set()
    for key, item in schema.get("properties", {}).items():
        path = prefix + key
        fields.add(path)
        fields.update(_schema_fields(item, path + "."))
    for key in ("anyOf", "oneOf", "allOf"):
        for item in schema.get(key, []):
            fields.update(_schema_fields(item, prefix))
    fields.update(_schema_fields(schema.get("items"), prefix + "[]."))
    return fields


def _response_facts(nodes: list[ast.AST], methods: dict | None = None, seen: frozenset = frozenset()) -> dict:
    fields, producers, actions = set(), set(), set()
    for root in nodes:
        for node in ast.walk(root):
            if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id in {"action", "sync_action"}:
                for comparator in node.comparators:
                    actions.update(item.value for item in ast.walk(comparator) if isinstance(item, ast.Constant) and isinstance(item.value, str))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                name = node.func.attr
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "self" and (name.startswith("_handle") or name == "_task_budget_increase"):
                    producers.add("self." + name)
                    if methods and name in methods and name not in seen:
                        nested = _response_facts([methods[name]], methods, seen | {name})
                        fields.update(nested["literal_response_fields"])
                        producers.update(nested["response_producers"])
                        actions.update(nested["action_literals"])
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "_send" and len(node.args) > 1:
                result = node.args[1]
                if isinstance(result, ast.Call):
                    producers.add(ast.unparse(result.func))
                elif isinstance(result, ast.Name):
                    producers.add("local:" + result.id)
                for item in ast.walk(result):
                    if isinstance(item, ast.Dict):
                        fields.update(key.value for key in item.keys if isinstance(key, ast.Constant) and isinstance(key.value, str))
            # Include fields assembled into response variables before _send.
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Dict):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(isinstance(target, ast.Name) and target.id in {"response", "result", "data", "report", "page"} for target in targets):
                    fields.update(key.value for key in node.value.keys if isinstance(key, ast.Constant) and isinstance(key.value, str))
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Call):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(isinstance(target, ast.Name) and target.id in {"response", "result", "data", "report", "page"} for target in targets):
                    producers.add(ast.unparse(node.value.func))
            if isinstance(node, ast.Return):
                if isinstance(node.value, ast.Call):
                    producers.add(ast.unparse(node.value.func))
                if isinstance(node.value, ast.Dict):
                    fields.update(key.value for key in node.value.keys if isinstance(key, ast.Constant) and isinstance(key.value, str))
    return {"literal_response_fields": sorted(fields), "response_producers": sorted(producers), "action_literals": sorted(actions)}


def _merge_response_facts(row: dict, facts: dict) -> None:
    # A later comparison inside a preflight BoolOp has no own branch body.
    # It must not erase a real dispatcher's already discovered output fields.
    for key in ("literal_response_fields", "response_producers", "action_literals"):
        row[key] = sorted(set(row.get(key, [])) | set(facts.get(key, [])))


def collect_surface(root: Path) -> dict[str, dict]:
    sys.path.insert(0, str(root / "src"))
    from local_ai_hub.operation_contracts import OPERATION_CONTRACTS, operation_actions, operation_output_schema
    from local_ai_hub.http_route_registry import POST_ROUTE_REGISTRY, GET_ROUTE_HANDLER_BOUNDARIES, POST_ROUTE_HANDLER_BOUNDARIES

    rows = {}
    for tool, contract in OPERATION_CONTRACTS.items():
        for action in operation_actions(tool):
            rows[f"MCP {tool}.{action}"] = {
                "source": "src/local_ai_hub/operation_contracts.py",
                "selector": contract["selector_field"],
                "output_schema_fields": sorted(_schema_fields(operation_output_schema(tool, action))),
            }
    for rule in POST_ROUTE_REGISTRY:
        for path in rule.paths:
            rows[f"POST {path}"] = {"source": "src/local_ai_hub/http_route_registry.py", "handler": rule.route_id}

    tree = ast.parse((root / "src/local_ai_hub/http_server.py").read_text(encoding="utf-8"))
    handler = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Handler")
    methods = {node.name: node for node in handler.body if isinstance(node, ast.FunctionDef)}
    analysis_tree = ast.parse((root / "src/local_ai_hub/http_post_repository_analysis.py").read_text(encoding="utf-8"))
    external_analysis = next(node for node in analysis_tree.body if isinstance(node, ast.FunctionDef) and node.name == "handle_post_repository_analysis")
    for rule in POST_ROUTE_REGISTRY:
        method_name = POST_ROUTE_HANDLER_BOUNDARIES.get(rule.route_id)
        if method_name:
            nodes = [external_analysis] if method_name == "_handle_post_repository_analysis" else [methods[method_name]]
        else:
            nodes = [statement for statement in ast.walk(methods["do_POST"])
                     if isinstance(statement, ast.If) and any(isinstance(item, ast.Constant) and isinstance(item.value, str) and item.value in {rule.route_id, *rule.paths} for item in ast.walk(statement.test))]
            nodes = [child for statement in nodes for child in statement.body]
        for path in rule.paths:
            rows[f"POST {path}"].update(_response_facts(nodes, methods))
    for name in ("do_GET", *GET_ROUTE_HANDLER_BOUNDARIES.values()):
        for node in ast.walk(methods[name]):
            if not isinstance(node, ast.Compare) or not isinstance(node.left, ast.Name) or node.left.id != "path":
                continue
            if not any(isinstance(op, (ast.Eq, ast.In)) for op in node.ops):
                continue
            for comparator in node.comparators:
                for item in ast.walk(comparator):
                    if isinstance(item, ast.Constant) and isinstance(item.value, str) and item.value.startswith("/"):
                        rows.setdefault(f"GET {item.value}", {"source": "src/local_ai_hub/http_server.py", "handler": name})
                        branches = [branch for branch in ast.walk(methods[name]) if isinstance(branch, ast.If) and branch.test is node]
                        _merge_response_facts(rows[f"GET {item.value}"], _response_facts([child for branch in branches for child in branch.body], methods))
    for path, name in GET_ROUTE_HANDLER_BOUNDARIES.items():
        rows[f"GET {path}"] = {"source": "src/local_ai_hub/http_server.py", "handler": name}
        rows[f"GET {path}"].update(_response_facts([methods[name]]))
    # Dynamic resource bodies are separate operations, not root-binding guards.
    dynamic = {
        "GET /api/agent-state/swarm/{swarm_id}": "path.startswith('/api/agent-state/swarm/')",
        "GET /api/debug-traces/{trace_id}": "path.startswith('/api/debug-traces/')",
        "GET /api/debug-traces/{trace_id}/metrics": "path.startswith(trace_prefix) and path.endswith(metrics_suffix)",
    }
    for key, expression in dynamic.items():
        branches = [node for node in ast.walk(methods["do_GET"]) if isinstance(node, ast.If) and ast.unparse(node.test) == expression]
        if not branches:
            raise ValueError("Dynamic dispatch changed; review inventory extractor: " + key)
        rows[key] = {"source": "src/local_ai_hub/http_server.py", "handler": "do_GET", **_response_facts([child for branch in branches for child in branch.body])}
    rows["OPTIONS /api/browser/*"] = {"source": "src/local_ai_hub/http_server.py", "handler": "do_OPTIONS"}
    rows["OPTIONS /api/vision/review"] = {"source": "src/local_ai_hub/http_server.py", "handler": "do_OPTIONS"}
    return dict(sorted(rows.items()))


def check_audit(root: Path) -> list[str]:
    current = collect_surface(root)
    path = root / "docs/agent-surface-audit.json"
    if not path.exists():
        return ["Missing audit dispositions"]
    document = json.loads(path.read_text(encoding="utf-8"))
    dispositions = document.get("operations", {})
    errors = [f"Unclassified: {key}" for key in current.keys() - dispositions.keys()]
    errors += [f"Stale: {key}" for key in dispositions.keys() - current.keys()]
    for key in current.keys() & dispositions.keys():
        row = dispositions[key]
        if row.get("decision") not in {"retain", "diagnostic", "protocol_boundary"} or not row.get("reason"):
            errors.append(f"Unreviewed: {key}")
        if not row.get("response_policy"):
            errors.append(f"Missing response review: {key}")
        if row.get("source_contract") != current[key]:
            errors.append(f"Changed response contract: {key}")
    return sorted(errors)


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    if "--inventory" in sys.argv:
        print(json.dumps(collect_surface(root), indent=2))
    else:
        errors = check_audit(root)
        print(json.dumps({"success": not errors, "errors": errors}, indent=2))
        raise SystemExit(bool(errors))

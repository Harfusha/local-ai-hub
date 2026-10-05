"""Read-only AST diff of public MCP handler arguments and registry properties."""
from __future__ import annotations

import argparse
import ast
from pathlib import Path

SHARED_FIELDS = {"max_response_tokens", "response_profile", "reuse_key"}


def dict_field_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    if isinstance(node, ast.Dict):
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                names.add(key.value)
            elif key is None:
                names.update(dict_field_names(value))
    elif isinstance(node, ast.DictComp):
        for generator in node.generators:
            if isinstance(generator.iter, (ast.Tuple, ast.List)):
                names.update(
                    item.value for item in generator.iter.elts
                    if isinstance(item, ast.Constant) and isinstance(item.value, str)
                )
    return names


def contract_fields(node: ast.AST) -> set[str]:
    calls = [
        item for item in ast.walk(node)
        if isinstance(item, ast.Call) and isinstance(item.func, ast.Name)
        and item.func.id == "_tool_contract"
    ]
    if not calls:
        return set()
    call = calls[0]
    fields = {call.args[2].value} if len(call.args) > 2 and isinstance(call.args[2], ast.Constant) else set()
    keywords = {item.arg: item.value for item in call.keywords if item.arg}
    fields.update(dict_field_names(keywords.get("properties", ast.Dict(keys=[], values=[]))))
    conditional = keywords.get("conditional_properties")
    if isinstance(conditional, ast.Dict):
        for value in conditional.values:
            fields.update(dict_field_names(value))
    return fields | SHARED_FIELDS


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    root = parser.parse_args().root.resolve()
    source = ast.parse((root / "src/local_ai_hub/mcp_server.py").read_text(encoding="utf-8"))
    contracts = ast.parse((root / "src/local_ai_hub/operation_contracts.py").read_text(encoding="utf-8"))
    handlers = {
        node.name: {
            arg.arg for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs
            if arg.arg not in {"self", "cls"}
        }
        for node in source.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("local_ai_")
    }
    registry: dict[str, set[str]] = {}
    for node in contracts.body:
        value = getattr(node, "value", None)
        if not isinstance(value, ast.Dict):
            continue
        for key, contract in zip(value.keys, value.values):
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                registry[key.value] = contract_fields(contract)
    for name in handlers:
        registered = registry.get(name, set())
        missing = sorted(handlers[name] - registered)
        print(f"{name}: handler={len(handlers[name])} registry={len(registered)} missing={missing}")


if __name__ == "__main__":
    main()

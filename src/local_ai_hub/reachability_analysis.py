"""Pure call-name reachability analysis for deterministic dead-code reporting."""

from typing import Any


def analyze_reachability(
    definitions: dict[str, dict[str, Any]],
    definitions_by_name: dict[str, list[str]],
    module_calls: dict[str, set[str]],
    entrypoints: list[str],
) -> tuple[set[str], set[str], list[dict[str, Any]], list[dict[str, Any]]]:
    ambiguous_names = {
        name for name, symbol_ids in definitions_by_name.items() if len(symbol_ids) > 1
    }
    reachable: set[str] = set()
    queue: list[str] = []

    for entrypoint in entrypoints:
        queue.extend(
            symbol_id
            for name in module_calls.get(entrypoint, set())
            if name not in ambiguous_names
            for symbol_id in definitions_by_name.get(name, [])
        )

    visited_nodes: set[str] = set()
    while queue:
        symbol_id = queue.pop(0)
        if symbol_id in visited_nodes:
            continue
        visited_nodes.add(symbol_id)
        if symbol_id in definitions:
            reachable.add(symbol_id)
            symbol_file = definitions[symbol_id]["file"]
            for neighbor in module_calls.get(symbol_file, set()):
                if neighbor not in visited_nodes and neighbor not in ambiguous_names:
                    queue.extend(definitions_by_name.get(neighbor, []))

    ambiguous_symbols = [
        definitions[symbol_id]
        for name in sorted(ambiguous_names)
        for symbol_id in definitions_by_name[name]
    ]
    unreachable = [
        info
        for symbol_id, info in definitions.items()
        if symbol_id not in reachable and info["name"] not in ambiguous_names
    ]
    return ambiguous_names, reachable, ambiguous_symbols, unreachable

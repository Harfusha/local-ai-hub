"""Bounded, conservative Python AST change classification without code execution."""
from __future__ import annotations

import ast
import copy
import hashlib
from collections import Counter, defaultdict, deque
from typing import Any

_DEFINITIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
MAX_SOURCE_BYTES = 1_048_576
MAX_AST_NODES = 20_000
MAX_DEFINITIONS = 1_000


class _OwnStructure(ast.NodeTransformer):
    def __init__(self, root: ast.AST) -> None:
        self.root = root

    def _definition(self, node: ast.AST) -> ast.AST | None:
        return self.generic_visit(node) if node is self.root else None

    visit_FunctionDef = _definition
    visit_AsyncFunctionDef = _definition
    visit_ClassDef = _definition


def _digest(node: ast.AST, *, own: bool = False, omit_name: bool = False) -> str:
    if own:
        node = copy.deepcopy(node)
        node = _OwnStructure(node).visit(node)
    if omit_name and isinstance(node, _DEFINITIONS):
        node.name = "<definition>"
    return hashlib.sha256(ast.dump(node, include_attributes=False).encode("utf-8")).hexdigest()


def _parse(source: str) -> tuple[ast.Module, list[dict[str, Any]]]:
    if not isinstance(source, str) or len(source) > MAX_SOURCE_BYTES or len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValueError("source exceeds the 1 MiB UTF-8 limit or is not text")
    tree = ast.parse(source)
    validation = [(tree, 0)]
    count = 0
    while validation:
        node, depth = validation.pop()
        count += 1
        if count > MAX_AST_NODES or depth > 128:
            raise ValueError("source exceeds the bounded AST node/depth limit")
        validation.extend((child, depth + 1) for child in ast.iter_child_nodes(node))
    pending: list[tuple[ast.AST, tuple[str, ...], int]] = [(tree, (), 0)]
    definitions: list[dict[str, Any]] = []
    positions: Counter[tuple[str, ...]] = Counter()
    occurrences: Counter[tuple[str, str]] = Counter()
    while pending:
        node, scope, depth = pending.pop()
        if len(scope) > 32:
            raise ValueError("source exceeds the bounded AST node/depth limit")
        child_scope = scope
        if isinstance(node, _DEFINITIONS):
            qualified = ".".join((*scope, node.name))
            if len(node.name) > 512 or len(qualified) > 2048 or len(definitions) >= MAX_DEFINITIONS:
                raise ValueError("source exceeds the bounded definition/name limit")
            kind = "class" if isinstance(node, ast.ClassDef) else "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function"
            occurrence = occurrences[(kind, qualified)]
            occurrences[(kind, qualified)] += 1
            definitions.append({
                "name": node.name, "qualified_name": qualified, "scope": ".".join(scope),
                "kind": kind, "line": node.lineno, "end_line": node.end_lineno,
                "position": positions[scope], "occurrence": occurrence,
                "fingerprint": _digest(node, own=True),
                "rename_fingerprint": _digest(node, own=True, omit_name=True),
            })
            positions[scope] += 1
            child_scope = (*scope, node.name)
        pending.extend((child, child_scope, depth + 1) for child in reversed(list(ast.iter_child_nodes(node))))
    return tree, definitions


def _metadata(item: dict[str, Any]) -> dict[str, Any]:
    return {key: item[key] for key in ("name", "qualified_name", "scope", "kind", "line", "end_line", "occurrence")}


def ast_diff(old_code: str, new_code: str) -> dict[str, Any]:
    """Separate exact structural candidates from edits; never prove behavior equivalence."""
    parsed = []
    for side, source in (("before", old_code), ("after", new_code)):
        try:
            parsed.append(_parse(source))
        except SyntaxError as exc:
            return {"success": False, "terminal": True, "retryable": False, "language": "python",
                    "error_code": "ast_diff_syntax_error", "error": "invalid Python source",
                    "side": side, "line": exc.lineno, "offset": exc.offset}
        except (ValueError, UnicodeError, RecursionError, MemoryError) as exc:
            return {"success": False, "terminal": True, "retryable": False,
                    "error_code": "ast_diff_input_limit", "error": str(exc)[:256], "side": side}
    (old_tree, before), (new_tree, after) = parsed
    pairs: list[tuple[int, int]] = []
    used_before: set[int] = set()
    used_after: set[int] = set()
    old_groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    new_groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for groups, items in ((old_groups, before), (new_groups, after)):
        for index, item in enumerate(items):
            groups[(item["kind"], item["qualified_name"])].append(index)

    def pair(left: int, right: int) -> None:
        pairs.append((left, right))
        used_before.add(left)
        used_after.add(right)

    ambiguous_identities = 0
    for key in sorted(old_groups.keys() & new_groups.keys()):
        by_hash: dict[str, deque[int]] = defaultdict(deque)
        for index in new_groups[key]:
            by_hash[after[index]["fingerprint"]].append(index)
        for index in old_groups[key]:
            candidates = by_hash[before[index]["fingerprint"]]
            if candidates:
                pair(index, candidates.popleft())
        left = [index for index in old_groups[key] if index not in used_before]
        right = [index for index in new_groups[key] if index not in used_after]
        if len(left) == len(right) == 1:
            pair(left[0], right[0])
        elif left and right:
            ambiguous_identities += 1

    old_renames: dict[tuple[str, str], list[int]] = defaultdict(list)
    new_renames: dict[tuple[str, str], list[int]] = defaultdict(list)
    for items, used, groups in ((before, used_before, old_renames), (after, used_after, new_renames)):
        for index, item in enumerate(items):
            if index not in used:
                groups[(item["kind"], item["rename_fingerprint"])].append(index)
    ambiguous = 0
    for key in sorted(old_renames.keys() & new_renames.keys()):
        left, right = old_renames[key], new_renames[key]
        if len(left) == len(right) == 1:
            pair(left[0], right[0])
        else:
            ambiguous += 1

    sibling_pairs: dict[str, list[int]] = defaultdict(list)
    for token, (left, right) in enumerate(pairs):
        if before[left]["scope"] == after[right]["scope"]:
            sibling_pairs[before[left]["scope"]].append(token)
    reordered: set[int] = set()
    for tokens in sibling_pairs.values():
        old_order = sorted(tokens, key=lambda token: before[pairs[token][0]]["position"])
        new_order = sorted(tokens, key=lambda token: after[pairs[token][1]]["position"])
        reordered.update(old for old, new in zip(old_order, new_order) if old != new)
        reordered.update(new for old, new in zip(old_order, new_order) if old != new)

    changes: list[dict[str, Any]] = []
    unchanged = 0
    logic_edits = _digest(old_tree, own=True) != _digest(new_tree, own=True)
    if logic_edits:
        changes.append({"change_types": ["module_modified"], "before": None, "after": None})
    for token, (left, right) in enumerate(pairs):
        old, new = before[left], after[right]
        types = []
        if old["name"] != new["name"]:
            types.append("renamed")
        if old["scope"] != new["scope"]:
            types.append("moved")
        if old["rename_fingerprint"] != new["rename_fingerprint"]:
            types.append("modified")
            logic_edits = True
        if token in reordered:
            types.append("reordered")
        if types:
            changes.append({"change_types": types, "before": _metadata(old), "after": _metadata(new)})
        else:
            unchanged += 1
    for items, used, change_type in ((before, used_before, "removed"), (after, used_after, "added")):
        for index, item in enumerate(items):
            if index not in used:
                logic_edits = True
                changes.append({"change_types": [change_type],
                                "before": _metadata(item) if change_type == "removed" else None,
                                "after": _metadata(item) if change_type == "added" else None})
    tree: dict[str, Any] = {"scope": "<module>", "children": []}
    scopes: dict[tuple[str, ...], dict[str, Any]] = {(): tree}
    for change in changes:
        location = change["after"] or change["before"] or {"scope": ""}
        parent = tuple(location["scope"].split(".")) if location["scope"] else ()
        for length in range(1, len(parent) + 1):
            prefix = parent[:length]
            if prefix not in scopes:
                group = {"scope": ".".join(prefix), "children": []}
                scopes[prefix] = group
                scopes[prefix[:-1]]["children"].append(group)
        scopes[parent]["children"].append(change)
    equal = _digest(old_tree) == _digest(new_tree)
    return {"success": True, "language": "python", "structural_equal": equal,
            "formatting_only": old_code != new_code and equal,
            "logic_edits_detected": logic_edits, "behavior_equivalence_proven": False,
            "summary": dict(Counter(kind for change in changes for kind in change["change_types"])),
            "unchanged_definitions": unchanged, "ambiguous_rename_groups": ambiguous,
            "ambiguous_identity_groups": ambiguous_identities,
            "changes": changes, "tree": tree,
            "source_hashes": {"before": hashlib.sha256(old_code.encode("utf-8")).hexdigest(),
                              "after": hashlib.sha256(new_code.encode("utf-8")).hexdigest()}}

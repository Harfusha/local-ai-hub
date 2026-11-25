"""Static, explicitly declared business assertions against current source.

No imports, code execution, dynamic inference, network requests or raw source
publication. A literal declaration is not proof of effective runtime behavior.
"""
from __future__ import annotations

import ast
import re
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .evidence import _evidence_path_under_root
from .repo_plan.schema_validation import RepoPlanValidationError, parse_plan_json
from .source_slice import read_source_slice

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,79}")
_FORMATS = {".py": "python_literal", ".json": "json_literal", ".toml": "toml_literal"}
_PRIVATE = re.compile(r"secret|credential|password|token|private|passwd|api[-_]?key", re.I)


def validate_source_assertion(value: Any) -> None:
    from .repo_task_handoff import _safe_relative_path

    if not isinstance(value, dict) or set(value) != {"path", "format", "key"}:
        raise RepoPlanValidationError("Invalid source assertion")
    path, kind, key = value["path"], value["format"], value["key"]
    if (
        not _safe_relative_path(path)
        or any(part.startswith(".") or _PRIVATE.search(part) for part in path.split("/"))
        or _FORMATS.get(Path(path).suffix.lower()) != kind
        or not isinstance(key, list) or not 1 <= len(key) <= 8
        or any(not isinstance(part, str) or not _NAME.fullmatch(part) or _PRIVATE.search(part) for part in key)
        or (kind == "python_literal" and (len(key) != 1 or not key[0].isidentifier()))
    ):
        raise RepoPlanValidationError("Unsupported or private source assertion target")


def _python_literal(text: str, name: str) -> tuple[bool, int, int] | None:
    tree = ast.parse(text)
    matches = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name:
            matches.append(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            matches.append(node.value)
    # Reject ambiguous writes, including conditional/nested assignments.
    writes = sum(isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, (ast.Store, ast.Del))
                 for node in ast.walk(tree))
    if len(matches) != 1 or writes != 1:
        return None
    value = matches[0]
    if not isinstance(value, ast.Constant) or type(value.value) is not bool:
        return None
    return value.value, value.lineno, value.end_lineno or value.lineno


def inspect_source_assertion(root: Path, assertion: Mapping[str, Any], expected: bool) -> dict[str, Any]:
    validate_source_assertion(dict(assertion))
    path = assertion["path"]
    output: dict[str, Any] = {"path": path, "status": "unknown", "expected": expected}
    source = _evidence_path_under_root(str(root), path, strict=True)
    if source is None or not source.is_file():
        return output
    result = read_source_slice(str(root), path, line_end=200, max_chars=12000)
    if (
        result.get("success") is not True or result.get("complete") is not True
        or result.get("total_lines", 201) > 200 or result.get("relative_path") != path
        or _evidence_path_under_root(str(root), path, strict=True) != source
    ):
        return output
    text = result["text"]
    try:
        if assertion["format"] == "python_literal":
            found = _python_literal(text, assertion["key"][0])
            if found is None:
                return output
            actual, start, end = found
        else:
            value = parse_plan_json(text.encode("utf-8")) if assertion["format"] == "json_literal" else tomllib.loads(text)
            for part in assertion["key"]:
                if not isinstance(value, dict) or part not in value:
                    return output
                value = value[part]
            if type(value) is not bool:
                return output
            actual, start, end = value, 1, max(1, result["total_lines"])
    except (ValueError, SyntaxError, RepoPlanValidationError, RecursionError):
        return output
    output.update({
        "status": "matches" if actual == expected else "mismatch", "actual": actual,
        "source": {"schema_version": 1, "path": path, "content_digest": result["file_sha256"],
                   "start_line": start, "end_line": end},
        "authority": "static_literal_only",
    })
    return output


def validate_verification_targets(value: Any) -> None:
    """Explicit static Python test locators; never executable commands."""
    from .repo_task_handoff import _safe_relative_path

    if not isinstance(value, list) or not 1 <= len(value) <= 4:
        raise RepoPlanValidationError("Verification targets require 1 through 4 locators")
    seen: set[tuple[str, str]] = set()
    for target in value:
        if not isinstance(target, dict) or set(target) != {"path", "symbol"}:
            raise RepoPlanValidationError("Invalid verification target")
        path, symbol = target["path"], target["symbol"]
        if (
            not _safe_relative_path(path) or not path.endswith(".py")
            or any(part.startswith(".") or _PRIVATE.search(part) for part in path.split("/"))
            or not isinstance(symbol, str) or len(symbol) > 160
            or not re.fullmatch(r"(?:[A-Za-z_][A-Za-z0-9_]*\.)?test_[A-Za-z0-9_]+", symbol)
            or _PRIVATE.search(symbol)
        ):
            raise RepoPlanValidationError("Unsupported or private verification target")
        key = (path, symbol)
        if key in seen:
            raise RepoPlanValidationError("Duplicate verification target")
        seen.add(key)


def inspect_verification_target(root: Path, target: Mapping[str, Any]) -> dict[str, Any]:
    """Observe a named test declaration without importing or running it."""
    validate_verification_targets([dict(target)])
    path, symbol = target["path"], target["symbol"]
    output: dict[str, Any] = {
        "path": path, "symbol": symbol, "status": "unknown",
        "runtime_verified": False, "authority": "static_test_declaration_only",
    }
    source = _evidence_path_under_root(str(root), path, strict=True)
    if source is None or not source.is_file():
        return output
    result = read_source_slice(str(root), path, line_end=200, max_chars=12000)
    if (
        result.get("success") is not True or result.get("complete") is not True
        or result.get("total_lines", 201) > 200 or result.get("relative_path") != path
        or _evidence_path_under_root(str(root), path, strict=True) != source
    ):
        return output
    try:
        tree = ast.parse(result["text"])
    except (SyntaxError, ValueError, RecursionError):
        return output
    parts = symbol.split(".")
    body = tree.body
    if len(parts) == 2:
        classes = [node for node in body if isinstance(node, ast.ClassDef) and node.name == parts[0]]
        if len(classes) > 1:
            return output
        body = classes[0].body if classes else []
    matches = [
        node for node in body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == parts[-1]
    ]
    if len(matches) > 1:
        return output
    node = matches[0] if matches else None
    output.update({
        "status": "declared" if node is not None else "not_declared",
        "source": {"schema_version": 1, "path": path, "content_digest": result["file_sha256"],
                   "start_line": node.lineno if node else 1,
                   "end_line": (node.end_lineno or node.lineno) if node else max(1, result["total_lines"])},
    })
    return output

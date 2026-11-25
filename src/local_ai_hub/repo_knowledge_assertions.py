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

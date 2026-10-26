"""Schema and semantic validation for repository-owned plan files."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from jsonschema.validators import Draft202012Validator

MAX_PLAN_FILE_BYTES = 1024 * 1024  # 1 MiB
MAX_PLAN_TASKS = 1000
MAX_PLAN_NESTING_DEPTH = 32

SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "docs"
    / "superpowers"
    / "specs"
    / "contracts"
    / "repo-plan.v1.schema.json"
)

PLAN_ID_REGEX = re.compile(r"^plan_[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
TASK_ID_REGEX = re.compile(r"^task_[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
CHANGE_ID_REGEX = re.compile(r"^change_[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
DELIVERY_ID_REGEX = re.compile(r"^delivery_[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
TARGET_REF_REGEX = re.compile(r"^refs/heads/[^\s\u0000]{1,245}$")
GIT_COMMIT_REGEX = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
CONTENT_SHA256_REGEX = re.compile(r"^[0-9a-f]{64}$")


class RepoPlanError(Exception):
    """Base exception for repo plan errors."""


class RepoPlanValidationError(RepoPlanError):
    """Raised when a plan violates schema or semantic constraints."""


class RepoPlanConflictError(RepoPlanError):
    """Raised when concurrent modification or stale revision is detected."""


class RepoPlanNotFoundError(RepoPlanError):
    """Raised when a plan or task is not found."""


def _check_nesting_depth(data: Any, current_depth: int = 1) -> None:
    stack = [(data, current_depth)]
    while stack:
        value, depth = stack.pop()
        if depth > MAX_PLAN_NESTING_DEPTH:
            raise RepoPlanValidationError(
                f"Plan exceeds maximum nesting depth of {MAX_PLAN_NESTING_DEPTH}"
            )
        if isinstance(value, dict):
            stack.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, (list, tuple)):
            stack.extend((item, depth + 1) for item in value)


def _check_raw_json_depth(text: str) -> None:
    """Bound container nesting before json.loads can recurse on untrusted text."""
    depth = 0
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            if depth > MAX_PLAN_NESTING_DEPTH:
                raise RepoPlanValidationError(
                    f"Plan exceeds maximum nesting depth of {MAX_PLAN_NESTING_DEPTH}"
                )
        elif char in "]}":
            depth = max(0, depth - 1)


def _reject_non_finite(value: Any) -> None:
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, float) and not math.isfinite(item):
            raise RepoPlanValidationError("Non-finite JSON number is not allowed")
        if isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, (list, tuple)):
            stack.extend(item)


def _bounded_json_bytes(data: Any) -> bytes:
    _check_nesting_depth(data)
    _reject_non_finite(data)
    try:
        encoded = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise RepoPlanValidationError(f"Plan data is not finite, bounded JSON: {exc}") from exc
    if len(encoded) > MAX_PLAN_FILE_BYTES:
        raise RepoPlanValidationError(
            f"Plan file exceeds maximum size of {MAX_PLAN_FILE_BYTES} bytes ({len(encoded)} bytes)"
        )
    return encoded


def _strict_object_pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    res: dict[str, Any] = {}
    for key, value in pairs:
        if key in res:
            raise RepoPlanValidationError(f"Duplicate JSON key: '{key}'")
        res[key] = value
    return res


def parse_plan_json(json_str_or_bytes: str | bytes) -> dict[str, Any]:
    """Parse JSON string or bytes with strict duplicate key, NaN, and depth checks."""
    if isinstance(json_str_or_bytes, bytes):
        raw_bytes = json_str_or_bytes
        if len(raw_bytes) > MAX_PLAN_FILE_BYTES:
            raise RepoPlanValidationError(
                f"Plan file exceeds maximum size of {MAX_PLAN_FILE_BYTES} bytes ({len(raw_bytes)} bytes)"
            )
        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RepoPlanValidationError(f"Plan file is not valid UTF-8: {exc}") from exc
    else:
        if not isinstance(json_str_or_bytes, str):
            raise RepoPlanValidationError("Plan JSON input must be str or bytes")
        text = json_str_or_bytes
        try:
            encoded = text.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise RepoPlanValidationError(f"Plan file is not valid UTF-8 text: {exc}") from exc
        if len(encoded) > MAX_PLAN_FILE_BYTES:
            raise RepoPlanValidationError(
                f"Plan file exceeds maximum size of {MAX_PLAN_FILE_BYTES} bytes ({len(encoded)} bytes)"
            )

    _check_raw_json_depth(text)
    def parse_finite_float(raw: str) -> float:
        value = float(raw)
        if not math.isfinite(value):
            raise RepoPlanValidationError(f"Non-finite JSON number: '{raw}'")
        return value

    try:
        data = json.loads(
            text,
            object_pairs_hook=_strict_object_pairs_hook,
            parse_float=parse_finite_float,
            parse_constant=lambda c: (_ for _ in ()).throw(
                RepoPlanValidationError(f"Non-finite JSON number or constant: '{c}'")
            ),
        )
    except json.JSONDecodeError as exc:
        raise RepoPlanValidationError(f"Malformed JSON in plan file: {exc}") from exc
    except RecursionError as exc:
        raise RepoPlanValidationError("Plan JSON exceeds parser nesting capacity") from exc

    if not isinstance(data, dict):
        raise RepoPlanValidationError("Plan root must be a JSON object")

    _check_nesting_depth(data)
    return data


_LOADED_SCHEMA: dict[str, Any] | None = None
_VALIDATOR: Draft202012Validator | None = None


def get_plan_validator() -> Draft202012Validator:
    global _LOADED_SCHEMA, _VALIDATOR
    if _VALIDATOR is None:
        if not SCHEMA_PATH.exists():
            raise FileNotFoundError(f"Plan schema not found at {SCHEMA_PATH}")
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            _LOADED_SCHEMA = json.load(f)
        _VALIDATOR = Draft202012Validator(_LOADED_SCHEMA)
    return _VALIDATOR


def validate_repo_path(path_str: str, repo_root: str | Path | None = None) -> None:
    """Validate lexical and confinement constraints for a repository-relative path."""
    if not isinstance(path_str, str):
        raise RepoPlanValidationError(f"Path must be a string, got {type(path_str)}")
    if not path_str or len(path_str) > 1024:
        raise RepoPlanValidationError(f"Path length must be between 1 and 1024: '{path_str}'")
    if "\\" in path_str:
        raise RepoPlanValidationError(f"Path must use forward slashes only: '{path_str}'")
    if path_str.startswith("/"):
        raise RepoPlanValidationError(f"Path must be relative, cannot start with '/': '{path_str}'")
    if re.match(r"^[A-Za-z]:", path_str):
        raise RepoPlanValidationError(f"Path cannot include Windows drive letter: '{path_str}'")
    for segment in path_str.split("/"):
        if segment in {".", ".."}:
            raise RepoPlanValidationError(f"Path cannot contain '.' or '..' segments: '{path_str}'")
    if any(ord(c) < 32 for c in path_str):
        raise RepoPlanValidationError(f"Path cannot contain control characters: '{path_str}'")

    if repo_root is not None:
        resolved_root = Path(repo_root).resolve()
        candidate = (resolved_root / path_str).resolve()
        try:
            candidate.relative_to(resolved_root)
        except ValueError as exc:
            raise RepoPlanValidationError(
                f"Path '{path_str}' escapes repository root '{resolved_root}'"
            ) from exc


def detect_dependency_cycles(tasks: dict[str, Any], plan_id: str) -> None:
    """Detect cycles among tasks within the same plan using DFS."""
    # Build adjacency list for tasks in this plan
    adj: dict[str, list[str]] = {tid: [] for tid in tasks}
    for tid, tdata in tasks.items():
        depends_on = tdata.get("depends_on", []) if isinstance(tdata, dict) else []
        for dep in depends_on:
            if not isinstance(dep, dict):
                continue
            dep_plan = dep.get("plan_id")
            dep_task = dep.get("task_id")
            if dep_plan == plan_id and dep_task in tasks:
                adj[tid].append(dep_task)

    state: dict[str, int] = {}  # 1: active, 2: complete
    for start in tasks:
        if state.get(start) == 2:
            continue
        path: list[str] = []
        positions: dict[str, int] = {}
        stack: list[tuple[str, Any]] = [(start, iter(adj.get(start, [])))]
        state[start] = 1
        positions[start] = 0
        path.append(start)
        while stack:
            node, neighbors = stack[-1]
            try:
                neighbor = next(neighbors)
            except StopIteration:
                stack.pop()
                path.pop()
                positions.pop(node, None)
                state[node] = 2
                continue
            if state.get(neighbor) == 1:
                cycle_path = " -> ".join(path[positions[neighbor]:] + [neighbor])
                raise RepoPlanValidationError(f"Cyclic dependency detected: {cycle_path}")
            if state.get(neighbor) != 2:
                state[neighbor] = 1
                positions[neighbor] = len(path)
                path.append(neighbor)
                stack.append((neighbor, iter(adj.get(neighbor, []))))


def validate_plan_dict(data: dict[str, Any], repo_root: str | Path | None = None) -> None:
    """Perform full JSON Schema and semantic validation on parsed plan dictionary."""
    if not isinstance(data, dict):
        raise RepoPlanValidationError("Plan data must be a dictionary")

    _bounded_json_bytes(data)

    # 1. Structural schema validation
    validator = get_plan_validator()
    errors = list(validator.iter_errors(data))
    if errors:
        first = errors[0]
        field_path = ".".join(str(p) for p in first.path) or "root"
        raise RepoPlanValidationError(f"Schema validation error at '{field_path}': {first.message}")

    # 2. Schema version check
    if data.get("schema_version") != 1:
        raise RepoPlanValidationError(
            f"Unsupported schema_version: {data.get('schema_version')}. Expected: 1"
        )

    # 3. Tasks count check
    tasks = data.get("tasks", {})
    if not isinstance(tasks, dict):
        raise RepoPlanValidationError("'tasks' must be an object")
    if len(tasks) > MAX_PLAN_TASKS:
        raise RepoPlanValidationError(
            f"Plan exceeds maximum task limit of {MAX_PLAN_TASKS} (found {len(tasks)})"
        )

    plan_id = data.get("id", "")
    if not PLAN_ID_REGEX.match(plan_id):
        raise RepoPlanValidationError(f"Invalid plan ID format: '{plan_id}'")

    # 4. Check spec_refs in plan
    for spec in data.get("spec_refs", []):
        validate_repo_path(spec.get("path", ""), repo_root=repo_root)

    # 5. Semantic checks on each task
    for tid, tdata in tasks.items():
        if not TASK_ID_REGEX.match(tid):
            raise RepoPlanValidationError(f"Invalid task ID format: '{tid}'")

        # Verify repo_paths in task spec_refs
        for spec in tdata.get("spec_refs", []):
            validate_repo_path(spec.get("path", ""), repo_root=repo_root)

        # Verify repo_paths in task scope
        scope = tdata.get("scope")
        if scope and isinstance(scope, dict):
            for path_str in scope.get("paths", []):
                validate_repo_path(path_str, repo_root=repo_root)

        # Verify clarifications
        for clar in tdata.get("clarifications", []):
            cid = clar.get("id", "")
            if not CHANGE_ID_REGEX.match(cid):
                raise RepoPlanValidationError(f"Invalid clarification ID format: '{cid}'")
            for spec in clar.get("spec_refs", []):
                validate_repo_path(spec.get("path", ""), repo_root=repo_root)

        # Verify deliveries
        deliveries = tdata.get("deliveries", {})
        if isinstance(deliveries, dict):
            for del_id, delivery in deliveries.items():
                if not DELIVERY_ID_REGEX.match(del_id):
                    raise RepoPlanValidationError(f"Invalid delivery ID format: '{del_id}'")
                target_ref = delivery.get("target_ref", "")
                if not TARGET_REF_REGEX.match(target_ref):
                    raise RepoPlanValidationError(f"Invalid delivery target_ref: '{target_ref}'")

        # Verify dependencies
        for dep in tdata.get("depends_on", []):
            dep_plan = dep.get("plan_id", "")
            dep_task = dep.get("task_id", "")
            if not PLAN_ID_REGEX.match(dep_plan):
                raise RepoPlanValidationError(f"Invalid dependency plan_id: '{dep_plan}'")
            if not TASK_ID_REGEX.match(dep_task):
                raise RepoPlanValidationError(f"Invalid dependency task_id: '{dep_task}'")
            if dep_plan == plan_id and dep_task not in tasks:
                raise RepoPlanValidationError(
                    f"Task '{tid}' depends on non-existent task '{dep_task}' in plan '{plan_id}'"
                )

    # 6. Cycle detection
    detect_dependency_cycles(tasks, plan_id)


def serialize_plan_json(data: dict[str, Any]) -> str:
    """Deterministically serialize plan dictionary to UTF-8 formatted JSON string with trailing newline."""
    validate_plan_dict(data)
    try:
        text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise RepoPlanValidationError(f"Plan data is not finite, bounded JSON: {exc}") from exc
    if len(text.encode("utf-8")) > MAX_PLAN_FILE_BYTES:
        raise RepoPlanValidationError(f"Plan file exceeds maximum size of {MAX_PLAN_FILE_BYTES} bytes")
    return text

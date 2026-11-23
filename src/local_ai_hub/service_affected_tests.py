"""Affected test discovery and dependency graph impact service."""

from __future__ import annotations

import math
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .cache import stable_hash
from .project_config import (
    PathHint,
    path_is_allowed,
    path_matches_pattern,
    resolve_project_context,
)
from .state_paths import configured_state_dir
from .test_selection import affected_test_command, canonical_runner, compatible_tests


def affected_tests(
    services: Any,
    root: str,
    changed_paths: list[str] | None = None,
    base: str = "HEAD",
    path_hints: list[Any] | tuple[Any, ...] | None = None,
) -> dict[str, Any]:
    context = resolve_project_context(root, configured_state_dir(services.config))
    request_hints: list[PathHint] = []
    if isinstance(path_hints, (list, tuple)):
        for item in path_hints[:64]:
            if isinstance(item, PathHint):
                request_hints.append(item)
            elif isinstance(item, dict):
                allowed_fields = {
                    "path",
                    "purpose",
                    "scope",
                    "evidence_id",
                    "provenance",
                    "repository_revision",
                    "config_digest",
                    "expires_at",
                }
                if set(item) - allowed_fields:
                    continue
                try:
                    request_hints.append(
                        PathHint(**{
                            key: value
                            for key, value in item.items()
                            if key in allowed_fields
                        })
                    )
                except TypeError:
                    continue
    request_hints = [
        hint
        for hint in request_hints
        if isinstance(hint.path, str)
        and isinstance(hint.purpose, str)
        and isinstance(hint.scope, str)
        and all(
            value is None or isinstance(value, str)
            for value in (
                hint.evidence_id,
                hint.provenance,
                hint.repository_revision,
                hint.config_digest,
                hint.expires_at,
            )
        )
    ]
    hint_digest = stable_hash([asdict(hint) for hint in request_hints])
    params = {
        "changed_paths": None if changed_paths is None else list(changed_paths),
        "base": base,
        "project_config_digest": context.config_digest,
        "path_hints_digest": hint_digest,
    }
    result = services._repository_test_impact_service().affected_tests(
        root,
        changed_paths,
        base,
        params,
    )
    if not isinstance(result, dict) or not result.get("success", True):
        return result
    workspace_state = result.get("workspace_cache", {})
    repository_revision = (
        str(workspace_state.get("fingerprint", ""))
        if isinstance(workspace_state, dict)
        and not workspace_state.get("stale")
        and not workspace_state.get("degraded")
        else ""
    )

    candidates = [
        path for path in result.get("test_files", []) if isinstance(path, str)
    ]
    changed_for_mapping = changed_paths or result.get("changed_files", [])
    def normalize_graph_path(path: str) -> str:
        normalized = path.replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        return normalized

    changed_for_graph = sorted(
        {
            normalize_graph_path(path)
            for path in changed_for_mapping
            if isinstance(path, str) and path
        }
    )
    graph_complete = False
    graph_tests: list[str] = []
    graph_missing_candidates = 0
    try:
        impact = (
            services.code_index.impact(root, changed_for_graph, max_dependents=100)
            if services.code_index is not None and changed_for_graph
            else None
        )
        if isinstance(impact, dict):
            likely_dependents = impact.get("likely_dependents", [])
            suggested_tests = impact.get("suggested_tests", [])
            confidence = impact.get("confidence")
            graph_complete = (
                impact.get("success") is True
                and isinstance(confidence, (int, float))
                and not isinstance(confidence, bool)
                and math.isfinite(float(confidence))
                and float(confidence) >= 0.94
                and impact.get("indexed_changed_files") == len(changed_for_graph)
                and impact.get("changed_files_count") == len(changed_for_graph)
                and isinstance(likely_dependents, list)
                and len(likely_dependents) < 100
                and isinstance(suggested_tests, list)
                and len(suggested_tests) < 20
            )
            if graph_complete:
                for item in suggested_tests:
                    candidate = item.get("path") if isinstance(item, dict) else None
                    if isinstance(candidate, str):
                        graph_tests.append(candidate.replace("\\", "/"))
                for item in likely_dependents:
                    candidate = item.get("path") if isinstance(item, dict) else None
                    if (
                        isinstance(candidate, str)
                        and services.code_index._is_test_path(candidate)
                    ):
                        graph_tests.append(candidate.replace("\\", "/"))
                graph_tests = list(dict.fromkeys(graph_tests))
                graph_missing_candidates = len(set(graph_tests) - set(candidates))
                candidates.extend(
                    path for path in graph_tests if path not in candidates
                )
    except Exception:
        graph_complete = False
    # An explicitly empty change set needs no graph or full-matrix fallback.
    # Omitted paths still retain the conservative discovery behavior.
    explicit_no_changes = isinstance(changed_paths, list) and not changed_paths
    selection_uncertain = not graph_complete and not explicit_no_changes
    matrix: dict[str, Any] | None = None
    complete_matrix_paths: list[str] = []
    if selection_uncertain:
        matrix = services.test_matrix(root)
        for item in matrix.get("test_files", []):
            candidate = item.get("path") if isinstance(item, dict) else item
            if isinstance(candidate, str):
                complete_matrix_paths.append(candidate)
        candidates.extend(complete_matrix_paths)
        if not complete_matrix_paths:
            candidates = []
    target_patterns = tuple(
        target_pattern
        for source_pattern, targets in context.settings.affected_tests_mapping.items()
        if any(
            isinstance(changed_path, str)
            and path_matches_pattern(changed_path, source_pattern)
            for changed_path in changed_for_mapping
        )
        for target_pattern in targets
    )
    if target_patterns:
        if matrix is None:
            matrix = services.test_matrix(root)
        for item in matrix.get("test_files", []):
            candidate = item.get("path") if isinstance(item, dict) else item
            if (
                isinstance(candidate, str)
                and any(
                    path_matches_pattern(candidate, pattern)
                    for pattern in target_patterns
                )
            ):
                candidates.append(candidate)
    candidates = list(dict.fromkeys(candidates))
    usage = context.prioritize_paths(
        candidates,
        purpose="affected_tests",
        scope="run_affected",
        repository_revision=repository_revision,
        path_hints=tuple(request_hints),
    )
    allowed_tests: list[str] = []
    for candidate in usage.paths:
        try:
            file_size = (Path(root) / candidate).stat().st_size
        except OSError:
            file_size = None
        if path_is_allowed(
            root,
            candidate,
            context.settings,
            phase="test",
            size_bytes=file_size,
        ):
            allowed_tests.append(candidate)

    result = dict(result)
    framework = canonical_runner(result.get("framework", "unknown"))
    allowed_tests, incompatible_tests = compatible_tests(allowed_tests, framework)
    result["test_files"] = allowed_tests
    result["excluded_incompatible_tests"] = list(dict.fromkeys(
        [*result.get("excluded_incompatible_tests", []), *incompatible_tests]
    ))
    result["requires_multiple_runners"] = bool(result["excluded_incompatible_tests"])
    if result["excluded_incompatible_tests"]:
        result["selection_complete"] = False
        result["confidence"] = min(float(result.get("confidence", 0.0)), 0.5)
    suggested_command = affected_test_command(allowed_tests, framework)
    result["suggested_command"] = suggested_command
    result["project_config_digest"] = context.config_digest
    if graph_complete:
        result["dependency_graph_complete"] = True
        result["dependency_graph_test_count"] = len(graph_tests)
        result["dependency_graph_missing_candidates"] = graph_missing_candidates
    if selection_uncertain:
        result["selection_uncertain"] = True
        result["selection_fallback"] = (
            "complete_test_matrix"
            if complete_matrix_paths
            else "unavailable_test_matrix"
        )
    result["path_hint_usage"] = {
        "hint_used": usage.hint_used,
        "fallback_used": usage.fallback_used,
        "hint_helped": usage.hint_helped,
    }
    return result

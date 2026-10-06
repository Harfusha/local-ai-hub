"""Typed, bounded project configuration and evidence-bound path hints."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import tomllib
from contextlib import closing
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Mapping


_MAX_CONFIG_BYTES = 256 * 1024
_MAX_RELATIVE_PATH = 1024
_MAX_PATH_OVERRIDES = 512
_MAX_HINTS_PER_SCOPE = 256
_MAX_HINTS_PER_PROJECT = 4096
_MAX_REQUEST_PATH_HINTS = 64
_GIT_TIMEOUT_SECONDS = 1.5
_PHASES = frozenset({"rag", "call_graph", "modules"})
_PATH_POLICY_PHASES = _PHASES | {"search", "repository_search", "preprocess", "test"}
_MODEL_PROFILES = frozenset({"integrated", "balanced", "high", "max"})
_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ENV_REFERENCE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")
_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
_EXTENSION = re.compile(r"^\.[a-z0-9][a-z0-9._+-]{0,15}$")
_PROJECT_CONFIG = ".local-ai.toml"
_WORKTREE_OVERRIDE = ".local-ai.worktree.toml"
_LOCAL_CONFIG_FILES = frozenset({_PROJECT_CONFIG, _WORKTREE_OVERRIDE})
_COMMON_DIR_UNSET = object()
_TOP_LEVEL = frozenset(
    {
        "exclude_paths",
        "force_include_paths",
        "path_overrides",
        "preprocess",
        "custom_extensions",
        "file_limits",
        "skip_phases",
        "commands",
        "affected_tests_mapping",
        "env",
        "verification_rules",
        "pinned_context",
        "entry_points",
        "retrieval_weights",
        "project_type",
        "solution_path",
        "language_overrides",
        "model_profile",
        "system_prompt_prefix",
        "shared_namespace",
    }
)


class ProjectConfigError(ValueError):
    """Invalid project configuration with a safe, machine-readable reason."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class CommandDefinition:
    argv: tuple[str, ...]
    description: str = ""
    env_references: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "argv", _freeze(self.argv))
        object.__setattr__(self, "env_references", _freeze(self.env_references))


@dataclass(frozen=True)
class ProjectSettings:
    exclude_paths: tuple[str, ...] = ()
    force_include_paths: tuple[str, ...] = ()
    path_overrides: Mapping[str, str] = field(default_factory=dict)
    preprocess_exclude_paths: tuple[str, ...] = ()
    text_extensions: tuple[str, ...] = ()
    binary_extensions: tuple[str, ...] = ()
    max_file_size_bytes: int | None = None
    skip_phases: tuple[str, ...] = ()
    commands: Mapping[str, str | CommandDefinition] = field(default_factory=dict)
    affected_tests_mapping: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    env_references: Mapping[str, str] = field(default_factory=dict)
    verification_rules: Mapping[str, bool | tuple[str, ...]] = field(default_factory=dict)
    pinned_context: tuple[str, ...] = ()
    entry_points: tuple[str, ...] = ()
    retrieval_weights: Mapping[str, float] = field(default_factory=dict)
    project_type: str | None = None
    solution_path: str | None = None
    language_overrides: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    model_profile: str = "balanced"
    system_prompt_prefix: str | None = None
    shared_namespace: str | None = None
    env: Mapping[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        for name in (
            "exclude_paths",
            "force_include_paths",
            "preprocess_exclude_paths",
            "text_extensions",
            "binary_extensions",
            "skip_phases",
            "pinned_context",
            "entry_points",
        ):
            object.__setattr__(self, name, _freeze(getattr(self, name)))
        for name in (
            "commands",
            "path_overrides",
            "affected_tests_mapping",
            "env",
            "env_references",
            "verification_rules",
            "retrieval_weights",
            "language_overrides",
        ):
            object.__setattr__(self, name, _freeze(getattr(self, name)))


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _canonical(value: Any) -> Any:
    if is_dataclass(value):
        return {
            item.name: _canonical(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, Mapping):
        return {key: _canonical(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    return value


def _json_compatible(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, list):
        return [_json_compatible(item) for item in value]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {key: _json_compatible(item) for key, item in value.items()}
    raise ProjectConfigError("invalid_config")


@dataclass(frozen=True)
class ProjectConfigResolution:
    settings: ProjectSettings
    active_sources: tuple[str, ...]
    error_codes: tuple[str, ...]
    config_digest: str


@dataclass(frozen=True)
class ProjectContext:
    """Resolved project settings and repo-scoped hint access for adapters."""

    root: Path
    resolution: ProjectConfigResolution
    _hint_store: ProjectPathHintStore = field(repr=False, compare=False)

    @property
    def settings(self) -> ProjectSettings:
        return self.resolution.settings

    @property
    def config_digest(self) -> str:
        return self.resolution.config_digest

    @property
    def coordination_id(self) -> str | None:
        """Return producer-owned project namespace, or fail closed on bad config."""
        if self.resolution.error_codes:
            return None
        return self._hint_store.project_id

    def path_hints(
        self, *, purpose: str, scope: str, repository_revision: str
    ) -> tuple[PathHint, ...]:
        return self._hint_store.find(
            purpose=purpose,
            scope=scope,
            repository_revision=repository_revision,
            config_digest=self.config_digest,
        )

    def prioritize_paths(
        self,
        candidates: list[str] | tuple[str, ...],
        *,
        purpose: str,
        scope: str,
        repository_revision: str,
        path_hints: list[PathHint] | tuple[PathHint, ...] = (),
    ) -> PathHintUsage:
        """Rank candidates by durable, request, then saved repo-scoped hints."""
        configured_hints = tuple(
            PathHint(path=path, purpose=purpose, scope=scope)
            for path in self.settings.entry_points
        )
        request_hints = tuple(
            hint
            for hint in path_hints[:_MAX_REQUEST_PATH_HINTS]
            if isinstance(hint, PathHint)
        )
        saved_hints = self.path_hints(
            purpose=purpose,
            scope=scope,
            repository_revision=repository_revision,
        )
        ordered = tuple(candidates)
        hints_available = bool(configured_hints or request_hints or saved_hints)
        hint_used = False
        for hints in (saved_hints, request_hints, configured_hints):
            if not hints:
                continue
            usage = prioritize_paths_with_hints(
                self.root,
                ordered,
                hints,
                purpose=purpose,
                scope=scope,
                repository_revision=repository_revision,
                config_digest=self.config_digest,
            )
            ordered = usage.paths
            hint_used = hint_used or usage.hint_used
        return PathHintUsage(
            paths=ordered,
            hint_used=hint_used,
            fallback_used=hints_available and not hint_used,
            hint_helped=None,
        )

    def save_path_hint(self, hint: PathHint) -> None:
        self._hint_store.add(hint)


@dataclass(frozen=True)
class PathHint:
    path: str
    purpose: str
    scope: str
    evidence_id: str | None = None
    provenance: str | None = None
    repository_revision: str | None = None
    config_digest: str | None = None
    expires_at: str | None = None


@dataclass(frozen=True)
class PathHintUsage:
    paths: tuple[str, ...]
    hint_used: bool
    fallback_used: bool
    hint_helped: None = None

    def telemetry_metadata(self) -> dict[str, bool | None]:
        """Return path-free fields safe for aggregate telemetry."""
        return {
            "hint_used": self.hint_used is True,
            "fallback_used": self.fallback_used is True,
            "hint_helped": None,
        }


def _git_common_dir(root: Path) -> Path | None:
    """Return Git common directory using one bounded, shell-free subprocess."""
    kwargs: dict[str, Any] = {
        "cwd": str(root),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.DEVNULL,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": _GIT_TIMEOUT_SECONDS,
        "check": False,
    }
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if no_window:
        kwargs["creationflags"] = no_window
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"], **kwargs
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    candidate = Path(result.stdout.strip())
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        return candidate.resolve(strict=False)
    except (OSError, RuntimeError):
        return None


def _merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _merge(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def _canonicalize_path_override_keys(layer: dict[str, Any]) -> dict[str, Any]:
    overrides = layer.get("path_overrides")
    if not isinstance(overrides, dict):
        return layer
    canonical: dict[str, Any] = {}
    for pattern, action in overrides.items():
        _, key = _normalize_glob_values("", _relative_pattern(pattern))
        if key in canonical:
            raise ProjectConfigError("invalid_config")
        canonical[key] = action
    layer["path_overrides"] = canonical
    return layer


def _relative_pattern(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > _MAX_RELATIVE_PATH
        or any(not character.isprintable() for character in value)
    ):
        raise ProjectConfigError("invalid_config")
    value = value.strip().replace("\\", "/")
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise ProjectConfigError("invalid_config")
    parts = value.split("/")
    if any(part in {"..", "."} for part in parts):
        raise ProjectConfigError("invalid_config")
    return "/".join(part for part in parts if part)


def _string_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ProjectConfigError("invalid_config")
    return tuple(_relative_pattern(item) for item in value)


def _literal_path_list(value: Any) -> tuple[str, ...]:
    paths = _string_list(value)
    if any(any(character in path for character in "*?[]") for path in paths):
        raise ProjectConfigError("invalid_config")
    return paths


def _extensions(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ProjectConfigError("invalid_config")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ProjectConfigError("invalid_config")
        extension = item.lower()
        if not _EXTENSION.fullmatch(extension):
            raise ProjectConfigError("invalid_config")
        result.append(extension)
    if len(result) != len(set(result)):
        raise ProjectConfigError("invalid_config")
    return tuple(result)


def _has_extension(path: str | os.PathLike[str], extensions: tuple[str, ...]) -> bool:
    """Match configured extensions against full names, including compound suffixes."""
    name = Path(path).name.casefold()
    return any(name.endswith(extension.casefold()) for extension in extensions)


def custom_extension_kind(
    path: str | os.PathLike[str],
    settings: ProjectSettings,
    *,
    language: str | None = None,
) -> Literal["text", "binary"] | None:
    """Classify configured custom extensions for reader and indexer consumers."""
    if _has_extension(path, settings.binary_extensions):
        return "binary"
    text_extensions = list(settings.text_extensions)
    if language is not None:
        override = settings.language_overrides.get(language, {})
        override_extensions = override.get("text_extensions", ())
        if isinstance(override_extensions, (tuple, list)):
            text_extensions.extend(
                item for item in override_extensions if isinstance(item, str)
            )
    if _has_extension(path, tuple(text_extensions)):
        return "text"
    return None


def _validate_command(value: Any) -> str | CommandDefinition:
    if isinstance(value, str):
        if not value.strip() or len(value) > 4096:
            raise ProjectConfigError("invalid_config")
        return value
    if not isinstance(value, dict) or set(value) - {"argv", "description", "env"}:
        raise ProjectConfigError("invalid_config")
    argv = value.get("argv")
    if (
        not isinstance(argv, list)
        or not argv
        or any(not isinstance(arg, str) or len(arg) > 1024 for arg in argv)
    ):
        raise ProjectConfigError("invalid_config")
    description = value.get("description", "")
    if not isinstance(description, str) or len(description) > 500:
        raise ProjectConfigError("invalid_config")
    env = value.get("env", {})
    if not isinstance(env, dict):
        raise ProjectConfigError("invalid_config")
    checked_env = _env_references(env)
    return CommandDefinition(tuple(argv), description, checked_env)


def _env_references(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ProjectConfigError("invalid_config")
    result: dict[str, str] = {}
    for key, item in value.items():
        match = _ENV_REFERENCE.fullmatch(item) if isinstance(item, str) else None
        if not isinstance(key, str) or not _KEY.fullmatch(key) or match is None:
            raise ProjectConfigError("invalid_config")
        result[key] = match.group(1)
    return result


def _environment_values(value: Any) -> tuple[dict[str, str], dict[str, str]]:
    if not isinstance(value, dict):
        raise ProjectConfigError("invalid_config")
    values: dict[str, str] = {}
    references: dict[str, str] = {}
    for key, item in value.items():
        if (
            not isinstance(key, str)
            or not _ENV_KEY.fullmatch(key)
            or not isinstance(item, str)
        ):
            raise ProjectConfigError("invalid_config")
        match = _ENV_REFERENCE.fullmatch(item)
        if match is not None:
            references[key] = match.group(1)
        elif "${" in item:
            raise ProjectConfigError("invalid_config")
        else:
            values[key] = item
    return values, references


def _normalize(data: dict[str, Any]) -> ProjectSettings:
    if set(data) - _TOP_LEVEL:
        raise ProjectConfigError("invalid_config")
    preprocess = data.get("preprocess", {})
    extensions = data.get("custom_extensions", {})
    limits = data.get("file_limits", {})
    for name, value in (
        ("preprocess", preprocess),
        ("custom_extensions", extensions),
        ("file_limits", limits),
    ):
        if not isinstance(value, dict):
            raise ProjectConfigError("invalid_config")
    if set(preprocess) - {"exclude_paths"}:
        raise ProjectConfigError("invalid_config")
    if set(extensions) - {"text", "binary"} or set(limits) - {"max_file_size_bytes"}:
        raise ProjectConfigError("invalid_config")

    text_extensions = _extensions(extensions.get("text", []))
    binary_extensions = _extensions(extensions.get("binary", []))
    if set(text_extensions) & set(binary_extensions):
        raise ProjectConfigError("invalid_config")

    max_bytes = limits.get("max_file_size_bytes")
    if max_bytes is not None and (
        isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0
    ):
        raise ProjectConfigError("invalid_config")

    skip = data.get("skip_phases", [])
    if not isinstance(skip, list) or any(
        not isinstance(item, str) or item not in _PHASES for item in skip
    ):
        raise ProjectConfigError("invalid_config")

    commands_value = data.get("commands", {})
    if not isinstance(commands_value, dict):
        raise ProjectConfigError("invalid_config")
    commands: dict[str, Any] = {}
    for name, command in commands_value.items():
        if not isinstance(name, str) or not _KEY.fullmatch(name):
            raise ProjectConfigError("invalid_config")
        commands[name] = _validate_command(command)

    affected_value = data.get("affected_tests_mapping", {})
    if not isinstance(affected_value, dict):
        raise ProjectConfigError("invalid_config")
    affected: dict[str, tuple[str, ...]] = {}
    for source, tests in affected_value.items():
        source = _relative_pattern(source)
        if isinstance(tests, str):
            tests = [tests]
        affected[source] = _string_list(tests)

    rules_value = data.get("verification_rules", {})
    if not isinstance(rules_value, dict):
        raise ProjectConfigError("invalid_config")
    rules: dict[str, Any] = {}
    for name, rule in rules_value.items():
        if not isinstance(name, str) or not _KEY.fullmatch(name):
            raise ProjectConfigError("invalid_config")
        if isinstance(rule, bool):
            if not rule:
                raise ProjectConfigError("invalid_config")
            rules[name] = True
        elif isinstance(rule, list) and rule and all(
            isinstance(item, str) and item.strip() for item in rule
        ):
            rules[name] = tuple(item.strip() for item in rule)
        else:
            raise ProjectConfigError("invalid_config")

    weights = data.get("retrieval_weights", {})
    if not isinstance(weights, dict):
        raise ProjectConfigError("invalid_config")
    normalized_weights: dict[str, float] = {}
    for name, weight in weights.items():
        if (
            not isinstance(name, str)
            or not _KEY.fullmatch(name)
            or isinstance(weight, bool)
            or not isinstance(weight, (int, float))
            or not math.isfinite(float(weight))
            or not 0.0 <= float(weight) <= 1.0
        ):
            raise ProjectConfigError("invalid_config")
        normalized_weights[name] = float(weight)

    language_overrides = data.get("language_overrides", {})
    if not isinstance(language_overrides, dict) or any(
        not isinstance(name, str)
        or not _KEY.fullmatch(name)
        or not isinstance(value, dict)
        for name, value in language_overrides.items()
    ):
        raise ProjectConfigError("invalid_config")
    normalized_language_overrides: dict[str, dict[str, Any]] = {}
    for name, value in language_overrides.items():
        override = _json_compatible(value)
        if "text_extensions" in value:
            override_extensions = _extensions(value["text_extensions"])
            if set(override_extensions) & set(binary_extensions):
                raise ProjectConfigError("invalid_config")
            override["text_extensions"] = override_extensions
        normalized_language_overrides[name] = override
    language_overrides = normalized_language_overrides

    path_overrides_value = data.get("path_overrides", {})
    if (
        not isinstance(path_overrides_value, dict)
        or len(path_overrides_value) > _MAX_PATH_OVERRIDES
    ):
        raise ProjectConfigError("invalid_config")
    path_overrides: dict[str, str] = {}
    for pattern, action in path_overrides_value.items():
        if not isinstance(action, str) or action not in {
            "include",
            "exclude",
            "default",
        }:
            raise ProjectConfigError("invalid_config")
        normalized_pattern = _relative_pattern(pattern)
        if normalized_pattern in path_overrides:
            raise ProjectConfigError("invalid_config")
        path_overrides[normalized_pattern] = action

    profile = data.get("model_profile", "balanced")
    if not isinstance(profile, str) or profile not in _MODEL_PROFILES:
        raise ProjectConfigError("invalid_config")
    project_type = data.get("project_type")
    if project_type is not None and (
        not isinstance(project_type, str) or not project_type.strip() or len(project_type) > 100
    ):
        raise ProjectConfigError("invalid_config")
    solution = data.get("solution_path")
    if solution is not None:
        solution = _relative_pattern(solution)
        if any(char in solution for char in "*?[]"):
            raise ProjectConfigError("invalid_config")
    prefix = data.get("system_prompt_prefix")
    if prefix is not None and (not isinstance(prefix, str) or len(prefix) > 4000):
        raise ProjectConfigError("invalid_config")
    namespace = data.get("shared_namespace")
    if namespace is not None and (
        not isinstance(namespace, str) or not _KEY.fullmatch(namespace)
    ):
        raise ProjectConfigError("invalid_config")

    project_env, env_references = _environment_values(data.get("env", {}))

    return ProjectSettings(
        exclude_paths=_string_list(data.get("exclude_paths", [])),
        force_include_paths=_string_list(data.get("force_include_paths", [])),
        path_overrides=path_overrides,
        preprocess_exclude_paths=_string_list(preprocess.get("exclude_paths", [])),
        text_extensions=text_extensions,
        binary_extensions=binary_extensions,
        max_file_size_bytes=max_bytes,
        skip_phases=tuple(skip),
        commands=commands,
        affected_tests_mapping=affected,
        env=project_env,
        env_references=env_references,
        verification_rules=rules,
        pinned_context=_literal_path_list(data.get("pinned_context", [])),
        entry_points=_literal_path_list(data.get("entry_points", [])),
        retrieval_weights=normalized_weights,
        project_type=project_type,
        solution_path=solution,
        language_overrides=dict(language_overrides),
        model_profile=profile,
        system_prompt_prefix=prefix,
        shared_namespace=namespace,
    )


def _read_layer(path: Path) -> dict[str, Any]:
    try:
        if not path.is_file():
            raise ProjectConfigError("invalid_toml")
        if path.stat().st_size > _MAX_CONFIG_BYTES:
            raise ProjectConfigError("config_too_large")
        with path.open("rb") as stream:
            raw = stream.read(_MAX_CONFIG_BYTES + 1)
        if len(raw) > _MAX_CONFIG_BYTES:
            raise ProjectConfigError("config_too_large")
        value = tomllib.loads(raw.decode("utf-8"))
    except ProjectConfigError:
        raise
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        raise ProjectConfigError("invalid_toml") from None
    if not isinstance(value, dict):
        raise ProjectConfigError("invalid_toml")
    return value


def _safe_config_file(path: Path, base: Path) -> bool:
    try:
        return path.resolve(strict=True).is_relative_to(base.resolve(strict=True))
    except (OSError, ValueError, RuntimeError):
        return False


def _digest(settings: ProjectSettings) -> str:
    payload = json.dumps(_canonical(settings), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def resolve_project_config(root: str | os.PathLike[str]) -> ProjectConfigResolution:
    """Load all project overlays atomically; invalid overlays select safe defaults."""
    try:
        project_root = Path(root).expanduser().resolve(strict=True)
        if not project_root.is_dir():
            raise ProjectConfigError("invalid_root")
    except (OSError, RuntimeError, ProjectConfigError):
        settings = ProjectSettings()
        return ProjectConfigResolution(settings, ("defaults",), ("invalid_root",), _digest(settings))

    return _resolve_project_config(project_root, _git_common_dir(project_root))


def _resolve_project_config(
    project_root: Path, common_dir: Path | None
) -> ProjectConfigResolution:
    project_path = project_root / _PROJECT_CONFIG
    worktree_path = project_root / ".local-ai.worktree.toml"
    machine_path = common_dir / "info" / "local-ai.toml" if common_dir else None
    layers: list[tuple[str, Path, Path]] = [("project", project_path, project_root)]
    if machine_path is not None and common_dir is not None:
        layers.append(("git_common", machine_path, common_dir))
    layers.append(("worktree", worktree_path, project_root))

    combined: dict[str, Any] = {}
    active_sources = ["defaults"]
    try:
        for source, path, containment_root in layers:
            if not path.exists():
                continue
            if not _safe_config_file(path, containment_root):
                raise ProjectConfigError("unsafe_config_path")
            layer = _canonicalize_path_override_keys(_read_layer(path))
            combined = _merge(combined, layer)
            active_sources.append(source)
        settings = _normalize(combined)
        config_digest = _digest(settings)
    except ProjectConfigError as exc:
        settings = ProjectSettings()
        return ProjectConfigResolution(settings, ("defaults",), (exc.code,), _digest(settings))
    except (TypeError, ValueError, OverflowError, RecursionError):
        settings = ProjectSettings()
        return ProjectConfigResolution(
            settings, ("defaults",), ("invalid_config",), _digest(settings)
        )

    return ProjectConfigResolution(
        settings=settings,
        active_sources=tuple(active_sources),
        error_codes=(),
        config_digest=config_digest,
    )


def resolve_project_context(
    root: str | os.PathLike[str], state_dir: str | os.PathLike[str]
) -> ProjectContext:
    try:
        project_root = Path(root).expanduser().resolve(strict=True)
        if not project_root.is_dir():
            raise ProjectConfigError("invalid_root")
    except (OSError, RuntimeError, ValueError):
        raise ProjectConfigError("invalid_root") from None
    common_dir = _git_common_dir(project_root)
    resolution = _resolve_project_config(project_root, common_dir)
    hint_store = ProjectPathHintStore(
        state_dir,
        project_root,
        shared_namespace=resolution.settings.shared_namespace,
        git_common_dir=common_dir,
    )
    return ProjectContext(project_root, resolution, hint_store)


def validate_path_hint(
    root: str | os.PathLike[str],
    hint: PathHint,
    *,
    purpose: str,
    scope: str,
    repository_revision: str,
    config_digest: str,
    now: datetime | None = None,
    learned: bool = False,
) -> Path | None:
    """Return contained, existing path only when hint scope and freshness match."""
    try:
        relative = _relative_pattern(hint.path)
        if any(char in relative for char in "*?[]"):
            return None
        if hint.purpose != purpose or hint.scope != scope:
            return None
        if learned and (
            not hint.evidence_id
            or not hint.provenance
            or not hint.repository_revision
            or not hint.config_digest
        ):
            return None
        if not _safe_label(hint.purpose, 128) or not _safe_label(hint.scope, 128):
            return None
        if hint.evidence_id is not None and not _safe_label(hint.evidence_id, 256):
            return None
        if hint.provenance is not None and not _safe_label(hint.provenance, 256):
            return None
        if hint.repository_revision is not None and not _safe_label(
            hint.repository_revision, 256
        ):
            return None
        if hint.config_digest is not None and not _safe_label(hint.config_digest, 128):
            return None
        if hint.expires_at is not None and not _safe_label(hint.expires_at, 64):
            return None
        if hint.repository_revision and hint.repository_revision != repository_revision:
            return None
        if hint.config_digest and hint.config_digest != config_digest:
            return None
        if hint.expires_at:
            expires = datetime.fromisoformat(hint.expires_at.replace("Z", "+00:00"))
            current = now or datetime.now(timezone.utc)
            if current.tzinfo is None:
                current = current.replace(tzinfo=timezone.utc)
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if current >= expires:
                return None
        project_root = Path(root).resolve(strict=True)
        candidate = (project_root / Path(relative)).resolve(strict=True)
        if not candidate.is_relative_to(project_root) or not candidate.exists():
            return None
        return candidate
    except (OSError, RuntimeError, ValueError, ProjectConfigError):
        return None


def prioritize_paths_with_hints(
    root: str | os.PathLike[str],
    candidates: list[str] | tuple[str, ...],
    hints: list[PathHint] | tuple[PathHint, ...],
    *,
    purpose: str,
    scope: str,
    repository_revision: str,
    config_digest: str,
) -> PathHintUsage:
    """Move matching candidates first while preserving every original candidate."""
    original = tuple(candidates)
    try:
        project_root = Path(root).resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return PathHintUsage(original, False, bool(hints), None)
    hinted_roots = [
        path
        for hint in hints
        if (
            path := validate_path_hint(
                project_root,
                hint,
                purpose=purpose,
                scope=scope,
                repository_revision=repository_revision,
                config_digest=config_digest,
                learned=bool(hint.evidence_id),
            )
        )
    ]
    prioritized: list[str] = []
    remaining: list[str] = []
    for candidate in original:
        try:
            path = (project_root / Path(candidate)).resolve(strict=False)
            if not path.is_relative_to(project_root):
                remaining.append(candidate)
                continue
            if any(path == hint_root or hint_root in path.parents for hint_root in hinted_roots):
                prioritized.append(candidate)
            else:
                remaining.append(candidate)
        except (OSError, RuntimeError, ValueError):
            remaining.append(candidate)
    ordered = tuple(prioritized + remaining)
    used = bool(prioritized)
    return PathHintUsage(
        paths=ordered,
        hint_used=used,
        fallback_used=bool(hints) and not used,
        hint_helped=None,
    )


def phase_is_allowed(settings: ProjectSettings, phase: str) -> bool:
    """Return whether a known optional phase is enabled by project settings."""
    return isinstance(phase, str) and phase in _PHASES and phase not in settings.skip_phases


def _phase_is_skipped(settings: ProjectSettings, phase: str) -> bool:
    return isinstance(phase, str) and phase in _PHASES and phase in settings.skip_phases


def _path_policy_phase_is_allowed(phase: str) -> bool:
    return isinstance(phase, str) and phase in _PATH_POLICY_PHASES


def path_is_allowed(
    root: str | os.PathLike[str],
    path: str | os.PathLike[str],
    settings: ProjectSettings,
    *,
    phase: str,
    soft_ignored: bool = False,
    hard_denied: bool = False,
    binary: bool = False,
    size_bytes: int | None = None,
) -> bool:
    """Apply shared project path rules without granting force-include extra trust."""
    if not _path_policy_phase_is_allowed(phase) or _phase_is_skipped(settings, phase):
        return False
    try:
        project_root = Path(root).resolve(strict=True)
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        if candidate.name in _LOCAL_CONFIG_FILES:
            return False
        lexical_candidate = Path(os.path.abspath(candidate))
        lexical_relative = lexical_candidate.relative_to(project_root).as_posix()
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(project_root):
            return False
        resolved_relative = resolved.relative_to(project_root).as_posix()
    except (OSError, RuntimeError, ValueError):
        return False
    if resolved.name in _LOCAL_CONFIG_FILES:
        return False
    if hard_denied or binary:
        return False
    if custom_extension_kind(resolved.name, settings) == "binary":
        return False
    if settings.max_file_size_bytes is not None:
        if (
            isinstance(size_bytes, bool)
            or not isinstance(size_bytes, int)
            or size_bytes < 0
            or size_bytes > settings.max_file_size_bytes
        ):
            return False
    if phase == "preprocess" and (
        _matches_any(lexical_relative, settings.preprocess_exclude_paths)
        or _matches_any(resolved_relative, settings.preprocess_exclude_paths)
    ):
        return False
    if _matches_any(lexical_relative, settings.exclude_paths) or _matches_any(
        resolved_relative, settings.exclude_paths
    ):
        return False
    overrides = {
        _path_override_for(path, settings.path_overrides)
        for path in (lexical_relative, resolved_relative)
    }
    if "exclude" in overrides:
        return False
    if "include" in overrides:
        return True
    if _matches_any(lexical_relative, settings.force_include_paths) or _matches_any(
        resolved_relative, settings.force_include_paths
    ):
        return True
    if soft_ignored:
        return False
    return True


def resolve_pinned_context(
    root: str | os.PathLike[str],
    settings: ProjectSettings,
    *,
    phase: str = "search",
) -> tuple[Path, ...]:
    """Resolve pinned candidates; callers still enforce walker trust state before read."""
    try:
        project_root = Path(root).expanduser().resolve(strict=True)
        if not project_root.is_dir():
            return ()
    except (OSError, RuntimeError, ValueError):
        return ()

    resolved_paths: list[Path] = []
    seen: set[Path] = set()
    for configured_path in settings.pinned_context:
        try:
            relative = _relative_pattern(configured_path)
            if any(character in relative for character in "*?[]"):
                continue
            candidate = project_root / relative
            resolved = candidate.resolve(strict=True)
            if not resolved.is_relative_to(project_root) or not resolved.is_file():
                continue
            size_bytes = resolved.stat().st_size
            if not path_is_allowed(
                project_root,
                candidate,
                settings,
                phase=phase,
                size_bytes=size_bytes,
            ):
                continue
            if resolved not in seen:
                seen.add(resolved)
                resolved_paths.append(resolved)
        except (OSError, RuntimeError, ValueError, ProjectConfigError):
            continue
    return tuple(resolved_paths)


def resolve_entry_points(
    root: str | os.PathLike[str],
    settings: ProjectSettings,
    *,
    phase: str = "search",
) -> tuple[Path, ...]:
    """Resolve entry candidates; callers still enforce walker trust state on traversal."""
    try:
        project_root = Path(root).expanduser().resolve(strict=True)
        if not project_root.is_dir():
            return ()
    except (OSError, RuntimeError, ValueError):
        return ()

    resolved_paths: list[Path] = []
    seen: set[Path] = set()
    for configured_path in settings.entry_points:
        try:
            relative = _relative_pattern(configured_path)
            if any(character in relative for character in "*?[]"):
                continue
            candidate = project_root / relative
            resolved = candidate.resolve(strict=True)
            if not resolved.is_relative_to(project_root):
                continue
            if resolved.is_dir():
                allowed = may_descend(
                    project_root, candidate, settings, phase=phase
                )
            elif resolved.is_file():
                allowed = path_is_allowed(
                    project_root,
                    candidate,
                    settings,
                    phase=phase,
                    size_bytes=resolved.stat().st_size,
                )
            else:
                allowed = False
            if allowed and resolved not in seen:
                seen.add(resolved)
                resolved_paths.append(resolved)
        except (OSError, RuntimeError, ValueError, ProjectConfigError):
            continue
    return tuple(resolved_paths)


def may_descend(
    root: str | os.PathLike[str],
    directory: str | os.PathLike[str],
    settings: ProjectSettings,
    *,
    phase: str,
    soft_ignored: bool = False,
    hard_denied: bool = False,
) -> bool:
    """Keep traversal alive only when directory policy permits or forced path may be below."""
    if not _path_policy_phase_is_allowed(phase) or _phase_is_skipped(settings, phase):
        return False
    try:
        project_root = Path(root).resolve(strict=True)
        candidate = Path(directory)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        if candidate.name in _LOCAL_CONFIG_FILES:
            return False
        lexical_candidate = Path(os.path.abspath(candidate))
        lexical_relative = lexical_candidate.relative_to(project_root).as_posix()
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(project_root) or not resolved.is_dir():
            return False
        resolved_relative = resolved.relative_to(project_root).as_posix()
    except (OSError, RuntimeError, ValueError):
        return False
    if resolved.name in _LOCAL_CONFIG_FILES or hard_denied:
        return False
    if phase == "preprocess" and (
        _matches_any(lexical_relative, settings.preprocess_exclude_paths)
        or _matches_any(resolved_relative, settings.preprocess_exclude_paths)
    ):
        return False
    if _matches_any(lexical_relative, settings.exclude_paths) or _matches_any(
        resolved_relative, settings.exclude_paths
    ):
        return False
    overrides = {
        _path_override_for(path, settings.path_overrides)
        for path in (lexical_relative, resolved_relative)
    }
    include_patterns = list(settings.force_include_paths) + [
        pattern
        for pattern, action in settings.path_overrides.items()
        if action in {"include", "default"}
    ]
    may_reach_included_descendant = any(
        _pattern_may_match_descendant(lexical_relative, pattern)
        or _pattern_may_match_descendant(resolved_relative, pattern)
        for pattern in include_patterns
    )
    if "exclude" in overrides:
        return may_reach_included_descendant
    if "include" in overrides:
        return True
    ignored = soft_ignored
    if not ignored:
        return True
    return may_reach_included_descendant


def phase_enabled(settings: ProjectSettings, phase: str) -> bool:
    """Return whether a known optional phase is enabled by project settings."""
    return phase_is_allowed(settings, phase)


def path_matches_pattern(path: str, pattern: str) -> bool:
    """Match a literal repo-relative path against a safe project glob."""
    try:
        relative_path = _relative_pattern(path)
        relative_pattern = _relative_pattern(pattern)
        if any(character in relative_path for character in "*?[]"):
            return False
        return _path_glob_matches(relative_path, relative_pattern)
    except ProjectConfigError:
        return False


def _matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    return any(_path_glob_matches(path, pattern) for pattern in patterns)


def _path_override_for(path: str, overrides: Mapping[str, str]) -> str | None:
    matched = [
        (_pattern_specificity(pattern), action)
        for pattern, action in overrides.items()
        if _path_glob_matches(path, pattern)
    ]
    if not matched:
        return None
    best = max(rank for rank, _action in matched)
    actions = {action for rank, action in matched if rank == best}
    if len(actions) > 1 or "exclude" in actions:
        return "exclude"
    return "include" if "include" in actions else None


def _pattern_specificity(pattern: str) -> tuple[int, int, int, int, int]:
    _, pattern = _normalize_glob_values("", pattern)
    segments = pattern.split("/")
    literal_segments = sum(
        1
        for segment in segments
        if segment != "**" and not any(char in segment for char in "*?[")
    )
    literal_characters = sum(
        1 for char in pattern if char not in "*?[]"
    )
    recursive_segments = sum(segment == "**" for segment in segments)
    wildcard_cost = sum(
        100
        if segment == "**"
        else segment.count("*") * 10
        + segment.count("?") * 5
        + segment.count("[")
        for segment in segments
    )
    return (
        literal_segments,
        literal_characters,
        -recursive_segments,
        -wildcard_cost,
        len(segments),
    )


def _path_glob_matches(path: str, pattern: str) -> bool:
    path, pattern = _normalize_glob_values(path, pattern)
    path_segments = path.split("/") if path else []
    pattern_segments = pattern.split("/") if pattern else []
    states = _glob_epsilon_closure({0}, pattern_segments)
    for segment in path_segments:
        following: set[int] = set()
        for index in states:
            if index == len(pattern_segments):
                continue
            if pattern_segments[index] == "**":
                following.add(index)
            elif fnmatch.fnmatchcase(segment, pattern_segments[index]):
                following.add(index + 1)
        states = _glob_epsilon_closure(following, pattern_segments)
        if not states:
            return False
    return len(pattern_segments) in states


def _pattern_may_match_descendant(directory: str, pattern: str) -> bool:
    directory, pattern = _normalize_glob_values(directory, pattern)
    path_segments = directory.split("/") if directory else []
    pattern_segments = pattern.split("/") if pattern else []
    states = _glob_epsilon_closure({0}, pattern_segments)
    for segment in path_segments:
        following: set[int] = set()
        for index in states:
            if index == len(pattern_segments):
                continue
            if pattern_segments[index] == "**":
                following.add(index)
            elif fnmatch.fnmatchcase(segment, pattern_segments[index]):
                following.add(index + 1)
        states = _glob_epsilon_closure(following, pattern_segments)
        if not states:
            return False
    return any(index < len(pattern_segments) for index in states)


def _normalize_glob_values(path: str, pattern: str) -> tuple[str, str]:
    path = path.replace("\\", "/")
    pattern = pattern.replace("\\", "/")
    if os.name == "nt":
        path = path.lower()
        pattern = pattern.lower()
    return path, pattern


def _glob_epsilon_closure(states: set[int], pattern: list[str]) -> set[int]:
    closure = set(states)
    pending = list(states)
    while pending:
        index = pending.pop()
        if index < len(pattern) and pattern[index] == "**" and index + 1 not in closure:
            closure.add(index + 1)
            pending.append(index + 1)
    return closure


def _safe_label(value: str, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= maximum
        and not any(ord(char) < 32 or ord(char) == 127 for char in value)
    )


class ProjectPathHintStore:
    """Persist repo-relative hints under a git-common-dir-scoped identity."""

    def __init__(
        self,
        state_dir: str | os.PathLike[str],
        root: str | os.PathLike[str],
        *,
        shared_namespace: str | None = None,
        git_common_dir: Path | None | object = _COMMON_DIR_UNSET,
    ) -> None:
        self.root = Path(root).expanduser().resolve(strict=True)
        common_dir = (
            _git_common_dir(self.root)
            if git_common_dir is _COMMON_DIR_UNSET
            else git_common_dir
        )
        identity = common_dir or self.root
        scope_value = f"{os.path.normcase(str(identity))}\0{shared_namespace or ''}"
        self.project_id = hashlib.sha256(scope_value.encode("utf-8")).hexdigest()
        self.database = Path(state_dir).expanduser() / "project-path-hints.sqlite3"
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS project_path_hints (
                    project_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    evidence_id TEXT NOT NULL,
                    provenance TEXT NOT NULL,
                    repository_revision TEXT NOT NULL,
                    config_digest TEXT NOT NULL,
                    expires_at TEXT,
                    PRIMARY KEY (project_id, path, purpose, scope, evidence_id)
                )"""
            )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=2.0)
        connection.execute("PRAGMA busy_timeout = 2000")
        return connection

    def add(self, hint: PathHint) -> None:
        if validate_path_hint(
            self.root,
            hint,
            purpose=hint.purpose,
            scope=hint.scope,
            repository_revision=hint.repository_revision or "",
            config_digest=hint.config_digest or "",
            learned=True,
        ) is None:
            raise ProjectConfigError("invalid_path_hint")
        if not hint.repository_revision or not hint.config_digest:
            raise ProjectConfigError("invalid_path_hint")
        with closing(self._connect()) as connection:
            connection.execute(
                """INSERT OR REPLACE INTO project_path_hints
                (project_id, path, purpose, scope, evidence_id, provenance,
                 repository_revision, config_digest, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    self.project_id,
                    _relative_pattern(hint.path),
                    hint.purpose,
                    hint.scope,
                    hint.evidence_id,
                    hint.provenance,
                    hint.repository_revision,
                    hint.config_digest,
                    hint.expires_at,
                ),
            )
            connection.execute(
                """DELETE FROM project_path_hints
                   WHERE project_id = ? AND purpose = ? AND scope = ?
                     AND repository_revision = ? AND config_digest = ?
                     AND rowid NOT IN (
                         SELECT rowid FROM project_path_hints
                         WHERE project_id = ? AND purpose = ? AND scope = ?
                           AND repository_revision = ? AND config_digest = ?
                         ORDER BY rowid DESC LIMIT ?
                     )""",
                (
                    self.project_id,
                    hint.purpose,
                    hint.scope,
                    hint.repository_revision,
                    hint.config_digest,
                    self.project_id,
                    hint.purpose,
                    hint.scope,
                    hint.repository_revision,
                    hint.config_digest,
                    _MAX_HINTS_PER_SCOPE,
                ),
            )
            connection.execute(
                """DELETE FROM project_path_hints
                   WHERE project_id = ? AND rowid NOT IN (
                       SELECT rowid FROM project_path_hints
                       WHERE project_id = ? ORDER BY rowid DESC LIMIT ?
                   )""",
                (self.project_id, self.project_id, _MAX_HINTS_PER_PROJECT),
            )
            connection.commit()

    def find(
        self,
        *,
        purpose: str,
        scope: str,
        repository_revision: str,
        config_digest: str,
    ) -> tuple[PathHint, ...]:
        with closing(self._connect()) as connection:
            now = datetime.now(timezone.utc).isoformat()
            rows = connection.execute(
                """SELECT path, purpose, scope, evidence_id, provenance,
                          repository_revision, config_digest, expires_at
                   FROM project_path_hints
                   WHERE project_id = ? AND purpose = ? AND scope = ?
                     AND repository_revision = ? AND config_digest = ?
                     AND (expires_at IS NULL OR julianday(expires_at) > julianday(?))
                   ORDER BY path LIMIT 256""",
                (
                    self.project_id,
                    purpose,
                    scope,
                    repository_revision,
                    config_digest,
                    now,
                ),
            ).fetchall()
        result: list[PathHint] = []
        for row in rows:
            hint = PathHint(*row)
            if validate_path_hint(
                self.root,
                hint,
                purpose=purpose,
                scope=scope,
                repository_revision=repository_revision,
                config_digest=config_digest,
                learned=True,
            ) is not None:
                result.append(hint)
        return tuple(result)

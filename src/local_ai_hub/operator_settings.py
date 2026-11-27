"""Canonical local operator runtime override input contract."""
from __future__ import annotations

from typing import Any



_FEATURES = ("status", "repo", "tasks", "rag", "commands", "coord", "artifacts",
             "code_intelligence", "preprocessing", "subagents", "agent_os", "work_orchestrator")
_BOOLEAN_SETTINGS = frozenset({"preprocessing.enabled",
    "code_intelligence.enabled", "code_intelligence.serena_enabled",
    *(f"features.{name}" for name in _FEATURES)})
_PROFILES = frozenset({"auto", "cpu", "integrated", "low", "balanced", "medium", "high", "max"})
_TELEMETRY_MODES = frozenset({"off", "minimal", "full"})


def operator_settings_patch(requested: Any) -> dict[str, Any]:
    if not isinstance(requested, dict):
        raise ValueError("settings must be an object")
    patch: dict[str, Any] = {}
    for dotted, value in requested.items():
        if not isinstance(dotted, str):
            raise ValueError("setting names must be strings")
        if dotted == "hardware.profile":
            valid = type(value) is str and value in _PROFILES
        elif dotted == "telemetry.mode":
            valid = type(value) is str and value in _TELEMETRY_MODES
        else:
            valid = dotted in _BOOLEAN_SETTINGS and type(value) is bool
        if not valid:
            raise ValueError(f"unsupported or invalid setting: {dotted[:120]}")
        table, name = dotted.split(".", 1)
        patch.setdefault(table, {})[name] = value
    return patch


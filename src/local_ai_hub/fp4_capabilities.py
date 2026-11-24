"""Read the shipped, pre-checked model FP4 catalog; never probe at runtime."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CATALOG_PATH = Path(__file__).with_name("data") / "fp4_model_support.json"


def load_fp4_catalog() -> dict[str, Any]:
    """Load repository-checked FP4 facts bundled with the package."""
    try:
        value = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {"schema_version": 1, "catalog_version": "unavailable", "models": []}
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        return {"schema_version": 1, "catalog_version": "unavailable", "models": []}
    return value


def configured_model_provider(cfg: dict[str, Any]) -> str:
    models = cfg.get("models", {})
    models = models if isinstance(models, dict) else {}
    explicit = str(models.get("provider", "") or "").strip().lower()
    if explicit and explicit not in {"auto", "configured"}:
        return explicit
    llama = cfg.get("llama_cpp", {})
    llama = llama if isinstance(llama, dict) else {}
    mode = str(llama.get("mode", "off") or "off").strip().lower()
    if mode == "on":
        return "llama_cpp"
    if mode == "auto":
        return "auto"
    return "ollama"


def static_fp4_routes(detected: dict[str, Any], provider: str) -> dict[str, str]:
    """Select only pre-checked catalog variants compatible with detected host."""
    catalog = load_fp4_catalog()
    routes: dict[str, str] = {}
    os_name = str(detected.get("os", "")).strip().lower()
    arch = str(detected.get("arch", "")).strip().lower()
    entries = catalog.get("models", [])
    if not isinstance(entries, list):
        return routes
    for item in entries:
        if not isinstance(item, dict) or item.get("route_eligible") is not True:
            continue
        if item.get("provider") != provider.strip().lower():
            continue
        if os_name not in item.get("platforms", []):
            continue
        if arch not in item.get("architectures", []):
            continue
        if item.get("requires_native_fp4") is True and detected.get("has_fp4") is not True:
            continue
        canonical = item.get("model")
        variant = item.get("fp4_variant")
        if isinstance(canonical, str) and isinstance(variant, str):
            routes[canonical] = variant
            for alias in item.get("aliases", []):
                if isinstance(alias, str):
                    routes[alias] = variant
    return routes

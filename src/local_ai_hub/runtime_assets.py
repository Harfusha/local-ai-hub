from __future__ import annotations

import importlib.resources
import json
from pathlib import Path
import tomllib
from typing import Any


class AssetNotFoundError(FileNotFoundError):
    """Raised when a packaged runtime asset cannot be found or read."""


def _get_package_root() -> importlib.resources.abc.Traversable:
    return importlib.resources.files("local_ai_hub")


def load_packaged_text(relative_path: str) -> str:
    """Load a packaged text asset relative to local_ai_hub package root."""
    normalized = relative_path.replace("\\", "/").strip("/")
    try:
        resource = _get_package_root().joinpath(normalized)
        return str(resource.read_text(encoding="utf-8"))
    except Exception as exc:
        local_path = Path(__file__).resolve().parent / normalized
        if local_path.is_file():
            return local_path.read_text(encoding="utf-8")
        raise AssetNotFoundError(f"Runtime asset not found: {relative_path}") from exc


def load_packaged_json(relative_path: str) -> Any:
    """Load and parse a packaged JSON asset."""
    text = load_packaged_text(relative_path)
    return json.loads(text)


def get_grammar(name: str) -> str:
    """Load a GBNF grammar asset by name."""
    clean = name.strip()
    if not clean.endswith(".gbnf"):
        clean = f"{clean}.gbnf"
    return load_packaged_text(f"grammars/{clean}")


def get_schema(name: str) -> dict[str, Any]:
    """Load a repo-plan schema by name."""
    clean = name.strip()
    if not clean.endswith(".schema.json"):
        clean = f"{clean}.schema.json"
    data = load_packaged_json(f"repo_plan/{clean}")
    if not isinstance(data, dict):
        raise ValueError(f"Schema {name} is not a JSON object")
    return data


def get_data_asset(name: str) -> Any:
    """Load a data asset by name."""
    clean = name.strip()
    if not clean.endswith(".json"):
        clean = f"{clean}.json"
    return load_packaged_json(f"data/{clean}")


def get_defaults_toml() -> str:
    """Load defaults.toml text."""
    return load_packaged_text("defaults.toml")


def build_runtime_asset_manifest() -> dict[str, Any]:
    """Build an authoritative manifest of all packaged runtime assets and verify readability."""
    manifest: dict[str, Any] = {
        "grammars": {},
        "schemas": {},
        "data": {},
        "ui_static": [],
        "defaults_toml": False,
        "automation_browser": False,
    }

    # Verify defaults.toml
    defaults_text = get_defaults_toml()
    tomllib.loads(defaults_text)
    manifest["defaults_toml"] = True

    # Verify automation_browser.js
    manifest["automation_browser"] = bool(load_packaged_text("automation_browser.js"))

    # Verify grammars
    preprocess_grammar = get_grammar("preprocess_card.gbnf")
    if "root ::=" not in preprocess_grammar:
        raise ValueError("Invalid preprocess_card.gbnf grammar")
    manifest["grammars"]["preprocess_card.gbnf"] = len(preprocess_grammar)

    # Verify schemas
    repo_plan_schema = get_schema("repo-plan.v1.schema.json")
    if "urn:local-ai-hub:repo-plan" not in repo_plan_schema.get("$id", ""):
        raise ValueError("Invalid repo-plan.v1.schema.json schema")
    manifest["schemas"]["repo-plan.v1.schema.json"] = repo_plan_schema.get("$id")

    # Verify data assets
    fp4_data = get_data_asset("fp4_model_support.json")
    if not isinstance(fp4_data, dict):
        raise ValueError("Invalid fp4_model_support.json data")
    manifest["data"]["fp4_model_support.json"] = len(fp4_data)

    # Legacy manifest key is retained empty for external consumers.

    return manifest

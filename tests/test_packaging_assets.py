from __future__ import annotations

import ast
import importlib
from pathlib import Path
import tomllib

import pytest

from local_ai_hub.runtime_assets import (
    AssetNotFoundError,
    build_runtime_asset_manifest,
    get_data_asset,
    get_defaults_toml,
    get_grammar,
    get_schema,
    load_packaged_text,
)

ROOT = Path(__file__).resolve().parents[1]


def test_authoritative_manifest_contains_all_runtime_assets():
    manifest = build_runtime_asset_manifest()
    assert manifest["defaults_toml"] is True
    assert manifest["automation_browser"] is True
    assert "preprocess_card.gbnf" in manifest["grammars"]
    assert manifest["grammars"]["preprocess_card.gbnf"] > 0
    assert "repo-plan.v1.schema.json" in manifest["schemas"]
    assert "fp4_model_support.json" in manifest["data"]

    ui_paths = {item["path"] for item in manifest["ui_static"]}
    assert "dashboard.html" in ui_paths
    assert "dist/dashboard.js" in ui_paths


def test_asset_loader_negative_cases():
    with pytest.raises(AssetNotFoundError):
        get_grammar("nonexistent_grammar_xyz.gbnf")

    with pytest.raises(AssetNotFoundError):
        get_schema("nonexistent_schema_xyz.schema.json")

    with pytest.raises(AssetNotFoundError):
        get_data_asset("nonexistent_data_xyz.json")

    with pytest.raises(AssetNotFoundError):
        load_packaged_text("completely/bogus/path.txt")


def test_package_data_parity_in_pyproject_and_manifest():
    pyproject_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    pyproject = tomllib.loads(pyproject_text)
    manifest_in = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")

    pkg_data = pyproject["tool"]["setuptools"]["package-data"]["local_ai_hub"]
    assert "grammars/*.gbnf" in pkg_data
    assert "defaults.toml" in pkg_data
    assert "automation_browser.js" in pkg_data
    assert "data/*.json" in pkg_data
    assert "ui_static/*" in pkg_data
    assert "ui_static/dist/*" in pkg_data

    # MANIFEST.in parity
    assert "recursive-include src/local_ai_hub/grammars *.gbnf" in manifest_in
    assert "recursive-include src/local_ai_hub/ui_static *" in manifest_in
    assert "recursive-include src/local_ai_hub/data *.json" in manifest_in
    assert "include src/local_ai_hub/automation_browser.js" in manifest_in
    assert "include src/local_ai_hub/defaults.toml" in manifest_in
    assert "include src/local_ai_hub/repo_plan/repo-plan.v1.schema.json" in manifest_in


def test_browser_bridge_assets_complete():
    bridge_dir = ROOT / "browser_bridge"
    expected_files = [
        "background.js",
        "capture.js",
        "manifest.json",
        "offscreen.html",
        "offscreen.js",
        "popup.html",
        "popup.js",
        "README.md",
    ]
    for filename in expected_files:
        filepath = bridge_dir / filename
        assert filepath.is_file(), f"Missing browser bridge asset: {filename}"
        assert filepath.stat().st_size > 0, f"Empty browser bridge asset: {filename}"


def test_cli_entrypoints_resolve_to_callable_targets():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = pyproject.get("project", {}).get("scripts", {})
    assert len(scripts) >= 5

    for command_name, target in scripts.items():
        module_name, func_name = target.split(":")
        mod = importlib.import_module(module_name)
        func = getattr(mod, func_name, None)
        assert callable(func), f"Entrypoint {command_name} -> {target} is not callable"

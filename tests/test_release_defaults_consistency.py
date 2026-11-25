from __future__ import annotations

import tomllib
import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_version_matches_installable_package_and_release_metadata():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    runtime = ast.parse((ROOT / "src" / "local_ai_hub" / "__init__.py").read_text(encoding="utf-8"))
    assignment = next(
        node for node in runtime.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets)
    )
    release = json.loads((ROOT / "RELEASE.json").read_text(encoding="utf-8"))
    provider_manifests = {
        "antigravity": "plugin.json",
        "claude": ".claude-plugin/plugin.json",
        "codex": "plugin.json",
        "copilot": "plugin.json",
        "cursor": ".cursor-plugin/plugin.json",
        "devin": "plugin.json",
        "gemini": "gemini-extension.json",
    }

    assert ast.literal_eval(assignment.value) == project["project"]["version"]
    assert release["version"] == project["project"]["version"]
    for provider, manifest_path in provider_manifests.items():
        manifest = json.loads(
            (ROOT / "plugins" / provider / "local-ai-hub" / manifest_path).read_text(encoding="utf-8")
        )
        assert manifest["version"] == project["project"]["version"], provider


def test_packaged_defaults_match_repository_defaults_and_enable_concise_local_output():
    repository_defaults = tomllib.loads((ROOT / "defaults.toml").read_text(encoding="utf-8"))
    packaged_defaults = tomllib.loads(
        (ROOT / "src" / "local_ai_hub" / "defaults.toml").read_text(encoding="utf-8")
    )

    assert packaged_defaults == repository_defaults
    assert repository_defaults["token_saving"]["concise_local_output"] is True
    assert repository_defaults["background_gpu"]["enabled"] is False
    assert repository_defaults["background_gpu"]["cpu_fallback_enabled"] is True
    assert repository_defaults["models"]["allow_hf_downloads"] is True
    assert repository_defaults["laya"]["enabled"] is True
    assert "mode" not in repository_defaults["laya"]
    assert repository_defaults["agents"]["antigravity"] is True
    assert repository_defaults["agents"]["opencode_plugin_route"] is True
    retired_models = {"qwen3.5:4b-q4_K_M", "gemma4:12b", "qwen2.5-coder:14b"}
    assert retired_models.isdisjoint(repository_defaults["models"].values())


def test_example_config_shows_active_laya_and_default_checkpoint_downloads():
    example = tomllib.loads((ROOT / "config.toml.example").read_text(encoding="utf-8"))

    assert example["laya"]["enabled"] is True
    assert "mode" not in example["laya"]
    assert example["laya"]["idle_unload_seconds"] == 600
    assert example["models"]["allow_hf_downloads"] is True


def test_setup_generation_syncs_repository_defaults_into_packaged_copy(tmp_path):
    from tools import setup

    package_dir = tmp_path / "src" / "local_ai_hub"
    package_dir.mkdir(parents=True)
    repository_defaults = tmp_path / "defaults.toml"
    packaged_defaults = package_dir / "defaults.toml"
    repository_defaults.write_text("[scheduler]\nmax_loaded_models = 1\n", encoding="utf-8")
    packaged_defaults.write_text("[scheduler]\nmax_loaded_models = 2\n", encoding="utf-8")

    sync = getattr(setup, "sync_packaged_defaults", None)
    assert callable(sync), "setup generation must synchronize packaged defaults"
    assert sync(tmp_path) is True
    assert packaged_defaults.read_bytes() == repository_defaults.read_bytes()
    assert sync(tmp_path) is False

from __future__ import annotations

import importlib.util
import json
import sys
import tomllib
from pathlib import Path

from local_ai_hub import __version__
from local_ai_hub.config import deep_merge
from local_ai_hub.features import FeatureSet
from local_ai_hub.generator import generate_global_policy, generate_mcp_tool_schemas
from local_ai_hub.hardware import profile_overrides


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("local_ai_hub_setup_t19", ROOT / "tools" / "setup.py")
assert SPEC and SPEC.loader
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


def _file_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_agent_config_merge_is_idempotent_and_parses_every_supported_host(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(setup, "get_user_homes", lambda: [home])
    codex_home = home / ".codex"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    install_skills = setup.install_agent_skills

    def confined_install_skills(install_dir, destination, **kwargs):
        assert destination.resolve().is_relative_to(tmp_path.resolve()), destination
        return install_skills(install_dir, destination, **kwargs)

    monkeypatch.setattr(setup, "install_agent_skills", confined_install_skills)

    json_configs = {
        ".claude.json": "mcpServers",
        ".gemini/settings.json": "mcpServers",
        ".gemini/config/mcp_config.json": "mcpServers",
        ".cursor/mcp.json": "mcpServers",
        ".codeium/windsurf/mcp_config.json": "mcpServers",
        ".copilot/mcp-config.json": "servers",
        ".local-ai/generic-mcp.json": "mcpServers",
        ".local-ai/vscode-mcp.json": "servers",
    }
    for relative, container in json_configs.items():
        path = home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"user_settings": {"keep": True}, container: {"external": {"command": "keep"}}}),
            encoding="utf-8",
        )
    codex_config = codex_home / "config.toml"
    codex_config.parent.mkdir(parents=True, exist_ok=True)
    codex_config.write_text(
        '[model]\nprovider = "user"\n\n[mcp_servers.external]\ncommand = "keep"\nargs = []\n',
        encoding="utf-8",
    )

    cfg = {
        "setup": {"backup_existing_configs": False},
        "tool_policy": {"install_global_instructions": False},
        "code_intelligence": {"direct_agent_mcp": False, "serena_enabled": False},
        "agents": {
            "agent_skills_standard": False,
            "codex": True,
            "claude": True,
            "gemini": True,
            "cursor": True,
            "windsurf": True,
            "copilot": True,
            "extra_mcp_json_paths": [str(home / ".local-ai" / "generic-mcp.json")],
            "extra_vscode_mcp_paths": [str(home / ".local-ai" / "vscode-mcp.json")],
        },
    }
    install_dir = tmp_path / "install"

    def configure() -> None:
        setup.configure_agents(install_dir, Path(sys.executable), None, cfg, include_companion=False)

    configure()

    for relative, container in json_configs.items():
        payload = json.loads((home / relative).read_text(encoding="utf-8"))
        assert payload["user_settings"] == {"keep": True}
        assert payload[container]["external"]["command"] == "keep"
        assert "local-ai" in payload[container]
    codex_payload = tomllib.loads(codex_config.read_text(encoding="utf-8"))
    assert codex_payload["model"]["provider"] == "user"
    assert codex_payload["mcp_servers"]["external"]["command"] == "keep"
    assert "local-ai" in codex_payload["mcp_servers"]

    generated = install_dir / "generated"
    assert json.loads((generated / "mcp-servers.json").read_text(encoding="utf-8"))["mcpServers"]
    assert json.loads((generated / "vscode-mcp.json").read_text(encoding="utf-8"))["servers"]
    for schema in sorted((generated / "schemas").glob("*.json")):
        assert isinstance(json.loads(schema.read_text(encoding="utf-8")), dict)

    first_run = _file_snapshot(tmp_path)
    configure()
    assert _file_snapshot(tmp_path) == first_run


def _assert_portable_keys_are_supported(config: dict, defaults: dict, prefix: str = "") -> None:
    for key, value in config.items():
        path = f"{prefix}.{key}" if prefix else key
        assert key in defaults, f"installer example key is absent from defaults: {path}"
        if isinstance(value, dict):
            assert isinstance(defaults[key], dict), f"installer table is not a defaults table: {path}"
            _assert_portable_keys_are_supported(value, defaults[key], path)


def test_dry_install_copy_keeps_portable_toml_version_models_policy_and_schemas(tmp_path):
    install_dir = tmp_path / "install-fixture"
    setup.copy_install_tree(install_dir, ROOT / "config.toml.example")

    config_text = (install_dir / "config.toml").read_text(encoding="utf-8")
    assert config_text == (ROOT / "config.toml.example").read_text(encoding="utf-8")
    config = tomllib.loads(config_text)
    defaults = tomllib.loads((install_dir / "defaults.toml").read_text(encoding="utf-8"))
    source_defaults = tomllib.loads(
        (install_dir / "src" / "local_ai_hub" / "defaults.toml").read_text(encoding="utf-8")
    )
    _assert_portable_keys_are_supported(config, defaults)
    assert defaults == source_defaults

    project = tomllib.loads((install_dir / "pyproject.toml").read_text(encoding="utf-8"))
    release = json.loads((install_dir / "RELEASE.json").read_text(encoding="utf-8"))
    assert project["project"]["version"] == release["version"] == __version__
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    assert "include config.toml.example" in manifest
    assert "include defaults.toml" in manifest
    assert project["tool"]["setuptools"]["package-data"]["local_ai_hub"] == [
        "defaults.toml",
        "automation_browser.js",
    ]
    assert (install_dir / "src" / "local_ai_hub" / "automation_browser.js").read_bytes() == (
        ROOT / "src" / "local_ai_hub" / "automation_browser.js"
    ).read_bytes()

    prompts = (
        (ROOT / "docs" / "INSTALL_PROMPT.md").read_text(encoding="utf-8"),
        (ROOT / "docs" / "UPDATE_PROMPT.md").read_text(encoding="utf-8"),
    )
    rollout_features = (
        "enriched_search",
        "batch_replacement",
        "diagnostic_artifacts",
        "local_diagnostic_dispatch",
    )
    for feature in rollout_features:
        assert defaults["features"][feature] is True
        assert config["features"][feature] is defaults["features"][feature]
        assert all(f"`features.{feature}`" in prompt for prompt in prompts)
    for gate in (
        "features.code_intelligence",
        "code_intelligence.enabled",
        "code_intelligence.serena_enabled",
    ):
        assert all(f"`{gate}`" in prompt for prompt in prompts)
    assert defaults["features"]["code_intelligence"] is True
    assert defaults["code_intelligence"]["enabled"] is True
    assert defaults["code_intelligence"]["serena_enabled"] is True

    model_docs = (ROOT / "docs" / "MODEL_CAPABILITIES.md").read_text(encoding="utf-8")
    for profile in ("integrated", "balanced", "high", "max"):
        models = profile_overrides(profile)["models"]
        for key in ("background_code", "fast_code", "general", "heavy_code", "reasoning", "vision"):
            assert f"`{models[key]}`" in model_docs, f"{profile}.{key} missing from model docs"

    effective = deep_merge(defaults, config)
    setup.write_generated_agent_manifests(install_dir, Path(sys.executable), None, effective)
    expected_schemas = generate_mcp_tool_schemas(effective)
    schema_dir = install_dir / "generated" / "schemas"
    actual_schema_names = {path.stem for path in schema_dir.glob("*.json")}
    assert actual_schema_names == set(expected_schemas)
    assert len(list(schema_dir.glob("*.json"))) == len(expected_schemas)
    features = FeatureSet.from_config(effective)
    expected_actions = {
        "local_ai_repo": features.supported_repo_actions(),
        "local_ai_task": features.supported_task_actions(),
        "local_ai_rag": features.supported_rag_actions(),
        "local_ai_coord": features.supported_coord_actions(),
    }
    assert "local_ai_command" not in expected_schemas
    for tool, actions in expected_actions.items():
        if tool not in expected_schemas:
            assert not actions, f"disabled tool {tool} unexpectedly has actions"
            continue
        assert expected_schemas[tool]["parameters"]["properties"]["action"]["enum"] == actions
    for name, expected in expected_schemas.items():
        serialized_expected = json.loads(json.dumps(expected))
        assert json.loads((schema_dir / f"{name}.json").read_text(encoding="utf-8")) == serialized_expected
    policy = (install_dir / "generated" / "agent-policy.md").read_text(encoding="utf-8")
    assert policy == generate_global_policy(effective) + "\n"


def test_install_update_security_prompts_match_current_http_contract() -> None:
    prompts = (
        (ROOT / "docs" / "INSTALL_PROMPT.md").read_text(encoding="utf-8"),
        (ROOT / "docs" / "UPDATE_PROMPT.md").read_text(encoding="utf-8"),
    )
    for prompt in prompts:
        normalized = prompt.lower().replace("`", "")
        assert "loopback-only" in normalized
        assert "no remote-access or remote-control mode" in normalized
        assert "server.client_host" in normalized and "security.allow_remote" in normalized
        assert "overrides are removed and rejected" in normalized
        assert "there is no remote-access switch" in normalized
        assert "at least 16 characters" not in normalized
        assert "empty api_token" in normalized and "unauthenticated" in normalized
        assert "agents, chats, projects and worktrees are not tenants" in normalized
        assert "retired fields/headers reject explicitly" in normalized
        for unsupported_claim in (
            "api_token_permissions grants",
            "principal namespace uses",
            "maximum 32",
            "hmac-sha256",
            "effective tenant as `root-`",
        ):
            assert unsupported_claim not in normalized

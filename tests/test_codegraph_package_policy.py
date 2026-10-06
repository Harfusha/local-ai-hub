import json
import tomllib
from pathlib import Path
from local_ai_hub.features import FeatureSet
from local_ai_hub.external_tools import ExternalCodeIntelligence
from local_ai_hub.generator import write_all_generated


ROOT = Path(__file__).resolve().parents[1]


def test_setup_has_no_codegraph_installer_or_mcp_path():
    source = (ROOT / "tools" / "setup.py").read_text(encoding="utf-8")
    assert "codegraph" not in source.casefold()


def test_generated_mcp_config_ignores_stale_codegraph_flag(tmp_path):
    with (ROOT / "defaults.toml").open("rb") as config_file:
        cfg = tomllib.load(config_file)
    cfg.setdefault("code_intelligence", {}).update(
        codegraph_enabled=True,
        direct_agent_mcp=True,
    )
    write_all_generated(cfg, tmp_path, tmp_path / "hub-python")
    generated = json.loads((tmp_path / "generated" / "mcp-servers.json").read_text(encoding="utf-8"))

    assert "codegraph" not in generated["mcpServers"]


def test_codegraph_removed_from_configs_and_features():
    for path in (ROOT / "defaults.toml", ROOT / "src" / "local_ai_hub" / "defaults.toml"):
        with path.open("rb") as config_file:
            cfg = tomllib.load(config_file)
            assert "codegraph_package" not in cfg.get("tools", {})
            assert "codegraph_enabled" not in cfg.get("code_intelligence", {})

    feat = FeatureSet({})
    assert not hasattr(feat, "codegraph")

    ext = ExternalCodeIntelligence({"code_intelligence": {"enabled": True}})
    try:
        assert ext.backend_available("codegraph") is False
    finally:
        ext.close()

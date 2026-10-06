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
        assert not hasattr(ext, "codegraph_enabled")
        assert not hasattr(ext, "query_codegraph")
        assert not hasattr(ext, "_codegraph_sessions")
        res = ext.query(".", "test", backend="codegraph")
        assert res == {"success": False, "backend": "codegraph", "unavailable": True, "error": "unsupported backend: codegraph"}
        assert res.get("success") is False
        assert res.get("unavailable") is True
        assert ext.index("codegraph", ".").get("success") is False
        assert "codegraph" not in ext.status()
        assert ext.reset_sessions("codegraph").get("success") is False
        assert not hasattr(ext, "_codegraph")
        ext.close()
    finally:
        ext.close()



def test_runtime_has_no_managed_codegraph_or_kuzu_references():
    runtime = ROOT / "src" / "local_ai_hub"
    sources = [*runtime.rglob("*.py"), runtime / "defaults.toml"]
    offenders = []
    for path in sources:
        content = path.read_text(encoding="utf-8").casefold()
        # Allow only the literal ignore-directory marker in the repository scanner.
        if path == ROOT / "src" / "local_ai_hub" / "repo_tools.py":
            content = content.replace('".codegraphcontext"', "", 1)
        if "codegraph" in content or "kuzu" in content:
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []

    from local_ai_hub import mcp_server

    assert "graph" not in mcp_server._REPO_ACTIONS
    assert "cross_project_graph" in mcp_server._REPO_ACTIONS
    assert "cross_repo_graph" in mcp_server._REPO_ACTIONS
    assert ".codegraphcontext/" in (ROOT / ".gitignore").read_text(encoding="utf-8")


def test_native_graph_mcp_actions_still_reach_cross_project_route(monkeypatch, tmp_path):
    from local_ai_hub import mcp_server

    calls = []

    def fake_post(path, payload, **kwargs):
        calls.append((path, payload))
        return {"success": True}

    monkeypatch.setattr(mcp_server.FEATURES, "repo", True)
    monkeypatch.setattr(mcp_server.CLIENT, "post", fake_post)

    for action in ("cross_project_graph", "cross_repo_graph"):
        result = mcp_server._local_ai_repo_impl(action=action, root=str(tmp_path))
        assert result["success"] is True

    expected_payload = {"roots": [str(tmp_path)]}
    assert calls == [
        ("/api/cross_project_graph", expected_payload),
        ("/api/cross_project_graph", expected_payload),
    ]


def test_packaging_metadata_has_no_managed_codegraph_or_kuzu_dependencies():
    package_files = [ROOT / "pyproject.toml", *ROOT.glob("requirements*.txt"), ROOT / "tools" / "setup.py"]
    offenders = []
    for path in package_files:
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8").casefold()
        if "codegraph" in content or "kuzu" in content:
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []

import json
from pathlib import Path

from tools.release_check import run_checks


def test_defaults_consistency_ignores_newline_style_but_rejects_value_drift(tmp_path):
    root = tmp_path
    (root / "src" / "local_ai_hub").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "src" / "local_ai_hub" / "__init__.py").write_text(
        '__version__ = "1.0.0"\n', encoding="utf-8"
    )
    (root / "pyproject.toml").write_text(
        '[project]\nname = "test-hub"\nversion = "1.0.0"\n', encoding="utf-8"
    )
    (root / "RELEASE.json").write_text(
        json.dumps({"version": "1.0.0", "status": "production-ready"}),
        encoding="utf-8",
    )
    (root / "MANIFEST.in").write_text(
        "include config.toml.example\ninclude requirements-openvino.txt\n",
        encoding="utf-8",
    )
    for relative in (
        "README.md", "LICENSE", "SECURITY.md", "CONTRIBUTING.md",
        "docs/INSTALLATION.md", "docs/CONFIGURATION.md",
        "docs/MCP_AND_AGENTS.md", "docs/OPERATIONS.md",
    ):
        (root / relative).write_text("", encoding="utf-8")
    (root / "README.md").write_text("Local AI Hub 1.0.0\n", encoding="utf-8")
    (root / "CHANGELOG.md").write_text("## 1.0.0\n", encoding="utf-8")

    source_defaults = "[scheduler]\nmax_loaded_models = 1\n"
    packaged_defaults = "[scheduler]\r\nmax_loaded_models = 1\r\n"
    (root / "src" / "local_ai_hub" / "defaults.toml").write_bytes(
        source_defaults.encode("utf-8")
    )
    (root / "defaults.toml").write_bytes(packaged_defaults.encode("utf-8"))

    checks = {item["name"]: item for item in run_checks(root)["checks"]}
    assert checks["defaults-consistency"]["ok"] is True

    (root / "defaults.toml").write_text(
        "[scheduler]\nmax_loaded_models = 2\n", encoding="utf-8"
    )
    checks = {item["name"]: item for item in run_checks(root)["checks"]}
    assert checks["defaults-consistency"]["ok"] is False

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_codegraph_is_absent_from_hub_integrations() -> None:
    paths = (
        ROOT / "config.toml.example",
        ROOT / "src/local_ai_hub/external_tools.py",
        ROOT / "src/local_ai_hub/preprocess.py",
        ROOT / "src/local_ai_hub/retrieval.py",
        ROOT / "tools/doctor.py",
        ROOT / "tools/selftest.py",
        ROOT / "tools/telemetry_report.py",
        ROOT / "tools/uninstall.py",
    )
    for path in paths:
        assert "codegraph" not in path.read_text(encoding="utf-8").casefold(), path.name

    mcp = (ROOT / "src/local_ai_hub/mcp_server.py").read_text(encoding="utf-8")
    assert "codegraphcontext" not in mcp.casefold()
    contracts = (ROOT / "src/local_ai_hub/operation_contracts.py").read_text(encoding="utf-8")
    module = ast.parse(contracts)
    actions = next(
        ast.literal_eval(node.value)
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "_REPO_ACTIONS" for target in node.targets)
    )
    assert "graph" not in actions
    assert 'if action in {"semantic", "graph", "intelligence"}' not in mcp


def test_installation_keeps_standalone_recommendation() -> None:
    installation = (ROOT / "docs/INSTALLATION.md").read_text(encoding="utf-8")
    assert "CodeGraphContext" in installation
    assert "optional standalone" in installation

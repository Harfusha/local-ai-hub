from __future__ import annotations

import json
import ast
from pathlib import Path

from tools import uninstall


ROOT = Path(__file__).resolve().parents[1]


def test_codegraph_is_absent_from_hub_runtime_configuration_and_telemetry() -> None:
    paths = (
        ROOT / "config.toml.example",
        *ROOT.joinpath("src", "local_ai_hub").rglob("*.py"),
        *ROOT.joinpath("tools").rglob("*.py"),
    )

    for path in paths:
        assert "codegraph" not in path.read_text(encoding="utf-8").casefold(), path.name


def test_graph_is_not_a_local_ai_repo_action() -> None:
    source = (ROOT / "src" / "local_ai_hub" / "mcp_server.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    actions = next(
        ast.literal_eval(node.value)
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "_REPO_ACTIONS" for target in node.targets)
    )
    assert "graph" not in actions


def test_optional_codegraph_docs_use_current_gcf_extra_without_hub_integration() -> None:
    installation = (ROOT / "docs" / "INSTALLATION.md").read_text(encoding="utf-8")
    standalone = installation.split("## Optional standalone tool: CodeGraphContext", 1)[1]

    assert "not Hub dependencies or backends" in standalone
    assert 'pip install "codegraphcontext[gcf]==0.6.13"' in standalone
    assert "it does not configure Local AI Hub" in standalone


def test_uninstall_preserves_standalone_codegraph_mcp_entry(tmp_path: Path) -> None:
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "local-ai": {"command": "hub"},
                    "serena-local": {"command": "serena"},
                    "codegraph-local": {"command": "codegraph"},
                    "other-tool": {"command": "other"},
                }
            }
        ),
        encoding="utf-8",
    )

    uninstall.clean_json(config_path)

    servers = json.loads(config_path.read_text(encoding="utf-8"))["mcpServers"]
    assert set(servers) == {"codegraph-local", "other-tool"}


def test_ollama_readonly_prompt_does_not_claim_hub_codegraph_support() -> None:
    prompt = (ROOT / "src" / "local_ai_hub" / "ollama_subagents.py").read_text(encoding="utf-8")

    assert "code index" in prompt
    assert "semantic symbols, code graph" not in prompt.lower()

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
        source = path.read_text(encoding="utf-8")
        if path == ROOT / "src/local_ai_hub/repo_tools.py":
            # Directory quarantine is mandatory; it is not a backend integration.
            module = ast.parse(source)
            allowed = []
            for node in ast.walk(module):
                if not isinstance(node, ast.Assign):
                    continue
                if not any(
                    isinstance(target, ast.Name)
                    and target.id in {"_HARD_SEARCH_DIRS", "default_ignore_dirs"}
                    for target in node.targets
                ):
                    continue
                allowed.extend(
                    item for item in ast.walk(node.value)
                    if isinstance(item, ast.Constant) and item.value == ".codegraphcontext"
                )
            lines = source.splitlines(keepends=True)
            for node in sorted(allowed, key=lambda item: (item.lineno, item.col_offset), reverse=True):
                assert node.lineno == node.end_lineno
                line = lines[node.lineno - 1]
                lines[node.lineno - 1] = line[:node.col_offset] + line[node.end_col_offset:]
            source = "".join(lines)
        if path.name == "benchmark_t10_repository.py":
            source = source.replace('"tests/test_codegraph_package_policy.py"', "")
        assert "codegraph" not in source.casefold(), path.name


def test_graph_is_not_a_local_ai_repo_action() -> None:
    source = (ROOT / "src/local_ai_hub/operation_contracts.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    actions = next(
        ast.literal_eval(node.value)
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "_REPO_ACTIONS" for target in node.targets)
    )
    assert "graph" not in actions
    mcp = (ROOT / "src/local_ai_hub/mcp_server.py").read_text(encoding="utf-8")
    module = ast.parse(mcp)
    mcp_actions = next(
        ast.literal_eval(node.value)
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "_REPO_ACTIONS" for target in node.targets)
    )
    assert "graph" not in mcp_actions
    assert "codegraphcontext" not in mcp.casefold()
    assert 'if action in {"semantic", "graph", "intelligence"}' not in mcp



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


def test_codegraphcontext_remains_hard_scan_ignore(tmp_path: Path) -> None:
    from local_ai_hub.repo_tools import RepositoryTools, _HARD_SEARCH_DIRS

    hidden = tmp_path / ".codegraphcontext" / "private.py"
    hidden.parent.mkdir()
    hidden.write_text("needle private backend state\n", encoding="utf-8")
    visible = tmp_path / "public.py"
    visible.write_text("needle public source\n", encoding="utf-8")
    (tmp_path / ".local-ai.toml").write_text(
        '[path_overrides]\n".codegraphcontext/**" = "include"\n',
        encoding="utf-8",
    )
    tools = RepositoryTools({
        "server": {"state_dir": str(tmp_path / ".local-ai-hub")},
        "rag": {"ignore_dirs": []},
        "search": {"prefer_git_files": False, "use_ripgrep_if_available": False},
    })

    assert ".codegraphcontext" in _HARD_SEARCH_DIRS
    assert ".codegraphcontext" in tools.ignore_dirs
    targeted = tools.search_paths(
        str(tmp_path), "needle", [".codegraphcontext/private.py", "public.py"],
        force_include_paths=[".codegraphcontext/private.py"],
    )
    broad = tools.search(str(tmp_path), "needle")

    assert targeted["success"] is True
    assert broad["success"] is True
    assert [row["path"] for row in targeted["results"]] == ["public.py"]
    assert [row["path"] for row in broad["results"]] == ["public.py"]
    assert targeted["scanned_files"] == 1

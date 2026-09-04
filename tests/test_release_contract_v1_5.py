from __future__ import annotations

import json
from pathlib import Path

from local_ai_hub import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_release_metadata_and_documentation_are_1_5():
    assert __version__ == "1.5.0"
    assert 'version = "1.5.0"' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    release = json.loads((ROOT / "RELEASE.json").read_text(encoding="utf-8"))
    assert release["version"] == "1.5.0" and release["status"] == "production-ready"
    required = {
        "ARCHITECTURE.md", "INSTALLATION.md", "CONFIGURATION.md", "MCP_AND_AGENTS.md",
        "HTTP_API.md", "DASHBOARD.md", "OPERATIONS.md", "SECURITY_MODEL.md",
        "TESTING.md", "TROUBLESHOOTING.md",
    }
    assert required <= {p.name for p in (ROOT / "docs").glob("*.md")}


def test_release_has_compact_mcp_surface_and_tool_first_policy():
    source = (ROOT / "src" / "local_ai_hub" / "mcp_server.py").read_text(encoding="utf-8")
    assert source.count("@mcp.tool()") == 7
    assert "CALL THIS BEFORE broad repository reads" in source
    skill = (ROOT / "skills" / "local-ai-orchestrator" / "SKILL.md").read_text(encoding="utf-8")
    assert "before broad repository exploration" in skill
    assert "semantic" in skill and "CodeGraphContext" in skill and "local_ai_command" in skill


def test_no_personal_paths_or_runtime_payloads_in_tracked_release_sources():
    forbidden = ("C:" + "\\Users\\" + "Adam", "/Users/" + "Adam", "DROP" + "IN", "RTX " + "4060")
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in {".git", "__pycache__", ".pytest_cache", ".venv", "tool-envs", "state", "data", "generated"} for part in path.parts):
            continue
        if path.suffix in {".pyc", ".sqlite3", ".db"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        assert not any(token in text for token in forbidden), f"personal/legacy token in {path.relative_to(ROOT)}"


def test_telemetry_export_defaults_inside_state_dir(tmp_path: Path):
    from tools import telemetry_report

    output = telemetry_report._default_output_path(tmp_path / "state")
    assert output.parent == (tmp_path / "state" / "diagnostics").resolve()
    assert output.name.startswith("local-ai-diagnostics-")
    assert output.suffix == ".json"


def test_mcp_wrapper_executes_against_v2_server_api_shape(tmp_path: Path):
    """Exercise the wrapper against the documented MCP SDK v2 import/decorator shape.

    The CI dependency install additionally imports the real SDK. This local stub keeps the
    release test deterministic/offline while catching accidental FastMCP/v1 regressions.
    """
    import os
    import subprocess
    import sys
    pkg = tmp_path / "mcp" / "server"
    pkg.mkdir(parents=True)
    (tmp_path / "mcp" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "__init__.py").write_text(
        "class MCPServer:\n"
        "    def __init__(self, name): self.name=name; self.tools=[]\n"
        "    def tool(self):\n"
        "        def deco(fn): self.tools.append(fn); return fn\n"
        "        return deco\n"
        "    def run(self): return None\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(tmp_path) + os.pathsep + str(ROOT / "src")
    cp = subprocess.run(
        [sys.executable, "-m", "local_ai_hub.mcp_server"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=10,
    )
    assert cp.returncode == 0, cp.stderr


def test_v15_agent_and_python_matrix_contracts():
    defaults = (ROOT / "defaults.toml").read_text(encoding="utf-8")
    for key in ("cursor = true", "windsurf = true", "copilot = true", "git_files_timeout_seconds", "watcher_refresh_seconds"):
        assert key in defaults
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for version in ("3.11", "3.12", "3.13", "3.14"):
        assert version in ci
    setup_source = (ROOT / "tools" / "setup.py").read_text(encoding="utf-8")
    assert ".cursor" in setup_source and "windsurf" in setup_source and ".copilot" in setup_source


def test_v15_bounded_runtime_and_sqlite_contracts():
    defaults = (ROOT / "defaults.toml").read_text(encoding="utf-8")
    for key in ("max_concurrent_requests", "request_body_timeout_seconds", "max_caller_wait_timeout_seconds", "coalesced_wait_seconds", "extra_mcp_json_paths", "extra_vscode_mcp_paths"):
        assert key in defaults
    assert (ROOT / "src" / "local_ai_hub" / "sqlite_support.py").exists()
    http = (ROOT / "src" / "local_ai_hub" / "http_server.py").read_text(encoding="utf-8")
    assert "BoundedSemaphore" in http and "Retry-After: 1" in http and "APP.scheduler.submit" in http
    scheduler = (ROOT / "src" / "local_ai_hub" / "scheduler.py").read_text(encoding="utf-8")
    assert "max_caller_wait_timeout_seconds" in scheduler and "model_switch_failure_cooldown_seconds" in scheduler


def test_v15_agent_policy_and_packaging_hardening_contracts():
    skill = (ROOT / "skills" / "local-ai-orchestrator" / "SKILL.md").read_text(encoding="utf-8")
    assert "exactly once" in skill and "in_progress=true" in skill and "never poll" in skill
    for phrase in ("READ-ONLY AUDIT CONTRACT", "git worktree add", "terminal=true", "allow_write", "Codex controls subagent permissions per task"):
        assert phrase in skill
    setup_source = (ROOT / "tools" / "setup.py").read_text(encoding="utf-8")
    assert "extra_mcp_json_paths" in setup_source and "extra_vscode_mcp_paths" in setup_source
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "wheel-smoke" in ci
    install_sh = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "zypper" in install_sh and "apk" in install_sh and "pacman" in install_sh
    install_ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
    assert "Python314" in install_ps1

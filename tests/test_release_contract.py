from __future__ import annotations

import json
import re
from pathlib import Path

from local_ai_hub import __version__
from local_ai_hub.generator import write_all_generated

ROOT = Path(__file__).resolve().parents[1]


def test_release_metadata_and_documentation_are_current():
    assert __version__ == "3.0.0"
    assert 'version = "3.0.0"' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    release = json.loads((ROOT / "RELEASE.json").read_text(encoding="utf-8"))
    assert release["version"] == "3.0.0" and release["status"] == "production-ready"
    assert f'placeholder: "{__version__}"' in (ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml").read_text(encoding="utf-8")
    required = {
        "ARCHITECTURE.md", "INSTALLATION.md", "CONFIGURATION.md", "MCP_AND_AGENTS.md",
        "HTTP_API.md", "DASHBOARD.md", "OPERATIONS.md", "SECURITY_MODEL.md",
        "TESTING.md", "TROUBLESHOOTING.md",
    }
    assert required <= {p.name for p in (ROOT / "docs").glob("*.md")}



def test_release_uses_only_current_local_ai_hub_contracts():
    roots = [ROOT / "src", ROOT / "tools", ROOT / "docs", ROOT / "skills", ROOT / "tests"]
    files = [ROOT / name for name in ("README.md", "CHANGELOG.md", "FEATURES.md", "AGENTS.md", "CONTRIBUTING.md", "SECURITY.md")]
    for base in roots:
        files.extend(path for path in base.rglob("*") if path.is_file() and path.suffix in {".py", ".md", ".toml", ".yml", ".yaml"})

    current_major = int(__version__.split(".", 1)[0])
    historical_majors = tuple(str(n) for n in range(1, current_major))
    # The v3 contract no longer contains migration/version markers.  The word
    # "blended" remains valid for the compatibility estimate of old telemetry
    # rows, so it must not be treated as a historical release marker.
    forbidden = ["bundle" + "_version", "ALTER" + " TABLE"]
    for major in historical_majors:
        forbidden.extend((f"Version {major}.", f"version {major}.", f"/v{major}/"))
    for path in files:
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"historical contract token {token!r} in {path.relative_to(ROOT)}"

    old_major_pattern = "|".join(re.escape(major) for major in historical_majors)
    historical_name = re.compile(rf"(?:^|[_-])v(?:{old_major_pattern})(?:[_.-]|$)|phase[0-9]+", re.IGNORECASE)
    for path in ROOT.rglob("*"):
        if path.is_file() and not any(part in {
            ".git", "__pycache__", ".pytest_cache", ".venv", "tool-envs", "state", "data",
            "generated", "backups", "migration-backups",
        } for part in path.parts):
            assert not historical_name.search(path.name), f"historical release name: {path.relative_to(ROOT)}"

def test_release_has_compact_mcp_surface_and_tool_first_policy(tmp_path: Path):
    source = (ROOT / "src" / "local_ai_hub" / "mcp_server.py").read_text(encoding="utf-8")
    assert source.count("@mcp.tool()") == 8
    assert "CALL THIS BEFORE broad repository reads" in source
    write_all_generated({"models": {"fast_code": "qwen2.5-coder:7b"}}, tmp_path)
    skill = (tmp_path / "skills" / "local-ai-orchestrator" / "SKILL.md").read_text(encoding="utf-8")
    assert "before broad repository exploration" in skill
    assert "semantic" in skill and "CodeGraphContext" in skill and "local_ai_command" in skill


def test_guarded_context_release_contract_documents_default_flow_and_fallbacks():
    configuration = (ROOT / "docs" / "CONFIGURATION.md").read_text(encoding="utf-8")
    http_api = (ROOT / "docs" / "HTTP_API.md").read_text(encoding="utf-8")
    testing = (ROOT / "docs" / "TESTING.md").read_text(encoding="utf-8")
    policy = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    combined = "\n".join((configuration, http_api, testing, policy))

    required = (
        "[context.preloads]",
        'local_ai_repo(action=\"context\")',
        "plan",
        "edit",
        "review",
        "test",
        "handoff",
        "evidence_ids",
        "repo_revision",
        "stale",
        "requires_approval",
        "Deterministic/indexed evidence is authoritative",
        "legacy fast/full",
    )
    assert all(term in combined for term in required)

    for code in (
        "preload_missing",
        "code_intelligence_unavailable",
        "local_model_timeout",
        "agent_state_disabled",
    ):
        assert f'"{code}"' in http_api

    warning_fields = (
        "severity", "code", "message", "evidence_ids", "affected_paths",
        "recommended_action", "requires_approval",
    )
    assert all(field in http_api for field in warning_fields)


def test_no_personal_paths_or_runtime_payloads_in_tracked_release_sources():
    forbidden = ("C:" + "\\Users\\" + "Adam", "/Users/" + "Adam", "DROP" + "IN", "RTX " + "4060")
    skip_parts = {
        ".git", "__pycache__", ".pytest_cache", ".venv", "tool-envs", "state", "data", "generated",
        ".agents", ".serena", ".superpowers", "agy-contextless-workspace",
        "backups", "migration-backups", ".worktrees",
    }
    skip_files = {"ORIGINAL_REQUEST.md", ".coverage"}
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip_parts for part in path.parts) or path.name in skip_files or path.name.startswith(".coverage"):
            continue
        if path.suffix in {".pyc", ".sqlite3", ".db", ".zip", ".pkl"} or ".local-ai-hub-backup-" in path.name:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        assert not any(token in text for token in forbidden), f"forbidden release token in {path.relative_to(ROOT)}"


def test_telemetry_export_defaults_inside_state_dir(tmp_path: Path):
    from tools import telemetry_report

    output = telemetry_report._default_output_path(tmp_path / "state")
    assert output.parent == (tmp_path / "state" / "diagnostics").resolve()
    assert output.name.startswith("local-ai-diagnostics-")
    assert output.suffix == ".json"


def test_agent_and_python_matrix_contracts():
    defaults = (ROOT / "defaults.toml").read_text(encoding="utf-8")
    for key in ("cursor = true", "windsurf = true", "copilot = true", "git_files_timeout_seconds", "watcher_refresh_seconds"):
        assert key in defaults
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for version in ("3.11", "3.12", "3.13", "3.14"):
        assert version in ci
    setup_source = (ROOT / "tools" / "setup.py").read_text(encoding="utf-8")
    assert ".cursor" in setup_source and "windsurf" in setup_source and ".copilot" in setup_source


def test_bounded_runtime_and_sqlite_contracts():
    defaults = (ROOT / "defaults.toml").read_text(encoding="utf-8")
    for key in ("max_concurrent_requests", "request_body_timeout_seconds", "max_caller_wait_timeout_seconds", "coalesced_wait_seconds", "extra_mcp_json_paths", "extra_vscode_mcp_paths"):
        assert key in defaults
    assert (ROOT / "src" / "local_ai_hub" / "sqlite_support.py").exists()
    http = (ROOT / "src" / "local_ai_hub" / "http_server.py").read_text(encoding="utf-8")
    assert "BoundedSemaphore" in http and "Retry-After: 1" in http and "APP.scheduler.submit" in http
    scheduler = (ROOT / "src" / "local_ai_hub" / "scheduler.py").read_text(encoding="utf-8")
    assert "max_caller_wait_timeout_seconds" in scheduler and "model_switch_failure_cooldown_seconds" in scheduler


def test_agent_policy_and_packaging_hardening_contracts(tmp_path: Path):
    write_all_generated({"models": {"fast_code": "qwen2.5-coder:7b"}}, tmp_path)
    skill = (tmp_path / "skills" / "local-ai-orchestrator" / "SKILL.md").read_text(encoding="utf-8")
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


def test_agent_prompts_require_durable_task_checkpoints_and_one_bounded_wait():
    for name in ("INSTALL_PROMPT.md", "UPDATE_PROMPT.md"):
        prompt = (ROOT / "docs" / name).read_text(encoding="utf-8")
        assert "task_create" in prompt
        assert "task_checkpoint" in prompt
        assert "one bounded wait" in prompt


def test_generated_skills_are_not_required_in_source_tree():
    assert not (ROOT / "skills" / "local-ai-orchestrator" / "SKILL.md").exists()
    assert not (ROOT / "skills" / "token-economizer" / "SKILL.md").exists()


def test_update_prompt_uses_branch_safe_pull_and_generated_artifact_wording():
    prompt = (ROOT / "docs" / "UPDATE_PROMPT.md").read_text(encoding="utf-8")
    assert "git pull --ff-only origin main" not in prompt
    assert "pull --ff-only" in prompt
    assert "checked-in/generated schemas" not in prompt
    assert "generated schemas" in prompt

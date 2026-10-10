from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from local_ai_hub import __version__
from local_ai_hub.generator import write_all_generated
from local_ai_hub.hardware import profile_overrides

ROOT = Path(__file__).resolve().parents[1]


def test_release_metadata_and_documentation_are_current():
    assert __version__ == "4.0.0"
    assert 'version = "4.0.0"' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    release = json.loads((ROOT / "RELEASE.json").read_text(encoding="utf-8"))
    assert release["version"] == "4.0.0" and release["status"] == "production-ready"
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
        for path in base.rglob("*"):
            if path.is_file() and path.suffix in {".py", ".md", ".toml", ".yml", ".yaml"}:
                if path.relative_to(ROOT).parts[:2] == ("docs", "superpowers"):
                    continue
                files.append(path)

    current_major = int(__version__.split(".", 1)[0])
    historical_majors = tuple(str(n) for n in range(1, current_major))
    # The v3 contract no longer contains migration/version markers.  The word
    # "blended" remains valid for the compatibility estimate of old telemetry
    # rows, so it must not be treated as a historical release marker.
    forbidden = ["bundle" + "_version"]
    for major in historical_majors:
        forbidden.extend((f"Version {major}.", f"version {major}.", f"/v{major}/"))
    for path in files:
        text = path.read_text(encoding="utf-8")
        if path == ROOT / "src" / "local_ai_hub" / "leases.py":
            rebuild = 'ALTER TABLE lease_waits_new RENAME TO lease_waits'
            assert text.count(rebuild) == 1
            text = text.replace(rebuild, "")
        for token in forbidden:
            assert token not in text, f"historical contract token {token!r} in {path.relative_to(ROOT)}"

    old_major_pattern = "|".join(re.escape(major) for major in historical_majors)
    historical_name = re.compile(rf"(?:^|[_-])v(?:{old_major_pattern})(?:[_.-]|$)|phase[0-9]+", re.IGNORECASE)
    for path in ROOT.rglob("*"):
        if re.match(r"t\d{2}[-_].*(?:-|_)v\d+", path.name, re.IGNORECASE):
            continue  # task/test artifact version, not a Local AI Hub product release
        relative = path.relative_to(ROOT)
        if relative.parts[:2] == ("docs", "integration") or (
            path.parent == ROOT / "docs"
            and re.match(r"(?:integration-|SYNC_|STASH_|T\d+.*(?:SYNC|HANDOFF|FILES)|WORKTREE_|PRIORITY_STASH)", path.name, re.IGNORECASE)
        ):
            continue  # internal integration ledgers are excluded from the source distribution
        if path.is_file() and not any(part in {
            ".git", "__pycache__", ".pytest_cache", ".venv", "tool-envs", "state", "data", ".handoff", "artifacts",
            "generated", "backups", "migration-backups", "dist", "build", "handoff", "T18-review-artifacts-20260928",
        } for part in path.parts):
            assert not historical_name.search(path.name), f"historical release name: {path.relative_to(ROOT)}"

def test_release_has_compact_mcp_surface_and_tool_first_policy(tmp_path: Path):
    source = (ROOT / "src" / "local_ai_hub" / "mcp_server.py").read_text(encoding="utf-8")
    assert source.count("@mcp.tool()") == 8
    assert "CALL THIS FIRST before broad repository reads" in source
    assert '"mode": "full" if mode == "full" else "adaptive" if mode == "adaptive" else "fast"' in source
    assert "CodeGraphContext" not in source and "handmade grep terms" in source
    write_all_generated({"models": {"fast_code": "qwen2.5-coder:7b"}}, tmp_path)
    skill = (tmp_path / "skills" / "local-ai-orchestrator" / "SKILL.md").read_text(encoding="utf-8")
    assert "before native reads, grep" in skill
    assert "semantic" in skill and "local_ai_command" in skill
    assert "CodeGraphContext" in skill and "optional standalone CLI/MCP" in skill
    installation = (ROOT / "docs" / "INSTALLATION.md").read_text(encoding="utf-8")
    assert "## Optional standalone tool: CodeGraphContext" in installation
    assert "CodeGraphContext and KuzuDB are not Hub dependencies or backends" in installation
    assert "install it directly in the target repository or environment" in installation
    assert "This connects an agent directly to CodeGraphContext; it does not configure Local AI Hub" in installation


def test_canonical_prompts_share_profile_and_installation_docs_own_standalone_setup():
    install = (ROOT / "docs" / "INSTALL_PROMPT.md").read_text(encoding="utf-8")
    update = (ROOT / "docs" / "UPDATE_PROMPT.md").read_text(encoding="utf-8")
    installation = (ROOT / "docs" / "INSTALLATION.md").read_text(encoding="utf-8")
    sdk = (ROOT / "docs" / "PYTHON_SDK.md").read_text(encoding="utf-8")
    install_routing = next(
        line for line in install.splitlines()
        if line.startswith("Local model routing starts")
    )
    update_routing = next(
        line for line in update.splitlines()
        if line.startswith("Local model routing starts")
    )
    assert install_routing == update_routing
    for profile in ("integrated", "balanced", "high", "max"):
        models = profile_overrides(profile)["models"]
        route_keys = ("background_code", "fast_code", "general", "heavy_code", "reasoning", "vision")
        assert all(models[key] in install_routing for key in route_keys), profile
    assert "CodeGraphContext/KuzuDB was removed from Local AI Hub." in install + update
    assert "optional standalone CLI/MCP" in install + update
    assert "It is not a Hub dependency, runtime, backend, or MCP integration." in install + update
    assert "## Optional standalone tool: CodeGraphContext" in installation
    assert "CodeGraphContext and KuzuDB are not Hub dependencies or backends" in installation
    assert "install it directly in the target repository or environment" in installation
    assert "T10 owns broader runtime" not in install + update


def test_active_docs_and_historical_plan_do_not_claim_codegraph_as_hub_backend():
    architecture = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    dashboard = (ROOT / "docs" / "DASHBOARD.md").read_text(encoding="utf-8")
    feature_audit = (ROOT / "docs" / "FEATURE_AUDIT_V4.md").read_text(encoding="utf-8")
    mcp = (ROOT / "docs" / "MCP_AND_AGENTS.md").read_text(encoding="utf-8")
    old_plan = (ROOT / "docs" / "superpowers" / "plans" / "2026-09-22-adaptive-retrieval-orchestrator.md").read_text(encoding="utf-8")
    assert "CodeGraphContext/KuzuDB are not Hub backends" in architecture + dashboard + mcp
    assert "CodeGraphContext/KuzuDB" in feature_audit
    assert "optional standalone CLI/MCP tool" in feature_audit
    assert "Hub does not install, configure, preprocess, invoke, or report it" in feature_audit
    assert "2026-09-21 audit snapshot" in feature_audit
    assert "not current host status" in feature_audit
    assert "**Superseded by T19" in old_plan
    assert "not current Hub behavior" in old_plan
    assert "do not establish current support or health" in old_plan


def test_t20_acceptance_matrix_is_preintegration_and_records_blocking_gates():
    plan = (ROOT / "docs" / "superpowers" / "plans" / "2026-09-25-t19-install-sdk-rollout.md").read_text(encoding="utf-8")
    matrix = plan.split("## Cross-track release acceptance matrix", 1)[1].split("## Execution Ledger", 1)[0]
    assert "PRE-INTEGRATION" in matrix
    assert "T01–T19 are not integrated into one revision" in matrix
    assert "API inventory is metadata only; operation behavior remains unverified" in matrix
    assert "final pass cannot be given" in matrix
    assert "clean-host Windows and Linux" in matrix
    assert "60-minute mixed workload" in matrix
    assert "verify_completion" in matrix


def test_python_sdk_documents_seven_common_workflows():
    sdk = (ROOT / "docs" / "PYTHON_SDK.md").read_text(encoding="utf-8")
    for step in (
        "/api/repo/callers",
        "/api/context/pack",
        "verify_completion",
        "continue_conversation",
        "/api/async-jobs",
        "task_resume",
        "/api/evidence/get",
    ):
        assert step in sdk


def test_installation_docs_match_declared_python_extras():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    expected = {
        extra: {
            re.split(r"[<>=!~]", requirement, maxsplit=1)[0]
            for requirement in requirements
        }
        for extra, requirements in project["project"]["optional-dependencies"].items()
    }
    installation = (ROOT / "docs" / "INSTALLATION.md").read_text(encoding="utf-8")
    extras_section = installation.split("### Optional Python extras\n", 1)[1].split("\n### ", 1)[0]
    rows = re.findall(r"^\| `([^`]+)` \| (.+?) \|$", extras_section, re.MULTILINE)
    documented = {
        extra: set(re.findall(r"`([^`]+)`", dependencies))
        for extra, dependencies in rows
    }

    assert len(rows) == len(expected)
    assert documented == expected


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

    for code in ("preload_missing_file", "agent_state_disabled"):
        assert f'"{code}"' in http_api

    assert '"preload_missing"' not in http_api
    assert "context_source" in http_api and "deterministic-fast" in http_api
    assert "continuation" in http_api
    assert "model_degraded" in http_api and "model_degraded_reason" in http_api
    assert "code_intelligence_unavailable" not in http_api
    assert "local_model_timeout" not in http_api

    warning_fields = (
        "severity", "code", "message", "evidence_ids", "affected_paths",
        "recommended_action", "requires_approval",
    )
    assert all(field in http_api for field in warning_fields)


def test_release_docs_match_stable_defaults_and_ci_gate():
    defaults = tomllib.loads((ROOT / "defaults.toml").read_text(encoding="utf-8"))
    assert defaults["agent_state"] == {
        "enabled": True,
        "event_retention_days": 30,
        "max_payload_bytes": 65536,
        "snapshot_interval_events": 50,
        "cleanup_batch_size": 100,
    }

    configuration = (ROOT / "docs" / "CONFIGURATION.md").read_text(encoding="utf-8")
    for claim in (
        "event_retention_days = 30",
        "max_payload_bytes = 65536",
        "snapshot_interval_events = 50",
        "cleanup_batch_size = 100",
    ):
        assert claim in configuration
    assert "`retention_days = 30`" not in configuration
    assert "max_event_bytes = 65536" not in configuration

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "BAAI/bge-small-en-v1.5" in readme
    assert "bge-m3" not in readme
    assert "NPU hardware is detected" in readme
    assert "Intel GPU is detected with the `integrated` profile" in readme

    testing = (ROOT / "docs" / "TESTING.md").read_text(encoding="utf-8")
    for step in ("release_check.py", "release_check.py --post-test", "git clean -fdX", "check_dashboard.py"):
        assert step in testing


def test_no_personal_paths_or_runtime_payloads_in_tracked_release_sources():
    forbidden = ("C:" + "\\Users\\" + "Adam", "/Users/" + "Adam", "DROP" + "IN", "RTX " + "4060")
    skip_parts = {
        ".git", "__pycache__", ".pytest_cache", ".venv", "tool-envs", "state", "data", "generated",
        ".agents", ".serena", ".superpowers", ".handoff", ".t03-root-current-overlay", "artifacts", "agy-contextless-workspace",
        "backups", "migration-backups", ".worktrees", "handoff", "T18-review-artifacts-20260928",
    }
    skip_files = {"ORIGINAL_REQUEST.md", ".coverage"}
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip_parts for part in path.parts) or path.name in skip_files or path.name.startswith(".coverage"):
            continue
        if path.parent == ROOT / "docs" and path.name.startswith("integration-"):
            continue  # internal integration notes are excluded from the source distribution
        relative = path.relative_to(ROOT)
        if relative.parts[:2] == ("docs", "integration") or (
            path.parent == ROOT / "docs"
            and re.match(r"(?:SYNC_|STASH_|T\d+.*(?:SYNC|HANDOFF|FILES)|WORKTREE_|PRIORITY_STASH)", path.name, re.IGNORECASE)
        ):
            continue
        # MANIFEST.in excludes release-plan docs from the source distribution.
        if path.relative_to(ROOT).parts[:2] == ("docs", "superpowers"):
            continue
        if path.suffix in {".pyc", ".sqlite3", ".db", ".zip", ".pkl"} or ".local-ai-hub-backup-" in path.name:
            continue
        relative = path.relative_to(ROOT)
        if relative.parts[0].startswith(".t") and "overlay" in relative.parts[0]:
            continue  # internal candidate overlays are not release sources
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


def test_generated_skills_are_ignored_in_source_tree():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in (
        "/skills/local-ai-orchestrator/SKILL.md",
        "/skills/local-ai-orchestrator/references/*.md",
        "/skills/token-economizer/SKILL.md",
    ):
        assert pattern in gitignore


def test_update_prompt_uses_branch_safe_pull_and_generated_artifact_wording():
    prompt = (ROOT / "docs" / "UPDATE_PROMPT.md").read_text(encoding="utf-8")
    assert "git pull --ff-only origin main" not in prompt
    assert "pull --ff-only" in prompt
    assert "checked-in/generated schemas" not in prompt
    assert "generated schemas" in prompt


def test_public_contract_notes_match_install_update_and_generated_skill(tmp_path: Path):
    write_all_generated({"models": {"fast_code": "qwen2.5-coder:7b"}}, tmp_path)
    prompts = [
        (ROOT / "docs" / "INSTALL_PROMPT.md").read_text(encoding="utf-8"),
        (ROOT / "docs" / "UPDATE_PROMPT.md").read_text(encoding="utf-8"),
    ]
    mcp_docs = (ROOT / "docs" / "MCP_AND_AGENTS.md").read_text(encoding="utf-8")
    generated = (tmp_path / "skills" / "local-ai-orchestrator" / "SKILL.md").read_text(encoding="utf-8")
    generic_manifest = json.loads((tmp_path / "generated" / "mcp-servers.json").read_text(encoding="utf-8"))
    vscode_manifest = json.loads((tmp_path / "generated" / "vscode-mcp.json").read_text(encoding="utf-8"))
    rag_schema = json.loads((tmp_path / "generated" / "schemas" / "local_ai_rag.json").read_text(encoding="utf-8"))
    generic_entry = generic_manifest["mcpServers"]["local-ai"]
    vscode_entry = vscode_manifest["servers"]["local-ai"]
    assert generic_entry["args"] == ["-m", "local_ai_hub.mcp_server"]
    assert generic_entry["env"]["LOCAL_AI_AGENT"] == "generic"
    assert vscode_entry["type"] == "stdio"
    assert vscode_entry["env"]["LOCAL_AI_AGENT"] == "copilot"
    rag_properties = rag_schema["parameters"]["properties"]
    assert {"ingest_document", "ingest_diagram"} <= set(rag_properties["action"]["enum"])
    assert {"content", "title", "metadata", "image_path", "caption"} <= rag_properties.keys()
    ingest_notes = (
        'non-empty `content` is required; `title` and `metadata` are optional.',
        'Success returns `success`, `workspace`, `document_title`, `chunks_ingested`, and `embedded`.',
        'Embedding errors do not stop lexical publication.',
        '`image_path` must resolve to an existing `.png`, `.jpg`, `.jpeg`, `.webp`, `.svg`, or `.bmp` file; `caption` and `metadata` are optional.',
        'Success also returns `diagram_indexed` and the resolved image path.',
    )
    synthesis_notes = (
        "`disable_llm_card_synthesis = true` skips LLM synthesis for unparsed file cards and stores deterministic stubs.",
        "It does not disable module/project cards:",
        '`prefer_deterministic_modules` and `prefer_deterministic_project` are separate preferences',
        "either path can use background LLM synthesis when deterministic output is unavailable or below its confidence threshold.",
        "Check active configuration and backend state before claiming synthesis is disabled.",
    )
    notes = (
        '`local_ai_rag(action="ingest_document")`',
        *ingest_notes,
        '`local_ai_repo(action="pipeline")` accepts closed step objects',
        '`local_ai_artifact(action="list")` does not require `artifact_id`',
        '`local_ai_coord(action="pubsub_poll")` accepts `after_seq`',
        '`local_ai_coord` bounds `max_tokens` to 0 through 100000.',
        "Repository pipelines serialize preprocessing mutation actions with other mutating steps.",
        "CodeGraphContext/KuzuDB was removed from Local AI Hub.",
        "optional standalone CLI/MCP",
        "It is not a Hub dependency, runtime, backend, or MCP integration.",
        *synthesis_notes,
    )

    for note in notes:
        assert all(note in prompt for prompt in prompts)
        assert note in generated
    assert all(note in mcp_docs for note in (*ingest_notes, *synthesis_notes))


def test_install_and_update_prompts_share_profile_aware_model_routing():
    install = (ROOT / "docs" / "INSTALL_PROMPT.md").read_text(encoding="utf-8")
    update = (ROOT / "docs" / "UPDATE_PROMPT.md").read_text(encoding="utf-8")
    routing_line = next(
        line for line in update.splitlines()
        if line.startswith("Local model routing starts from ")
    )

    assert routing_line in install.splitlines()
    stale_install_policies = (
        "qwen2.5-coder:1.5b` only for quick/simple tasks",
        "qwen2.5-coder:1.5b` for bounded extraction/simple work",
        "qwen2.5-coder:1.5b` only for quick/simple microtasks",
        "qwen2.5-coder:3b` for ordinary and more involved work",
        "qwen2.5-coder:3b` for ordinary bounded reasoning",
        "qwen2.5-coder:0.5b` only for preprocessing",
        "qwen3.5:9b` for extreme reasoning in the balanced profile",
    )
    assert all(policy not in install for policy in stale_install_policies)
    assert "high uses 1.5b/3b/7b/9b" not in update
    assert "max uses 1.5b/3b/9b for heavy routes" not in update


def test_feature_audit_marks_codegraph_as_removed_from_hub():
    audit = (ROOT / "docs" / "FEATURE_AUDIT_V4.md").read_text(encoding="utf-8")
    assert "Current status is removal from Hub" in audit
    assert "**Removed from Hub; optional standalone CLI/MCP tool**" in audit

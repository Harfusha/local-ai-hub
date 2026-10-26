"""Unit tests for host adapters, capability probes, and Superpowers integration."""

from pathlib import Path

from local_ai_hub.repo_plan.host_adapters import (
    PLANNER_BLOCK_START,
    PLANNER_BLOCK_END,
    SteeringManager,
    inject_managed_instructions,
    probe_host_capabilities,
    remove_managed_instructions,
)


def test_managed_instructions_injection_and_update(tmp_path: Path):
    """Test injecting and updating managed instructions while preserving user content."""
    original_agents = """# Project Guidelines
Custom rule 1: Do not touch production db.
Custom rule 2: Always use Python 3.11+.
"""
    # 1. First injection appends to bottom
    injected = inject_managed_instructions(original_agents)
    assert PLANNER_BLOCK_START in injected
    assert PLANNER_BLOCK_END in injected
    assert "Custom rule 1: Do not touch production db." in injected
    assert "Custom rule 2: Always use Python 3.11+." in injected

    # 2. Re-injecting with updated block updates in-place without duplicating
    updated_block = f"{PLANNER_BLOCK_START}\n## UPDATED PLANNER RULES\n- Rule A\n{PLANNER_BLOCK_END}"
    re_injected = inject_managed_instructions(injected, block=updated_block)
    assert re_injected.count(PLANNER_BLOCK_START) == 1
    assert re_injected.count(PLANNER_BLOCK_END) == 1
    assert "## UPDATED PLANNER RULES" in re_injected
    assert "Custom rule 1: Do not touch production db." in re_injected

    # 3. Removal removes the block and keeps original text
    cleaned = remove_managed_instructions(re_injected)
    assert PLANNER_BLOCK_START not in cleaned
    assert PLANNER_BLOCK_END not in cleaned
    assert "Custom rule 1: Do not touch production db." in cleaned


def test_probe_host_capabilities(tmp_path: Path):
    """Test capability probing across different directory setups."""
    # Setup repo root without instructions
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    # 1. Initial state: file management yes, instructions no, interception no -> unsupported
    report1 = probe_host_capabilities("gemini_antigravity", repo_root=repo_root)
    assert report1.host_name == "gemini_antigravity"
    assert report1.file_management is True
    assert report1.instructions_integrated is False
    assert report1.workflow_interception is False
    assert report1.support_level == "unsupported"

    # 2. Add AGENTS.md with managed block -> advisory
    agents_file = repo_root / "AGENTS.md"
    agents_file.write_text(inject_managed_instructions("# Agents"), encoding="utf-8")

    report2 = probe_host_capabilities("gemini_antigravity", repo_root=repo_root)
    assert report2.instructions_integrated is True
    assert report2.support_level == "advisory"

    # Files do not establish host invocation or effective enforcement.
    hooks_dir = repo_root / ".local-ai-hub" / "local" / "hooks"
    hooks_dir.mkdir(parents=True)
    (hooks_dir / "not_a_hook.txt").write_text("# hook", encoding="utf-8")

    report3 = probe_host_capabilities("gemini_antigravity", repo_root=repo_root)
    assert report3.workflow_interception is False
    assert report3.support_level == "advisory"


def test_instruction_probe_reads_bounded_files_and_gemini_instructions(tmp_path: Path):
    from local_ai_hub.repo_plan.host_adapters import probe_host_capabilities

    agents = tmp_path / "AGENTS.md"
    agents.write_text("x" * 70000 + f"{PLANNER_BLOCK_START}\n{PLANNER_BLOCK_END}")
    gemini = tmp_path / ".gemini/GEMINI.md"
    gemini.parent.mkdir()
    gemini.write_text(f"{PLANNER_BLOCK_START}\n{PLANNER_BLOCK_END}")
    report = probe_host_capabilities("gemini_cli", tmp_path)
    assert report.instructions_integrated
    agents.unlink()
    gemini.unlink()
    agents.write_text("x" * 70000 + f"{PLANNER_BLOCK_START}\n{PLANNER_BLOCK_END}")
    report = probe_host_capabilities("generic_mcp", tmp_path)
    assert not report.instructions_integrated


def test_superpowers_install_timeout_reports_partial_state(tmp_path: Path, monkeypatch):
    import subprocess
    import local_ai_hub.process_utils as process_utils
    from local_ai_hub.repo_plan.host_hooks import install_superpowers

    package = tmp_path / "extensions/superpowers"
    executable = tmp_path / "node.exe"
    executable.write_bytes(b"native executable placeholder")

    def timeout(argv, **kwargs):
        package.mkdir(parents=True)
        (package / "partial.txt").write_text("partial")
        raise subprocess.TimeoutExpired(argv, 60)

    monkeypatch.setattr(process_utils, "run_hidden", timeout)
    result = install_superpowers("gemini_cli", repo_root=tmp_path, package_root=package,
                                 executable=executable, operator_authorized=True, consent=True)
    assert result["outcome_unknown"]
    assert result["changed"] is None
    assert result["partial_install_review_required"]


def test_superpowers_nonzero_partial_install_not_reported_unchanged(tmp_path: Path, monkeypatch):
    import subprocess
    from types import SimpleNamespace
    import local_ai_hub.process_utils as process_utils
    from local_ai_hub.repo_plan.host_hooks import install_superpowers

    package = tmp_path / "extensions/superpowers"
    executable = tmp_path / "node.exe"
    executable.write_bytes(b"native executable placeholder")

    def failed(argv, **kwargs):
        package.mkdir(parents=True)
        (package / "partial.txt").write_text("partial")
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(process_utils, "run_hidden", failed)
    result = install_superpowers("gemini_cli", repo_root=tmp_path, package_root=package,
                                 executable=executable, operator_authorized=True, consent=True)
    assert not result["success"]
    assert result["changed"] is None
    assert result["partial_install_review_required"]


def test_steering_manager_lifecycle(tmp_path: Path):
    """Test capturing operator mid-execution steering, listing, and reconciliation."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    mgr = SteeringManager(repo_root)

    # 1. Capture steering for task_alpha
    res1 = mgr.capture_steering(
        session_id="session_101",
        message="Change output format from XML to JSON",
        task_id="task_alpha",
    )
    assert res1["success"] is True
    sid1 = res1["steering_id"]

    # 2. Capture general steering
    res2 = mgr.capture_steering(
        session_id="session_101",
        message="Add rate limiting to all endpoints",
    )
    assert res2["success"] is True
    sid2 = res2["steering_id"]

    # 3. List pending
    pending_all = mgr.list_pending_steering()
    assert len(pending_all) == 2

    pending_task = mgr.list_pending_steering(task_id="task_alpha")
    assert len(pending_task) == 1
    assert pending_task[0]["steering_id"] == sid1

    # 4. Mark reconciled
    reconciled = mgr.mark_reconciled(sid1, reconciliation_summary="Contract revised to require JSON format")
    assert reconciled is True

    # 5. Verify pending list reflects reconciliation
    pending_after = mgr.list_pending_steering()
    assert len(pending_after) == 1
    assert pending_after[0]["steering_id"] == sid2

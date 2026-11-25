"""CI event ownership: one PR cohort per commit, release verification preserved."""

from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"


def test_ci_runs_pr_updates_without_duplicate_feature_push_runs():
    text = WORKFLOW.read_text(encoding="utf-8")
    triggers = text.split("on:\n", 1)[1].split("\npermissions:", 1)[0]
    assert "push:\n    branches: [master]\n    tags: [\"v*\"]" in triggers
    assert "\n  pull_request:\n" in triggers
    assert "\n  workflow_dispatch:\n" in triggers


def test_ci_only_cancels_superseded_pr_runs():
    text = WORKFLOW.read_text(encoding="utf-8")
    policy = text.split("\nconcurrency:\n", 1)[1].split("\nenv:\n", 1)[0]
    assert "format('pr-{0}', github.event.pull_request.number)" in policy
    assert "github.event_name == 'pull_request'" in policy
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in policy


def test_ci_tag_releases_enable_full_platform_matrix():
    text = WORKFLOW.read_text(encoding="utf-8")
    # Both platform-smoke and integration must enable full suite on tag push (v*)
    for job_name in ("platform-smoke", "integration"):
        job_section = text.split(f"  {job_name}:\n", 1)[1].split("\n  steps:", 1)[0]
        assert "startsWith(github.ref, 'refs/tags/v')" in job_section
        assert "inputs.full_matrix" in job_section


def test_ci_coverage_export_uses_safe_diagnostics_wrapper():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "python -m coverage json" not in text
    assert text.count("python -m tools.ci_diagnostics --export-coverage") >= 2


def test_ci_integration_explicitly_notes_skipped_runs():
    text = WORKFLOW.read_text(encoding="utf-8")
    integration_job = text.split("  integration:\n", 1)[1].split("  critical-coverage:\n", 1)[0]
    assert "Note skipped integration run" in integration_job
    assert "::notice title=Integration suite skipped::" in integration_job


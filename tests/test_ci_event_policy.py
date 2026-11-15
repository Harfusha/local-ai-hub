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

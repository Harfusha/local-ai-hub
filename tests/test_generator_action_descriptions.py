from local_ai_hub.generator import (
    _repo_analysis_guidance,
    _repo_context_note,
    _repo_review_guidance,
    _supported_repo_action_names,
    generate_global_policy,
    generate_skill_references,
)
from local_ai_hub.features import FeatureSet


def test_repo_review_guidance_only_names_enabled_actions():
    guidance = _repo_review_guidance(["security_audit"])

    assert "security_audit" in guidance
    assert "review_diff" not in guidance


def test_repo_review_guidance_omits_disabled_review_actions():
    assert _repo_review_guidance([]) == ""


def test_generated_repo_guidance_lists_only_enabled_actions():
    actions = ["context", "impact", "security_audit"]

    analysis = _repo_analysis_guidance(actions)
    names = _supported_repo_action_names(actions, ("impact", "review_diff", "security_audit"))

    assert "context" in analysis
    assert "solve" not in analysis
    assert names == "impact, security_audit"


def test_generated_repo_guidance_omits_disabled_actions():
    assert _repo_analysis_guidance([]) == ""
    assert _supported_repo_action_names([], ("impact", "review_diff", "security_audit")) == ""
    assert "`context`" not in _repo_context_note([])


def test_generated_context_note_tracks_enabled_action():
    assert "adaptive `context`" in _repo_context_note(["context"])
    assert "adaptive `context`" not in _repo_context_note(["solve"])


def test_generated_skill_and_workflow_references_follow_repo_action_set(monkeypatch):
    monkeypatch.setattr(FeatureSet, "supported_repo_actions", lambda _self: ["security_audit"])
    references = generate_skill_references({
        "features": {
            "repo": True,
            "tasks": False,
            "coord": False,
            "artifacts": False,
            "status": False,
        },
        "preprocessing": {"enabled": False},
    })

    repo_tool = next(
        line for line in references["tools.md"].splitlines()
        if line.startswith("- `local_ai_repo`:")
    )
    assert "security_audit" in repo_tool
    assert "review_diff" not in repo_tool
    assert "impact" not in repo_tool
    assert "context" not in repo_tool
    assert "solve" not in repo_tool

    workflows = references["workflows.md"]
    assert "Review with `security_audit`" in workflows
    assert "`review_diff`" not in workflows
    assert "Use `context` for compact evidence." not in workflows
    assert "Call `solve` after evidence" not in workflows
    assert "use `impact` before risky dependent changes." not in workflows

    policy = generate_global_policy({
        "features": {
            "repo": True,
            "tasks": False,
            "coord": False,
            "artifacts": False,
            "status": False,
        },
        "preprocessing": {"enabled": False},
    })
    assert "adaptive `context` once with a stable root" not in policy
    assert "use available deterministic/indexed retrieval" in policy

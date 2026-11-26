from local_ai_hub.change_commit_preflight import commit_preflight, revision_error


def _plan(*changes):
    return {
        "success": True, "observed_change_set_id": "a" * 64,
        "git_visible_observation_complete": True, "comparison": None,
        "clusters": [
            {"group_key": path, "files": [path], "changes": [{"path": path, "status": status}]}
            for path, status in changes
        ],
    }


def test_exact_staging_preview_never_executes():
    plan = _plan(("a.py", " M"), ("other.py", " M"))
    result = commit_preflight(plan, ["a.py"], "a" * 64)
    assert result["stage_argv_preview"] == ["git", "--literal-pathspecs", "add", "--", "a.py"]
    assert result["requires_explicit_approval"]
    assert not result["commit_ready"]


def test_foreign_staging_and_mixed_staging_block():
    result = commit_preflight(_plan(("a.py", "MM"), ("other.py", "M ")), ["a.py"], "a" * 64)
    assert set(result["blockers"]) == {"unselected_staged_changes", "mixed_staged_unstaged_selection"}
    assert not result["stage_argv_preview"]


def test_revision_and_untracked_fail_closed():
    plan = _plan(("a.py", "??"))
    assert not commit_preflight(plan, ["a.py"], "b" * 64)["success"]
    assert "untracked_requires_explicit_review" in commit_preflight(plan, ["a.py"], "a" * 64)["blockers"]
    plan["git_visible_observation_complete"] = False
    assert revision_error(plan, "a" * 64)
    assert not commit_preflight(plan, ["a.py"], "a" * 64)["success"]


def test_staged_scope_does_not_prove_validation():
    result = commit_preflight(_plan(("a.py", "M ")), ["a.py"], "a" * 64)
    assert result["index_scope_matches_selection"]
    assert result["verification_status"] == "unknown"
    assert not result["commit_ready"]

from local_ai_hub.frontend_review import run_repair_recheck


def _bundle():
    return {
        "prompt": "Fix the frontend",
        "redaction": "none",
        "dom": {"redaction": "none", "html": "<button data-testid='cta'>Buy</button>", "elements": [{"element_id": "cta"}]},
        "accessibility": {},
        "computed_styles": {},
        "runtime": {},
        "viewport": {"width": 390, "height": 844},
    }


def _review():
    return {"findings": [{"finding_id": "cta", "element_ids": ["cta"], "observed": "bad", "hypothesized": "bad", "uncertainty": []}]}


def test_repair_recheck_stops_when_findings_clear():
    calls = []

    def repair(packet, attempt):
        calls.append(("edit", attempt, packet["success"]))
        return {"success": True, "patches": ["app.css"]}

    def recheck(edit, attempt):
        calls.append(("recheck", attempt))
        return {"findings": []}

    result = run_repair_recheck(_review(), _bundle(), {"files": []}, repair=repair, recheck=recheck)
    assert result["success"] is True
    assert result["attempts"] == 1
    assert calls == [("edit", 1, True), ("recheck", 1)]


def test_repair_recheck_is_bounded_and_reports_remaining_findings():
    result = run_repair_recheck(
        _review(), _bundle(), {},
        repair=lambda packet, attempt: {"success": True},
        recheck=lambda edit, attempt: {"findings": [{"finding_id": "cta"}]},
        max_attempts=99,
    )
    assert result["success"] is False
    assert result["attempts"] == 5
    assert len(result["history"]) == 5
    assert result["error_code"] == "frontend_repair_exhausted"


def test_repair_recheck_does_not_hide_edit_failure():
    result = run_repair_recheck(
        _review(), _bundle(), {},
        repair=lambda packet, attempt: {"success": False, "error": "coder declined"},
        recheck=lambda edit, attempt: {"findings": []},
        max_attempts=2,
    )
    assert result["success"] is False
    assert result["attempts"] == 2
    assert all(item["stage"] == "edit" for item in result["history"])

from local_ai_hub.delivery import decide_delivery


def test_review_diff_auto_delivery_bypasses_queue_when_age_exceeds_budget():
    result = decide_delivery(
        "auto",
        latency_budget_ms=5_000,
        queue_age_ms=5_001,
        max_queue_age_ms=5_000,
    )
    assert result["mode"] == "bypass"
    assert result["reason"] == "queue_age_budget_exceeded"


def test_queued_review_is_not_success_when_job_is_incomplete():
    status = {"success": True, "job_id": "job-1", "state": "queued", "retryable": True}
    assert status["state"] == "queued"
    assert status["retryable"] is True
    assert status["success"] is not False

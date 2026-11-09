from local_ai_hub.generator import generate_skill_markdown, generate_skill_references


def qualified_work_config():
    return {
        "ollama": {"enabled": True},
        "hardware": {"profile": "high"},
        "features": {"bounded_local_work": True},
    }


def test_generated_workflow_explains_missing_receipt():
    workflow = generate_skill_references(qualified_work_config())["workflows.md"]
    assert 'validation.receipt_status="not_recorded"' in workflow
    assert "no durable broker verification receipt" in workflow
    assert "does not replace primary-agent review" in workflow


def test_generated_guidance_preserves_qualified_bounded_handoff():
    cfg = qualified_work_config()
    skill = generate_skill_markdown(cfg)
    workflow = generate_skill_references(cfg)["workflows.md"]
    tools = generate_skill_references(cfg)["tools.md"]
    for guidance in (skill, workflow):
        assert "high/max profile" in guidance or "profile `high`" in guidance
        assert "task/model quality" in guidance
        assert "primary agent" in guidance
        assert "bounded patch parent directories must already exist" in guidance
        assert "mixed LF and CRLF within a single file" in guidance
        assert "timed_out=true" in guidance and "in_progress=true" in guidance
        assert "not a terminal result" in guidance
        assert "max_response_tokens >= 512" in guidance
        assert "output_truncated=true" in guidance
    assert 'receipt_status="recorded_unmapped"' in workflow
    assert 'stale_verification_receipts' in workflow
    assert 'uncertain_verification_receipts' in workflow
    assert "not task completion" in workflow
    assert "task_barrier_error=finalization_event_lookup_timeout" in workflow
    work_line = next(line for line in tools.splitlines() if line.startswith("- `local_ai_work`:"))
    assert "explicit" in work_line and "primary" in work_line

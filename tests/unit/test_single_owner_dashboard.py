from pathlib import Path


_DASHBOARD = Path(__file__).parents[2] / "src" / "local_ai_hub" / "dashboard.py"


def test_dashboard_has_no_tenant_controls_or_projection() -> None:
    source = _DASHBOARD.read_text(encoding="utf-8")

    assert "tenant" not in source.casefold()
    assert "Tenant" not in source


def test_dashboard_keeps_real_project_agent_and_session_context() -> None:
    source = _DASHBOARD.read_text(encoding="utf-8")

    assert "traceProjectLabel" in source
    assert "request.agent" in source
    assert "session_id" in source
    assert "workVisible" in source

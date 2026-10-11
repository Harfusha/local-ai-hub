from local_ai_hub.dashboard import DASHBOARD_HTML


def test_trace_and_workload_views_do_not_surface_tenant_identity() -> None:
    visible_tenant_labels = (
        "Agent/tenant",
        "Agent / tenant",
        "Actor / tenant",
        "Stream / Tenant:",
        "<div>Tenant</div>",
        "Tenant / Namespace",
    )

    assert not [label for label in visible_tenant_labels if label in DASHBOARD_HTML]

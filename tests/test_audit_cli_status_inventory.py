from tools.hubctl import status_inventory_lines


def test_cli_does_not_turn_missing_inventory_into_zero():
    models, agent = status_inventory_lines({})
    assert "unreported" in models.lower()
    assert "unreported" in agent.lower()
    assert "0 installed" not in models
    assert "0 tasks" not in agent


def test_cli_reports_explicit_empty_inventory_and_distinguishes_stale():
    models, agent = status_inventory_lines({"installed_models": [], "agent_state": {"tasks": [], "leases": []}})
    assert "0 installed" in models
    assert "0 reported tasks" in agent
    models, _ = status_inventory_lines({"installed_models": [], "snapshot_stale": True})
    assert "stale" in models.lower()
    assert "0 installed" not in models


def test_cli_rejects_malformed_or_explicitly_unavailable_models():
    for value in ({"installed_models": [7]}, {"installed_models": [], "installed_models_available": False}):
        models, _ = status_inventory_lines(value)
        assert "unreported" in models.lower()
        assert "0 installed" not in models

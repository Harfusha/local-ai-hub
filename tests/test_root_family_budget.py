from local_ai_hub.budget import RootFamilyBudget


def test_root_family_budget_rejects_new_work_with_actionable_reason():
    budget = RootFamilyBudget()
    budget.reserve("woodbound", input_tokens=100, limit=100)
    result = budget.reserve("woodbound", input_tokens=1, limit=100)
    assert result["status"] == "rejected"
    assert result["reason"] == "root_family_budget_exceeded"


def test_duplicate_scope_is_coalesced_and_fanout_is_bounded():
    budget = RootFamilyBudget(max_active_scopes=1)
    first = budget.reserve("family", input_tokens=1, scope="src/a.py")
    duplicate = budget.reserve("family", input_tokens=1, scope="src/a.py")
    second = budget.reserve("family", input_tokens=1, scope="src/b.py")
    assert first["status"] == "accepted"
    assert duplicate["status"] == "coalesced"
    assert second["status"] == "rejected"
    assert second["reason"] == "fanout_scope_limit_exceeded"

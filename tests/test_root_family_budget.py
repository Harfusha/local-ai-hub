from local_ai_hub.budget import RootFamilyBudget
from local_ai_hub import mcp_server


def test_root_family_budget_rejects_new_work_with_actionable_reason():
    budget = RootFamilyBudget()
    budget.reserve("woodbound", input_tokens=100, limit=100, owner="execution-a")
    result = budget.reserve("woodbound", input_tokens=1, limit=100, owner="execution-b")
    assert result["status"] == "rejected"
    assert result["reason"] == "root_family_budget_exceeded"


def test_duplicate_scope_is_coalesced_and_fanout_is_bounded():
    budget = RootFamilyBudget(max_active_scopes=1)
    first = budget.reserve("family", input_tokens=1, scope="src/a.py", owner="execution-a")
    duplicate = budget.reserve("family", input_tokens=1, scope="src/a.py", owner="execution-b")
    second = budget.reserve("family", input_tokens=1, scope="src/b.py", owner="execution-c")
    assert first["status"] == "accepted"
    assert duplicate["status"] == "coalesced"
    assert duplicate["reservation_id"] == first["reservation_id"]
    assert second["status"] == "rejected"
    assert second["reason"] == "fanout_scope_limit_exceeded"


def test_coalesced_caller_cannot_release_another_execution_reservation():
    budget = RootFamilyBudget()
    first = budget.reserve("family", input_tokens=7, scope="task/action", owner="execution-a")
    duplicate = budget.reserve("family", input_tokens=9, scope="task/action", owner="execution-b")

    refused = budget.release(duplicate["reservation_id"], owner="execution-b")
    assert refused["status"] == "owner_mismatch"
    assert budget.used_tokens("family") == 7

    released = budget.release(first["reservation_id"], owner="execution-a")
    assert released["status"] == "released"
    assert budget.used_tokens("family") == 0


def test_release_is_idempotent_and_unknown_ids_do_not_change_budget():
    budget = RootFamilyBudget()
    reservation = budget.reserve("family", input_tokens=7, owner="execution-a")

    assert budget.release("wrong-id", owner="execution-a")["status"] == "not_found"
    assert budget.used_tokens("family") == 7
    assert budget.release(reservation["reservation_id"], owner="wrong-owner")["status"] == "owner_mismatch"
    assert budget.used_tokens("family") == 7
    assert budget.release(reservation["reservation_id"], owner="execution-a")["status"] == "released"
    assert budget.release(reservation["reservation_id"], owner="execution-a")["status"] == "not_found"
    assert budget.used_tokens("family") == 0


def test_reservation_requires_explicit_owner():
    result = RootFamilyBudget().reserve("family", input_tokens=7)

    assert result["status"] == "rejected"
    assert result["reason"] == "reservation_owner_required"


def test_nested_mcp_wrapper_does_not_release_parent_context(monkeypatch):
    budget = RootFamilyBudget()
    parent = budget.reserve("family", input_tokens=5, owner="parent-execution")
    monkeypatch.setattr(mcp_server, "ROOT_FAMILY_BUDGET", budget)
    reservation = {"reservation_id": parent["reservation_id"], "owner": "parent-execution"}
    token = mcp_server._CURRENT_ROOT_FAMILY_RESERVATION.set(reservation)
    try:
        child = mcp_server._release_root_family_on_exit(lambda: "child-result")

        assert child() == "child-result"
        assert mcp_server._CURRENT_ROOT_FAMILY_RESERVATION.get() == reservation
        assert budget.used_tokens("family") == 5
    finally:
        mcp_server._release_root_family_reservation()
        mcp_server._CURRENT_ROOT_FAMILY_RESERVATION.reset(token)

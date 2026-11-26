from __future__ import annotations

from local_ai_hub.change_plan_projection import project_change_plan


def _result():
    return {"success": True, "cluster_count": 10, "clusters": [
        {"cluster_id": i, "name": f"group {i}", "summary": "changed",
         "suggested_commit_message": "chore: update component", "files": ["a.py"] * 10,
         "verification_status": "unknown"} for i in range(10)
    ], "unavailable_patch_scopes": [{"path": "a.py"}] * 12}


def test_bounded_projection_preserves_omission_counts():
    result = project_change_plan(_result(), limit=3, offset=3)
    assert [g["cluster_id"] for g in result["clusters"]] == [3, 4, 5]
    assert result["clusters"][0]["files_omitted"] == 4
    assert result["unavailable_patch_scopes_omitted"] == 4
    assert result["next_offset"] == 6
    assert result["has_more"] is True
    assert result["commit_ready"] is False


def test_model_advice_is_separate_and_invalid_output_fails_closed():
    def delegate(args):
        return {"success": True, "text": '{"messages":[{"id":0,"message":"chore: update payment"}]}'}
    result = project_change_plan(_result(), mode="semantic", limit=1, delegate=delegate)
    group = result["clusters"][0]
    assert group["model_commit_message"] == "chore: update payment"
    assert group["suggested_commit_message"] == "chore: update component"
    assert group["verification_status"] == "unknown"
    rejected = project_change_plan(_result(), mode="semantic", limit=2, delegate=delegate)
    assert rejected["model_advice_status"] == "invalid"
    assert "model_commit_message" not in rejected["clusters"][0]



def test_local_model_proposes_complete_nonoverlapping_partition():
    import json

    def delegate(args):
        return {"success": True, "text": json.dumps({
            "messages": [{"id": 0, "message": "chore: update payment"}, {"id": 1, "message": "test: update tests"}],
            "groups": [{"ids": [0, 1], "summary": "Payment and test updates", "message": "chore: update payment and tests"}],
        })}

    result = project_change_plan(_result(), mode="semantic", limit=2, delegate=delegate)
    assert result["model_advice_status"] == "available"
    assert result["semantic_group_proposals"][0]["cluster_ids"] == [0, 1]
    assert result["semantic_group_scope"] == "current_page_only"
    assert not result["semantic_group_proposals"][0]["commit_ready"]


def test_model_partition_rejects_missing_and_duplicate_ids():
    import json

    for ids in ([0], [0, 0], [0, 2]):
        def delegate(args):
            return {"success": True, "text": json.dumps({
                "messages": [{"id": 0, "message": "chore: update payment"}, {"id": 1, "message": "test: update tests"}],
                "groups": [{"ids": ids, "summary": "Payment updates", "message": "chore: update payment"}],
            })}
        result = project_change_plan(_result(), mode="semantic", limit=2, delegate=delegate)
        assert result["model_advice_status"] == "invalid"
        assert not result["semantic_group_proposals"]

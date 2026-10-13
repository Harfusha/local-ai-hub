from local_ai_hub.mcp_server import _compact

def test_negative_knowledge_find_preserves_incidents():
    raw_response = {
        "success": True,
        "matches": [
            {"incident_id": "inc-1", "error_class": "TimeoutError", "message": "Command timed out"}
        ],
        "count": 1
    }
    projected = _compact(raw_response, "task_memory")
    assert "matches" in projected or "incidents" in projected
    assert len(projected.get("matches", [])) == 1

def test_negative_knowledge_find_preserves_empty_matches():
    raw_response = {
        "success": True,
        "matches": [],
        "incidents": [],
        "negative_knowledge": [],
        "count": 0
    }
    projected = _compact(raw_response, "task_memory")
    assert "matches" in projected
    assert projected["matches"] == []
    assert "incidents" in projected
    assert projected["incidents"] == []

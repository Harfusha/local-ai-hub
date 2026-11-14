from local_ai_hub.breaking_change_detection import compare_api_definitions


def test_added_required_parameter_is_reported_as_breaking():
    old_defs = {
        "fetch_user_record": {
            "kind": "function",
            "required_count": 1,
            "pos_args": ["user_id"],
        }
    }
    new_defs = {
        "fetch_user_record": {
            "kind": "function",
            "required_count": 2,
            "pos_args": ["user_id", "include_deleted"],
        }
    }

    changes = compare_api_definitions("src/api.py", old_defs, new_defs)

    assert changes == [
        {
            "type": "signature_changed",
            "symbol": "fetch_user_record",
            "file": "src/api.py",
            "kind": "function",
            "description": "Signature of function 'fetch_user_record' added required parameter(s): include_deleted",
            "new_req": 2,
            "old_req": 1,
            "added_req": ["include_deleted"],
            "removed_args": [],
        }
    ]

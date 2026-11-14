from local_ai_hub.api_spec_document import build_api_spec_document


def test_build_api_spec_document_groups_methods_and_preserves_endpoints() -> None:
    endpoints = [
        {"method": "GET", "path": "/users", "handler": "list_users", "summary": "List users", "description": ""},
        {"method": "POST", "path": "/users", "handler": "create_user", "summary": "Create user", "description": ""},
    ]

    result = build_api_spec_document("sample", endpoints)

    assert result["success"] is True
    assert result["openapi"] == "3.0.0"
    assert result["info"] == {"title": "sample", "version": "1.0.0"}
    assert result["total_endpoints"] == 2
    assert result["endpoints"] is endpoints
    assert result["paths"]["/users"]["get"]["operationId"] == "list_users"
    assert result["paths"]["/users"]["post"]["summary"] == "Create user"
    assert result["paths"]["/users"]["get"]["responses"] == {"200": {"description": "Success"}}


def test_duplicate_path_and_method_keeps_last_projection_but_counts_each_endpoint() -> None:
    endpoints = [
        {"method": "GET", "path": "/users", "handler": "old", "summary": "Old"},
        {"method": "get", "path": "/users", "handler": "new", "summary": "New"},
    ]

    result = build_api_spec_document("sample", endpoints)

    assert result["total_endpoints"] == 2
    assert result["paths"]["/users"]["get"]["operationId"] == "new"
    assert result["paths"]["/users"]["get"]["summary"] == "New"

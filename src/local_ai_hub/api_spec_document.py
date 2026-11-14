"""Pure response construction for deterministic API specification extraction."""

from __future__ import annotations

from typing import Any


def build_api_spec_document(project_name: str, endpoints: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the OpenAPI-shaped response while preserving endpoint order and counts."""
    openapi_paths: dict[str, Any] = {}
    for endpoint in endpoints:
        path = endpoint["path"]
        method = endpoint["method"].lower()
        if path not in openapi_paths:
            openapi_paths[path] = {}
        openapi_paths[path][method] = {
            "summary": endpoint.get("summary", ""),
            "description": endpoint.get("description", ""),
            "operationId": endpoint.get("handler", ""),
            "responses": {"200": {"description": "Success"}},
        }

    return {
        "success": True,
        "openapi": "3.0.0",
        "info": {"title": project_name, "version": "1.0.0"},
        "total_endpoints": len(endpoints),
        "paths": openapi_paths,
        "endpoints": endpoints,
    }

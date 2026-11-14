from __future__ import annotations

import ast
import json
from pathlib import Path

from local_ai_hub.http_route_registry import POST_ROUTE_REGISTRY, select_http_routes
from local_ai_hub.operation_contracts import OPERATION_CONTRACTS, operation_metadata
from tools.surface_inventory import _path_condition_match


ROOT = Path(__file__).resolve().parents[1]


def _coverage_rows() -> list[dict]:
    payload = json.loads((ROOT / "docs/API_COVERAGE.json").read_text(encoding="utf-8"))
    return payload["coverage_rows"]


def test_generated_catalog_matches_all_public_mcp_tools_and_action_contracts():
    rows = _coverage_rows()
    tools = {
        row["name"]
        for row in rows
        if row.get("surface") == "MCP tool"
    }
    action_rows = {
        (row["surface"].removeprefix("MCP action "), row["name"]): row
        for row in rows
        if row.get("surface", "").startswith("MCP action ")
        and row["surface"].removeprefix("MCP action ") in OPERATION_CONTRACTS
    }

    assert len(OPERATION_CONTRACTS) == 7
    assert tools == set(OPERATION_CONTRACTS)
    source_actions = {
        (tool, action)
        for tool in OPERATION_CONTRACTS
        for action in operation_metadata(tool)["actions"]
    }
    assert set(action_rows) <= source_actions

    schema_gaps = [
        row
        for row in rows
        if row.get("surface", "").startswith("MCP action schema gap ")
    ]
    assert schema_gaps
    assert all("absent from the generated action enum" in row["condition"] for row in schema_gaps)

    for tool, action in action_rows:
        row = action_rows[(tool, action)]
        catalog_contract = row["contract"]
        source_contract = operation_metadata(tool)["actions"][action]
        assert catalog_contract["required_fields"] == list(source_contract["required"])
        assert catalog_contract["operation_side_effects"] == source_contract["side_effects"]
        assert catalog_contract["idempotent"] is source_contract["idempotent"]
        assert catalog_contract["retry_safe"] is source_contract["retry_safe"]
        assert catalog_contract["automatic_replay"] is source_contract["automatic_replay"]
        assert isinstance(catalog_contract["request_payload"], (dict, str))
        assert isinstance(catalog_contract["response_contract"], (dict, str))
        assert row["state"]
        assert row["access_classification"]
        assert row["scope_boundary"]


def test_generated_catalog_covers_canonical_http_post_routes_and_auth_fields():
    rows = _coverage_rows()
    route_rows = [row for row in rows if row.get("surface") == "HTTP POST"]
    catalog_paths = {row["name"] for row in route_rows}
    registered_paths = {
        path
        for rule in POST_ROUTE_REGISTRY
        for path in rule.paths
    }

    assert registered_paths <= catalog_paths
    for row in route_rows:
        contract = row["contract"]
        assert contract["method"] == "POST"
        assert "auth_identity" in contract
        assert contract["auth_identity"] == (
            "local loopback client; _authorized actor is local; no per-user principal or bearer token"
        )
        assert "canonical method/path selection precedes body parsing" in contract["route_invariants"]
        assert "direct route dispatch is listed in route_state_boundary" in contract["state_boundary"]
        assert "src/local_ai_hub/http_server.py:2782" in row["evidence"]
        assert "src/local_ai_hub/http_server.py:3005" in row["evidence"]
        assert "src/local_ai_hub/http_server.py:5816" in row["evidence"]
        binding = contract["dispatch_scope_binding"]
        assert binding["status"] in {"observed", "not_observed"}
        assert bool(binding["guards"]) is (binding["status"] == "observed")
        authorization = contract["authorization_boundary"]
        assert authorization["status"] == "shared_gate_observed"
        assert authorization["route_scope_guards"] == binding["guards"]
        assert authorization["behavior_test_id"] == (
            "tests/unit/test_canonical_http_routes.py::"
            "test_every_registered_post_route_authorizes_before_body_or_dispatch"
        )
        assert any("loopback" in check for check in authorization["checks"])
        assert any("Host and Origin" in check for check in authorization["checks"])
        state_boundary = contract["route_state_boundary"]
        assert "unverified" in state_boundary["transitive_state_effects"]
        assert state_boundary["direct_dispatch_status"] == contract["route_dispatch"]["status"]
        if binding["guards"]:
            assert all(guard in row["scope_boundary"] for guard in binding["guards"])
        else:
            assert "remains unverified" in row["scope_boundary"]
        if binding["status"] == "observed":
            assert any(source.startswith("src/local_ai_hub/http_server.py:") for source in row["evidence"])
        assert "required_fields" in contract
        assert "side_effects" in contract
        assert "response_contract" in contract
        assert row["state"]
        assert row["access_classification"]
        assert row["scope_boundary"]


def test_registered_post_paths_select_their_route_ids():
    for rule in POST_ROUTE_REGISTRY:
        for path in rule.paths:
            assert rule.route_id in select_http_routes("POST", path)
            assert select_http_routes("GET", path) == ()


def test_http_post_scope_binding_stays_specific_and_fail_closed():
    rows = {row["name"]: row for row in _coverage_rows() if row.get("surface") == "HTTP POST"}

    rename = rows["/api/ast_rename"]
    assert "_bind_repository_root_payload" in rename["contract"]["dispatch_scope_binding"]["guards"]
    assert "_bind_repository_root_payload" in rename["scope_boundary"]
    assert "_bind_task_payload" in rows["/api/agent-state/tasks"]["contract"]["dispatch_scope_binding"]["guards"]
    assert rows["/api/admin/mode"]["contract"]["dispatch_scope_binding"] == {
        "status": "not_observed",
        "guards": [],
    }


def test_http_post_route_dispatch_uses_route_ids_and_named_boundaries():
    rows = {row["name"]: row for row in _coverage_rows() if row.get("surface") == "HTTP POST"}

    coord_dispatch = rows["/api/coord/board_item_create"]["contract"]["route_dispatch"]
    assert "APP.services.board_item_create" in coord_dispatch["targets"]
    assert "src/local_ai_hub/http_server.py:" in " ".join(rows["/api/coord/board_item_create"]["evidence"])

    git_dispatch = rows["/api/git/status"]["contract"]["route_dispatch"]
    assert "_handle_post_repository_analysis" in git_dispatch["handler_boundaries"]

    artifact_dispatch = rows["/api/artifact/get"]["contract"]["route_dispatch"]
    assert "_handle_post_artifact_get" in artifact_dispatch["handler_boundaries"]

    telemetry_dispatch = rows["/api/telemetry/tool-accounting"]["contract"]["route_dispatch"]
    assert "APP.telemetry.record_tool_accounting" in telemetry_dispatch["targets"]


def test_scope_path_matcher_ignores_negated_path_guards():
    assert not _path_condition_match(
        ast.parse('not path.startswith("/api/repo/")', mode="eval").body,
        "/api/repo/search",
    )[0]
    assert not _path_condition_match(
        ast.parse('path != "/api/repo/search"', mode="eval").body,
        "/api/repo/search",
    )[0]


def test_registry_document_points_to_the_executable_contract_sources():
    doc = (ROOT / "docs/API_REGISTRY.md").read_text(encoding="utf-8")

    for required_reference in (
        "src/local_ai_hub/operation_contracts.py",
        "src/local_ai_hub/http_route_registry.py",
        "docs/API_COVERAGE.json",
        "tests/test_operation_contracts.py",
        "tests/test_http_route_operation_acceptance.py",
        "tests/unit/test_canonical_http_routes.py",
    ):
        assert required_reference in doc

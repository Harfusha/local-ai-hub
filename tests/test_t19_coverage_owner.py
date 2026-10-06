import ast
from pathlib import Path

from tools.surface_inventory import _extract_registered_http, _findings, collect_inventory, coverage_rows

ROOT = Path(__file__).resolve().parents[1]


def test_generation_task_does_not_override_explicit_owner_task() -> None:
    finding = {
        "surface": "HTTP GET",
        "name": "/api/context/pack",
        "owner": "tools/surface_inventory.py",
        "owner_task": "T01",
        "evidence": ["tools/surface_inventory.py:29"],
    }

    row = coverage_rows([finding], task_id="T19")[0]

    assert row["owner_task"] == "T01"
    assert row["task_id"] == "T19"


def test_context_pack_post_remains_assigned_to_t14_in_generated_coverage() -> None:
    inventory = collect_inventory(Path(__file__).resolve().parents[1])
    finding = next(
        item
        for item in _findings(inventory)
        if item["surface"] == "HTTP POST" and item["name"] == "/api/context/pack"
    )

    row = coverage_rows([finding], task_id="T19")[0]

    assert row["owner_task"] == "T14"
    assert row["task_id"] == "T19"


def test_post_route_rule_registry_is_included_in_inventory() -> None:
    registry_path = ROOT / "src" / "local_ai_hub" / "http_route_registry.py"
    tree = ast.parse(registry_path.read_text(encoding="utf-8"))

    routes = _extract_registered_http(tree, "src/local_ai_hub/http_route_registry.py")

    assert ("POST", "/api/repo/callers") in {
        (route["method"], route["path"]) for route in routes
    }

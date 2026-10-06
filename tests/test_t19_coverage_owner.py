from pathlib import Path

from tools.surface_inventory import _findings, collect_inventory, coverage_rows


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


def test_context_pack_get_remains_assigned_to_t01_in_generated_coverage() -> None:
    inventory = collect_inventory(Path(__file__).resolve().parents[1])
    finding = next(
        item
        for item in _findings(inventory)
        if item["surface"] == "HTTP GET" and item["name"] == "/api/context/pack"
    )

    row = coverage_rows([finding], task_id="T19")[0]

    assert row["owner_task"] == "T01"
    assert row["task_id"] == "T19"

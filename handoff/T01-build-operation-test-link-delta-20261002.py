#!/usr/bin/env python3
"""Build a conservative T01 worktree delta from asserted operation test links."""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.surface_inventory import collect_inventory, coverage_rows, _findings  # noqa: E402

BASE_MAP = ROOT / "handoff" / "T01-operation-evidence-review-20261001-v2.csv"
EXPECTED_BASE_SHA256 = "F71D4BCD89B37877D16C6D5FCEF25F140A79CB9A9ABE0900684FE2EA0C3E0A37"
EXPECTED_INVENTORY_SHA256 = "375A804B517C36A24C83BD331FAD29351E7E75D9E2AC8422389D5C43749E683D"
TARGETED_TEST_FILES = {
    "tests/test_client_operation_acceptance.py",
    "tests/test_http_route_operation_acceptance.py",
    "tests/test_hubctl_unlinked_operations.py",
    "tests/test_mcp_command_operation_acceptance.py",
    "tests/test_mcp_coord_operation_acceptance.py",
    "tests/test_rag_work_operation_acceptance.py",
}
NEW_OWNER_RECEIPTS = [
    {
        "task_id": "T04",
        "receipt_path": "C:/Users/Adam/.codex/worktrees/t04-integration/.local-ai-hub/artifacts/t04-end-to-end-acceptance-closeout-2026-10-01-v2.md",
        "receipt_sha256": "0646A75C775ADD0E81F58E25B54935DFF2E5339D91B74065EA3B247AB0008F4E",
        "checkpoint_path": "C:/Users/Adam/.codex/worktrees/t04-integration/.local-ai-hub/artifacts/t04-resume-checkpoint-2026-10-02-v1.md",
        "checkpoint_sha256": "EFBD36B7DF6E38E33A37AB005AB094274A181F4F628E44098CA6C70D4F5A7029",
        "evidence": "root-current suite 120 passed in 63.70s at HEAD 01df56605ccf484ebfe2808ac60d696c4e81dffc; receipt pins client, HTTP, MCP, conversations, agent_tasks and selected test files",
        "mapping_status": "aggregate receipt has no exact per-operation selectors; do not close T04 rows",
        "row_updates": 0,
    },
    {
        "task_id": "T03",
        "receipt_path": "C:/Users/Adam/.codex/worktrees/t03-contracts-resume/.local-ai-hub/handoff/T03-root-current-full-status-output-20261001.receipt.md",
        "receipt_sha256": "8CED158874401F776E1ADDBEB0886FACE3580B763A6DCA4C2E30E9A94ED01A43",
        "patch_path": "C:/Users/Adam/.codex/worktrees/t03-contracts-resume/.local-ai-hub/handoff/T03-root-current-full-status-output-20261001.patch",
        "patch_sha256": "A5CA8543CA462B67D12C75343A794E23B1B225ADC796B2C44965125C572F04E6",
        "evidence": "candidate suite 97 passed in 28.07s; not rerun; root HEAD 01df56605ccf484ebfe2808ac60d696c4e81dffc still matches patch preimages; root integration pending",
        "mapping_status": "candidate-only until root integration and exact selectors are reverified; do not close T03 rows",
        "row_updates": 0,
    },
    {
        "task_id": "T17",
        "receipt_path": "C:/Users/Adam/.codex/worktrees/t17-multimodal-resume/.local-ai-hub/handoff/t17-browser-vision-ownership-review.md",
        "receipt_sha256": "6AF94C2B44A0B6D5D36E92B468CEE5271132466C100E93BF2FDBB76E8EF3CDAE",
        "patch_path": "C:/Users/Adam/.codex/worktrees/t17-multimodal-resume/.local-ai-hub/handoff/t17-transcribe-route-fixture-root-current-v1.patch",
        "patch_sha256": "431656D385BE76E22E523DA37126ED1DF23A1C8366474F4EB5713BAFE9A08966",
        "operation_id": "op-65970ac00a0a",
        "mapped_operation_owner_task": "T13",
        "selector": "tests/test_transcription_contract.py::test_http_transcribe_route_preserves_requested_model",
        "evidence": "candidate selector 1 passed in 4.54s; temporary root-source overlay selector 1 passed in 4.12s after applying this one-line fixture-only patch",
        "mapping_status": "exact HTTP POST /api/task/transcribe row op-65970ac00a0a; primary operation owner remains T13; candidate/overlay evidence only until T20 integrates patch and runs selector in integrated root",
        "root_preimage_sha256": "568616AC241D6B9E1C4F797542A9FFEF63384CB3FB6C56B9A27A3DEADC71E492",
        "overlay_postimage_sha256": "A0E5B29F3A5DAD83EE2FD9E89EAF43B8C90F3A859DA0DD80B380E9D42648FA48",
        "row_updates": 1,
        "root_green": False,
    },
]

OWNER_ROW_EVIDENCE = {
    "op-65970ac00a0a": {
        "selector": "tests/test_transcription_contract.py::test_http_transcribe_route_preserves_requested_model",
        "status": "T17 candidate selector and temporary root-source overlay passed; integrated root run pending",
        "receipt_ref": "handoff/t17-browser-vision-ownership-review.md",
        "receipt_sha256": "6AF94C2B44A0B6D5D36E92B468CEE5271132466C100E93BF2FDBB76E8EF3CDAE",
        "patch_sha256": "431656D385BE76E22E523DA37126ED1DF23A1C8366474F4EB5713BAFE9A08966",
        "receipt_owner_task": "T17",
        "primary_operation_owner_task": "T13",
        "root_green": "false",
    },
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main() -> int:
    inventory_path = ROOT / "tools" / "surface_inventory.py"
    base_sha = sha256(BASE_MAP)
    inventory_sha = sha256(inventory_path)
    if base_sha != EXPECTED_BASE_SHA256 or inventory_sha != EXPECTED_INVENTORY_SHA256:
        raise SystemExit("pinned input changed; review and update pins explicitly")

    with BASE_MAP.open(encoding="utf-8-sig", newline="") as stream:
        base_rows = list(csv.DictReader(stream))
    if len({row["operation_id"] for row in base_rows}) != len(base_rows):
        raise SystemExit("duplicate operation_id in base map")

    inventory = collect_inventory(ROOT)
    links = inventory["behavioral_test_links"]
    current_inventory_rows = coverage_rows(_findings(inventory))
    candidates: list[dict[str, str]] = []
    for row in base_rows:
        key = f'{row["surface"]}::{row["name"]}'
        selectors = sorted(links.get(key, []))
        targeted_selectors = [
            selector
            for selector in selectors
            if selector.split("::", 1)[0] in TARGETED_TEST_FILES
        ]
        candidate = {
            "operation_id": row["operation_id"],
            "surface": row["surface"],
            "name": row["name"],
            "primary_owner_task": row["primary_owner_task"],
            "baseline_behavioral_disposition": row["behavioral_disposition"],
            "candidate_test_selectors": json.dumps(selectors, ensure_ascii=False),
            "candidate_targeted_selectors": json.dumps(targeted_selectors, ensure_ascii=False),
            "candidate_disposition": (
                "exact selector linked in targeted T01 file; execution receipt is separate"
                if targeted_selectors
                else "asserted selector linked; execution receipt is separate"
                if selectors
                else "no asserted operation test linked; behavior unverified"
            ),
            "root_green": "false",
            "owner_receipt_selector": "",
            "owner_receipt_status": "",
            "owner_receipt_ref": "",
            "owner_receipt_sha256": "",
            "owner_receipt_patch_sha256": "",
            "owner_receipt_task": "",
        }
        if row["operation_id"] in OWNER_ROW_EVIDENCE:
            owner_evidence = OWNER_ROW_EVIDENCE[row["operation_id"]]
            candidate.update({
                "candidate_disposition": owner_evidence["status"],
                "owner_receipt_selector": owner_evidence["selector"],
                "owner_receipt_status": owner_evidence["status"],
                "owner_receipt_ref": owner_evidence["receipt_ref"],
                "owner_receipt_sha256": owner_evidence["receipt_sha256"],
                "owner_receipt_patch_sha256": owner_evidence["patch_sha256"],
                "owner_receipt_task": owner_evidence["receipt_owner_task"],
            })
        candidates.append(candidate)

    # Keep the historical gap map separate from current inventory evidence:
    # new operations may have exact focused tests without appearing in the
    # older 446-row gap snapshot. Never infer coverage from a neighboring route,
    # alias, or a test module name alone.
    current_operation_evidence: list[dict[str, str]] = []
    for row in current_inventory_rows:
        key = f'{row["surface"]}::{row["name"]}'
        if row["surface"] == "HubClient target":
            key += f'::{row.get("handler", "")}'
        selectors = sorted(links.get(key, []))
        candidate_selectors = [
            selector
            for selector in selectors
            if selector.split("::", 1)[0] in TARGETED_TEST_FILES
        ]
        current_operation_evidence.append({
            "operation_id": row["operation_id"],
            "surface": row["surface"],
            "name": row["name"],
            "handler": row.get("handler", ""),
            "owner_task": row["owner_task"],
            "contract_metadata_node_id": (
                "tests/test_surface_inventory.py::test_operation_contract_metadata["
                f'{row["operation_id"]}]'
            ),
            "contract_node_basis": "pytest parametrize ids=lambda row: row['operation_id']; metadata-only contract assertion",
            "exact_test_selectors": json.dumps(selectors, ensure_ascii=False),
            "candidate_test_selectors": json.dumps(candidate_selectors, ensure_ascii=False),
            "candidate_selector_status": "focused selector" if candidate_selectors else "no focused selector",
            "behavioral_disposition": row["behavioral_disposition"],
            "root_green": "false",
        })
    current_by_id = {row["operation_id"]: row for row in current_operation_evidence}
    for candidate in candidates:
        current = current_by_id.get(candidate["operation_id"])
        candidate["current_inventory_match"] = "present" if current else "absent"
        candidate["contract_metadata_node_id"] = (
            current["contract_metadata_node_id"] if current else ""
        )
        candidate["exact_current_test_selectors"] = (
            current["exact_test_selectors"] if current else "[]"
        )
        exact_current = json.loads(candidate["exact_current_test_selectors"])
        if exact_current:
            candidate["candidate_test_selectors"] = json.dumps(
                sorted(set(json.loads(candidate["candidate_test_selectors"])) | set(exact_current)),
                ensure_ascii=False,
            )
            candidate["candidate_targeted_selectors"] = json.dumps(sorted({
                *json.loads(candidate["candidate_targeted_selectors"]),
                *(selector for selector in exact_current if selector.split("::", 1)[0] in TARGETED_TEST_FILES),
            }), ensure_ascii=False)

    unmapped_operations = []
    for candidate in candidates:
        behavioral_selectors = json.loads(candidate["candidate_test_selectors"])
        if not behavioral_selectors and not candidate["owner_receipt_selector"]:
            unmapped_operations.append({
                "operation_id": candidate["operation_id"],
                "surface": candidate["surface"],
                "name": candidate["name"],
                "owner_task": candidate["primary_owner_task"],
                "dedupe_key": candidate["operation_id"],
                "current_inventory_match": candidate["current_inventory_match"],
                "contract_metadata_node_id": candidate["contract_metadata_node_id"],
                "behavioral_test_selectors": "[]",
                "status": "behavior selector unmapped; contract metadata node is not behavioral proof",
            })

    linked_rows = [
        row for row in candidates
        if json.loads(row["candidate_test_selectors"]) or row["owner_receipt_selector"]
    ]
    static_linked_rows = [row for row in candidates if json.loads(row["candidate_test_selectors"])]
    focused_rows = [row for row in candidates if json.loads(row["candidate_targeted_selectors"])]
    unlinked_rows = [
        row for row in candidates
        if row["candidate_disposition"] == "no asserted operation test linked; behavior unverified"
    ]
    selectors = {
        selector
        for row in candidates
        for selector in json.loads(row["candidate_test_selectors"])
    }
    targeted_selectors = {
        selector
        for row in candidates
        for selector in json.loads(row["candidate_targeted_selectors"])
    }
    summary = {
        "schema_version": 1,
        "worktree": str(ROOT),
        "head": "689165fbe18101feacf5f489847a4890fc27ed1f",
        "base_map": {"path": BASE_MAP.relative_to(ROOT).as_posix(), "sha256": base_sha},
        "matcher": {"path": inventory_path.relative_to(ROOT).as_posix(), "sha256": inventory_sha},
        "targeted_test_files": sorted(TARGETED_TEST_FILES),
        "operation_rows": len(candidates),
        "candidate_linked_rows": len(linked_rows),
        "static_candidate_linked_rows": len(static_linked_rows),
        "owner_receipt_selector_rows": sum(bool(row["owner_receipt_selector"]) for row in candidates),
        "candidate_rows_with_targeted_selectors": len(focused_rows),
        "unique_linked_selectors": len(selectors),
        "unique_selectors_in_targeted_files": len(targeted_selectors),
        "candidate_unlinked_rows": len(candidates) - len(linked_rows),
        "unlinked_by_owner": dict(sorted(Counter(row["primary_owner_task"] for row in unlinked_rows).items())),
        "t01_unlinked_rows": sum(row["primary_owner_task"] == "T01" for row in unlinked_rows),
        "unlinked_rows_owned_by_other_tasks": sum(row["primary_owner_task"] != "T01" for row in unlinked_rows),
        "root_green_rows": 0,
        "root_open_by_owner": dict(sorted(Counter(row["primary_owner_task"] for row in candidates).items())),
        "rows_without_exact_selector_mapping": len(unlinked_rows),
        "candidate_only_operation_ids": sorted(
            row["operation_id"] for row in candidates
            if (json.loads(row["candidate_test_selectors"]) or row["owner_receipt_selector"])
        ),
        "root_open_operation_ids": [row["operation_id"] for row in candidates],
        "candidate_disposition_counts": dict(Counter(row["candidate_disposition"] for row in candidates)),
        "execution_receipt": "handoff/T01-operation-acceptance-run-20261002.md",
    }
    for receipt in NEW_OWNER_RECEIPTS:
        receipt["mapped_operation_ids"] = [receipt["operation_id"]] if receipt.get("operation_id") else []
        receipt["unlinked_operation_ids"] = [
            row["operation_id"]
            for row in unlinked_rows
            if row["primary_owner_task"] == receipt["task_id"]
        ]
        receipt["unlinked_row_count"] = len(receipt["unlinked_operation_ids"])
    summary["new_owner_receipts_reviewed"] = NEW_OWNER_RECEIPTS
    summary["newly_closed_operation_ids"] = []
    summary["remaining_open_operation_ids"] = [row["operation_id"] for row in candidates]
    csv_path = ROOT / "handoff" / "T01-operation-test-link-delta-20261002.csv"
    json_path = ROOT / "handoff" / "T01-operation-test-link-delta-20261002.json"
    selector_csv_path = ROOT / "handoff" / "T01-current-operation-selector-evidence-20261002.csv"
    selector_json_path = ROOT / "handoff" / "T01-current-operation-selector-evidence-20261002.json"
    fields = list(dict.fromkeys(key for row in candidates for key in row))
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(candidates)
    json_path.write_text(
        json.dumps({"summary": summary, "operations": candidates}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    selector_summary = {
        "schema_version": 1,
        "worktree": str(ROOT),
        "matcher_sha256": inventory_sha,
        "current_inventory_operation_rows": len(current_operation_evidence),
        "operations_with_exact_test_selectors": sum(
            row["exact_test_selectors"] != "[]" for row in current_operation_evidence
        ),
        "operations_with_focused_candidate_selectors": sum(
            row["candidate_test_selectors"] != "[]" for row in current_operation_evidence
        ),
        "unique_focused_candidate_selectors": len({
            selector
            for row in current_operation_evidence
            for selector in json.loads(row["candidate_test_selectors"])
        }),
        "historical_gap_rows_with_current_contract_node": sum(
            bool(row["contract_metadata_node_id"]) for row in candidates
        ),
        "historical_gap_rows_without_current_contract_node": sum(
            not row["contract_metadata_node_id"] for row in candidates
        ),
        "historical_gap_rows_without_behavioral_selector": len(unmapped_operations),
        "dedupe_key": "operation_id",
        "root_green_rows": 0,
        "scope_note": "Static asserted-call links only; focused selector execution and root integration are separate receipts.",
    }
    selector_fields = list(dict.fromkeys(key for row in current_operation_evidence for key in row))
    with selector_csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=selector_fields)
        writer.writeheader()
        writer.writerows(current_operation_evidence)
    selector_json_path.write_text(
        json.dumps({"summary": selector_summary, "operations": current_operation_evidence}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    gap_node_csv_path = ROOT / "handoff" / "T01-gap-operation-node-map-20261002.csv"
    gap_node_json_path = ROOT / "handoff" / "T01-gap-operation-node-map-20261002.json"
    gap_node_fields = list(dict.fromkeys(key for row in candidates for key in row))
    with gap_node_csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=gap_node_fields)
        writer.writeheader()
        writer.writerows(candidates)
    gap_node_json_path.write_text(
        json.dumps({"summary": selector_summary, "operations": candidates}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    unmapped_csv_path = ROOT / "handoff" / "T01-unmapped-operation-dedupe-20261002.csv"
    unmapped_json_path = ROOT / "handoff" / "T01-unmapped-operation-dedupe-20261002.json"
    with unmapped_csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(unmapped_operations[0]) if unmapped_operations else [])
        writer.writeheader()
        writer.writerows(unmapped_operations)
    unmapped_summary = {
        "schema_version": 1,
        "dedupe_key": "operation_id",
        "historical_gap_rows": len(candidates),
        "unique_unmapped_behavior_operations": len(unmapped_operations),
        "duplicate_operation_ids_removed": 0,
        "behavioral_selector_unmapped_operation_ids": [row["operation_id"] for row in unmapped_operations],
        "root_green_rows": 0,
        "note": "Contract metadata node IDs are listed separately and do not count as behavioral selectors.",
    }
    unmapped_json_path.write_text(
        json.dumps({"summary": unmapped_summary, "operations": unmapped_operations}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        **summary,
        "csv_sha256": sha256(csv_path),
        "json_sha256": sha256(json_path),
        "selector_evidence_csv_sha256": sha256(selector_csv_path),
        "selector_evidence_json_sha256": sha256(selector_json_path),
        "selector_evidence_summary": selector_summary,
        "gap_operation_node_map_csv_sha256": sha256(gap_node_csv_path),
        "gap_operation_node_map_json_sha256": sha256(gap_node_json_path),
        "unmapped_operation_dedupe_csv_sha256": sha256(unmapped_csv_path),
        "unmapped_operation_dedupe_json_sha256": sha256(unmapped_json_path),
        "unmapped_operation_dedupe_summary": unmapped_summary,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

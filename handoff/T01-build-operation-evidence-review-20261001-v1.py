"""Reconcile T01 behavior gaps with the latest owner-coverage delta."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GAP_CSV = ROOT / "handoff/T01-unlinked-MCP-HTTP-owner-gaps-20261001-v2.csv"
GAP_JSON = ROOT / "handoff/T01-unlinked-MCP-HTTP-owner-gaps-20261001-v2.json"
DELTA_CSV = ROOT / "handoff/T01-root-current-owner-coverage-delta-20261001-v3.csv"
TRIAGE_CSV = ROOT / "handoff/T01-unverified-high-impact-owner-triage-root-snapshot-20261001.csv"
T01_RECEIPT = ROOT / "handoff/T01-operation-level-receipt-task-rollback-20261001.md"
T01_TEST_SOURCE = ROOT / "tests/test_mcp_coord_operation_acceptance.py"
OUT_CSV = ROOT / "handoff/T01-operation-evidence-review-20261001-v1.csv"
OUT_JSON = ROOT / "handoff/T01-operation-evidence-review-20261001-v1.json"

REVIEW = {
    "op-65970ac00a0a": (
        "partial_http_route_assertion",
        "Loopback POST asserts forwarded model, language, audio_path, tenant; service is mocked. No real transcription/backend quality proof.",
    ),
    "op-6bfb2c2726e6": (
        "negative_conditional_gate_only",
        "Selector calls agent_state with FEATURES.agent_os=False and asserts HTTP 400 invalid action. Does not prove enabled-mode agent_state behavior.",
    ),
    "op-901c14322762": (
        "partial_mcp_dispatch_assertion",
        "Selector calls local_ai_artifact(list), asserts success and POST /api/artifact/list dispatch. Backend response is mocked; no route/service behavior proof.",
    ),
    "op-fef1ba551941": (
        "partial_mcp_health_assertion",
        "Selector calls local_ai_status(health), asserts client lookup and success in operational modes. Client response is mocked; no live health proof.",
    ),
}
RECEIPTS = {
    "op-65970ac00a0a": {
        "status": "owner_lookup_pending",
        "source_sha256": "568616AC241D6B9E1C4F797542A9FFEF63384CB3FB6C56B9A27A3DEADC71E492",
        "receipt_path": "",
        "receipt_sha256": "",
        "result": "",
        "command": "",
        "source_pin_status": "owner_lookup_pending",
    },
    "op-6bfb2c2726e6": {
        "status": "no_execution_receipt_found",
        "source_sha256": "B0D2CCE62F5F3FB0BABB145A8933E8254236D3D61DB31ABE57008FBFCEA28AAF",
        "receipt_path": "",
        "receipt_sha256": "",
        "result": "",
        "command": "",
        "source_pin_status": "not_applicable_no_run_receipt",
    },
    "op-901c14322762": {
        "status": "no_execution_receipt_found",
        "source_sha256": "DDBC0A14ECC172BF642CDE6117D9824E99E7553A97DEF644D7A09151D467F3E4",
        "receipt_path": "",
        "receipt_sha256": "",
        "result": "",
        "command": "",
        "source_pin_status": "not_applicable_no_run_receipt",
    },
    "op-fef1ba551941": {
        "status": "transcript_result_found_source_pin_unbound",
        "source_sha256": "C9947D2FE44582B238E6FAA0DF062C4B73B2542AF93D3037EB124A206147E2FD",
        "receipt_path": "T13 thread 01a0d8a1-7ce1-7470-8e18-ee0a2ac57a5d; handoff/root-source-deterministic-overlay-20261001",
        "receipt_sha256": "",
        "result": "34 passed in 5.36s; selector included in suite",
        "command": "python -B -m pytest -c pytest.ini -q -p no:cacheprovider --tb=short tests/test_operational_mode.py::test_missing_mode_file_defaults_to_active tests/test_operational_mode.py::test_mode_updates_are_persisted_and_increment_revision tests/test_operational_mode.py::test_mode_update_waits_for_writer_in_another_process tests/test_operational_mode.py::test_mode_updates_from_multiple_processes_do_not_lose_revisions tests/test_operational_mode.py::test_mode_replace_retries_windows_sharing_violation tests/test_operational_mode.py::test_mode_replace_sharing_violation_retry_is_bounded tests/test_operational_mode.py::test_mode_update_retries_transient_replace_permission_error tests/test_operational_mode.py::test_corrupt_mode_fails_closed_to_maintenance tests/test_operational_mode.py::test_http_mode_routes_read_and_update_persisted_mode tests/test_operational_mode.py::test_http_mode_skips_gaming_unload_after_later_resume tests/test_operational_mode.py::test_mcp_agent_tool_is_rejected_before_dispatch_but_status_remains_available tests/test_http_mode_update_rejects_invalid_and_unauthorized_requests tests/test_operational_mode_http_gate.py::test_context_pack_is_retryably_gated_in_paused_modes tests/test_operational_mode_http_gate.py::test_gaming_allows_safe_reads_but_maintenance_blocks_agent_reads tests/test_mcp_operational_mode_dispatch.py::test_gaming_mcp_dispatch_allows_only_speculative_lint tests/test_mcp_operational_mode_dispatch.py::test_maintenance_mcp_dispatch_still_blocks_speculative_lint tests/test_mcp_task_mode_gate.py::test_gaming_defers_mcp_inference_with_bounded_retry tests/test_mcp_task_mode_gate.py::test_gaming_allows_cheap_artifact_read tests/test_mcp_task_mode_gate.py::test_maintenance_blocks_agent_action_but_preserves_job_status tests/test_client_transport.py::test_client_replays_duplicate_request_until_owner_finishes tests/test_hubctl_mode.py::test_hubctl_pause_resume_use_authorized_mode_endpoint tests/test_hubctl_mode.py::test_hubctl_sets_mode_offline_without_starting_server tests/test_hubctl_mode.py::test_hubctl_reads_persisted_mode_offline tests/test_hubctl_mode.py::test_hubctl_mode_does_not_assume_requested_mode_without_server_confirmation tests/test_hubctl_mode.py::test_hubctl_mode_reads_current_mode tests/test_preprocess_operational_mode.py::test_gaming_finishes_current_step_then_active_resumes_one_checkpoint tests/test_preprocess_operational_mode.py::test_gaming_cpu_loop_does_not_schedule_another_project_step tests/test_preprocess_operational_mode.py::test_gaming_gpu_loop_does_not_schedule_another_project_step tests/test_preprocess_operational_mode.py::test_gaming_unschedules_watcher_and_active_resyncs_once",
        "source_pin_status": "owner supplied worktree file hash; transcript did not bind hash to this run",
    },
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


gap_rows = read_csv(GAP_CSV)
gap_metadata = json.loads(GAP_JSON.read_text(encoding="utf-8"))
delta_rows = read_csv(DELTA_CSV)
triage_rows = read_csv(TRIAGE_CSV)
delta_by_id = {row["operation_id"]: row for row in delta_rows}
triage_by_id = {row["operation_id"]: row for row in triage_rows}
extra_fields = [
    "root_delta_owner_task",
    "root_delta_test_ids",
    "root_delta_test_coverage",
    "root_delta_behavioral_disposition",
    "operation_level_review",
    "assertion_scope_review",
    "owner_execution_receipt_status",
    "owner_test_source_sha256",
    "owner_receipt_path",
    "owner_receipt_sha256",
    "owner_test_execution_result",
    "owner_test_execution_command",
    "owner_test_source_pin_status",
    "gap_matrix_member",
    "root_delta_member",
    "triage_candidate_selector",
    "triage_candidate_result",
    "triage_candidate_scope",
    "triage_candidate_acceptance_gap_fields",
    "triage_evidence_status",
]

with OUT_CSV.open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(
        handle, fieldnames=list(gap_rows[0]) + extra_fields, extrasaction="ignore"
    )
    writer.writeheader()
    for row in gap_rows:
        delta = delta_by_id.get(row["operation_id"], {})
        triage = triage_by_id.get(row["operation_id"], {})
        disposition, scope = REVIEW.get(
            row["operation_id"],
            (
                "unverified_no_asserted_operation_test",
                "Gap matrix lists metadata-only operation-contract selector; no asserted operation behavior test linked.",
            ),
        )
        receipt = RECEIPTS.get(
            row["operation_id"],
            {
                "status": "no_operation_test_selector_in_root_delta",
                "source_sha256": "",
                "receipt_path": "",
                "receipt_sha256": "",
                "result": "",
                "command": "",
                "source_pin_status": "no_owner_test_execution_receipt",
            },
        )
        row.update(
            root_delta_owner_task=delta.get("owner_task", ""),
            root_delta_test_ids=delta.get("test_ids", ""),
            root_delta_test_coverage=delta.get("test_coverage", ""),
            root_delta_behavioral_disposition=delta.get("behavioral_disposition", ""),
            operation_level_review=disposition,
            assertion_scope_review=scope,
            owner_execution_receipt_status=receipt["status"],
            owner_test_source_sha256=receipt["source_sha256"],
            owner_receipt_path=receipt["receipt_path"],
            owner_receipt_sha256=receipt["receipt_sha256"],
            owner_test_execution_result=receipt["result"],
            owner_test_execution_command=receipt["command"],
            owner_test_source_pin_status=receipt["source_pin_status"],
            gap_matrix_member="true",
            root_delta_member="true" if delta else "false",
            triage_candidate_selector=triage.get("candidate_receipt_selector", ""),
            triage_candidate_result=triage.get("candidate_receipt_result", ""),
            triage_candidate_scope=triage.get("candidate_receipt_scope", ""),
            triage_evidence_status=(
                "candidate_result_claim_unverified"
                if triage.get("candidate_receipt_selector")
                else "triage_reports_no_asserted_operation_test"
                if triage
                else ""
            ),
        )
        writer.writerow(row)

supplemental_triage_rows = [
    row for row in triage_rows if row["operation_id"] not in {item["operation_id"] for item in gap_rows}
]
with OUT_CSV.open("a", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(
        handle, fieldnames=list(gap_rows[0]) + extra_fields, extrasaction="ignore"
    )
    for triage in supplemental_triage_rows:
        delta = delta_by_id.get(triage["operation_id"], {})
        is_task_rollback_candidate = triage["operation_id"] == "op-28d63e90525c"
        base = {field: "" for field in gap_rows[0]}
        base.update(
            operation_id=triage["operation_id"],
            surface=triage["surface"],
            name=triage["operation"],
            primary_owner_task=triage["owner_task"],
            state=delta.get("state", ""),
            evidence_status="",
            code_evidence=json.dumps([triage["source_evidence"]]),
            gap_class="supplemental high-impact triage row outside baseline gap v2",
            current_test_ids=delta.get("test_ids", ""),
            test_coverage="metadata only; operation behavior unverified",
            behavioral_disposition=triage["behavioral_status"],
            acceptance="",
            handoff="supplemental high-impact triage; owner remains assigned",
        )
        receipt = (
            {
                "status": "t01_targeted_pytest_passed_source_pinned",
                "source_sha256": "2EA4B59D11DB9519C3FC1D2A98C22AAC78E68D67B8C31C802602F16D4FFC11B6",
                "receipt_path": T01_RECEIPT.relative_to(ROOT).as_posix(),
                "receipt_sha256": sha256(T01_RECEIPT),
                "result": "2 passed in 2.82s",
                "command": "$env:PYTHONPATH='src'; & 'C:\\Python313\\python.exe' -B -m pytest -q --tb=short tests/test_mcp_coord_operation_acceptance.py::test_http_agent_task_rejects_unknown_action_without_store_mutation tests/test_mcp_coord_operation_acceptance.py::test_local_ai_coord_task_rollback_restores_and_persists_previous_checkpoint",
                "source_pin_status": "T01 worktree source hash recorded in adjacent run receipt",
            }
            if is_task_rollback_candidate
            else {
                "status": "no_asserted_operation_test",
                "source_sha256": "",
                "receipt_path": "",
                "receipt_sha256": "",
                "result": "",
                "command": "",
                "source_pin_status": "not_applicable",
            }
        )
        base.update(
            root_delta_owner_task=delta.get("owner_task", ""),
            root_delta_test_ids=delta.get("test_ids", ""),
            root_delta_test_coverage=delta.get("test_coverage", ""),
            root_delta_behavioral_disposition=delta.get("behavioral_disposition", ""),
            operation_level_review=(
                "targeted_behavior_test_passed_in_t01_current_worktree"
                if is_task_rollback_candidate
                else "unverified_no_asserted_operation_test"
            ),
            assertion_scope_review=(
                triage["candidate_receipt_scope"]
                if is_task_rollback_candidate
                else "High-impact triage lists no asserted operation test; owner acceptance remains open."
            ),
            owner_execution_receipt_status=receipt["status"],
            owner_test_source_sha256=receipt["source_sha256"],
            owner_receipt_path=receipt["receipt_path"],
            owner_receipt_sha256=receipt["receipt_sha256"],
            owner_test_execution_result=receipt["result"],
            owner_test_execution_command=receipt["command"],
            owner_test_source_pin_status=receipt["source_pin_status"],
            gap_matrix_member="false",
            root_delta_member="true" if delta else "false",
            triage_candidate_selector=triage.get("candidate_receipt_selector", ""),
            triage_candidate_result=triage.get("candidate_receipt_result", ""),
            triage_candidate_scope=triage.get("candidate_receipt_scope", ""),
            triage_candidate_acceptance_gap_fields=triage.get("acceptance_gap_fields", ""),
            triage_evidence_status=(
                "current_t01_receipt_recorded"
                if is_task_rollback_candidate
                else "triage_reports_no_asserted_operation_test"
            ),
        )
        writer.writerow(base)

review_counts = Counter(
    row["operation_level_review"] for row in read_csv(OUT_CSV)
)
owner_counts = Counter(row["primary_owner_task"] for row in read_csv(OUT_CSV))
summary = {
    "schema_version": "t01-operation-evidence-review/v1",
    "captured_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "workspace": str(ROOT),
    "command": "& 'C:\\Python313\\python.exe' -B handoff/T01-build-operation-evidence-review-20261001-v1.py",
    "builder_sha256": sha256(Path(__file__)),
    "inputs": {
        GAP_CSV.relative_to(ROOT).as_posix(): sha256(GAP_CSV),
        GAP_JSON.relative_to(ROOT).as_posix(): sha256(GAP_JSON),
        DELTA_CSV.relative_to(ROOT).as_posix(): sha256(DELTA_CSV),
        TRIAGE_CSV.relative_to(ROOT).as_posix(): sha256(TRIAGE_CSV),
    },
    "output_csv": OUT_CSV.relative_to(ROOT).as_posix(),
    "output_csv_sha256": sha256(OUT_CSV),
    "counts": {
        "gap_matrix_rows": len(gap_rows),
        "high_impact_triage_rows": len(triage_rows),
        "high_impact_triage_overlap": len(set(row["operation_id"] for row in gap_rows) & set(row["operation_id"] for row in triage_rows)),
        "supplemental_triage_rows": len(supplemental_triage_rows),
        "output_rows": len(read_csv(OUT_CSV)),
        "gap_matrix_unassigned": sum(
            not row["primary_owner_task"].strip() for row in gap_rows
        ),
        "root_delta_rows": len(delta_rows),
        "operation_id_intersection": len(
            set(row["operation_id"] for row in gap_rows) & set(delta_by_id)
        ),
        "review_disposition_counts": dict(sorted(review_counts.items())),
        "baseline_test_coverage_counts": dict(
            sorted(Counter(row["test_coverage"] for row in gap_rows).items())
        ),
        "surface_coverage": gap_metadata["coverage"],
        "owner_counts": dict(sorted(owner_counts.items())),
    },
    "reviewed_root_delta_selectors": {
        operation_id: {
            "owner": delta_by_id[operation_id]["owner_task"],
            "test_ids": json.loads(delta_by_id[operation_id]["test_ids"]),
            "review": REVIEW[operation_id][0],
            "scope": REVIEW[operation_id][1],
            "execution_receipt_status": RECEIPTS[operation_id]["status"],
            "test_source_sha256": RECEIPTS[operation_id]["source_sha256"],
            "execution_receipt_path": RECEIPTS[operation_id]["receipt_path"],
            "execution_receipt_sha256": RECEIPTS[operation_id]["receipt_sha256"],
            "execution_result": RECEIPTS[operation_id]["result"],
            "execution_command": RECEIPTS[operation_id]["command"],
            "source_pin_status": RECEIPTS[operation_id]["source_pin_status"],
        }
        for operation_id in sorted(REVIEW)
    },
    "confirmed_execution_receipts": sum(
        receipt["status"] == "transcript_result_found_source_pin_unbound"
        for receipt in RECEIPTS.values()
    ),
    "confirmed_execution_receipts_total": sum(
        receipt["status"] == "transcript_result_found_source_pin_unbound"
        for receipt in RECEIPTS.values()
    ) + int(T01_RECEIPT.exists()),
    "owner_receipt_lookup_pending": [
        operation_id
        for operation_id, receipt in RECEIPTS.items()
        if receipt["status"] == "owner_lookup_pending"
    ],
    "supplemental_triage_candidates": [
        {
            "operation_id": row["operation_id"],
            "owner_task": row["owner_task"],
            "selector": row["candidate_receipt_selector"],
            "claimed_result": row["candidate_receipt_result"],
            "scope": row["candidate_receipt_scope"],
            "source_sha256_in_t01_checkout": sha256(T01_TEST_SOURCE),
            "receipt_path": T01_RECEIPT.relative_to(ROOT).as_posix(),
            "receipt_sha256": sha256(T01_RECEIPT),
            "result": "2 passed in 2.82s",
            "command": "$env:PYTHONPATH='src'; & 'C:\\Python313\\python.exe' -B -m pytest -q --tb=short tests/test_mcp_coord_operation_acceptance.py::test_http_agent_task_rejects_unknown_action_without_store_mutation tests/test_mcp_coord_operation_acceptance.py::test_local_ai_coord_task_rollback_restores_and_persists_previous_checkpoint",
            "assessment": "targeted T01 worktree run; source and adjacent result receipt hashes recorded",
        }
        for row in triage_rows
        if row.get("candidate_receipt_selector")
    ],
    "limits": [
        "Three selectors provide narrow direct route/action assertions; they do not establish downstream service/model quality.",
        "One selector proves disabled-mode rejection only, not successful enabled-mode operation.",
        "Remaining rows retain metadata-only test IDs and require owner-provided operation assertions.",
        "One targeted two-selector batch was run in T01 after explicit T02 slot release; no Hub calls were made.",
    ],
    "tests_run": [
        {
            "result": "2 passed in 2.82s",
            "command": "$env:PYTHONPATH='src'; & 'C:\\Python313\\python.exe' -B -m pytest -q --tb=short tests/test_mcp_coord_operation_acceptance.py::test_http_agent_task_rejects_unknown_action_without_store_mutation tests/test_mcp_coord_operation_acceptance.py::test_local_ai_coord_task_rollback_restores_and_persists_previous_checkpoint",
            "source_path": T01_TEST_SOURCE.relative_to(ROOT).as_posix(),
            "source_sha256": sha256(T01_TEST_SOURCE),
            "receipt_path": T01_RECEIPT.relative_to(ROOT).as_posix(),
            "receipt_sha256": sha256(T01_RECEIPT),
            "hub_calls": 0,
        }
    ],
}
OUT_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(
    json.dumps(
        {
            "rows": summary["counts"]["output_rows"],
            "baseline_gap_rows": len(gap_rows),
            "root_delta_rows": len(delta_rows),
            "high_impact_triage_rows": len(triage_rows),
            "supplemental_triage_rows": len(supplemental_triage_rows),
            "intersection": summary["counts"]["operation_id_intersection"],
            "reviews": summary["counts"]["review_disposition_counts"],
            "unassigned": summary["counts"]["gap_matrix_unassigned"],
            "csv_sha256": summary["output_csv_sha256"],
            "json_sha256": sha256(OUT_JSON),
        },
        sort_keys=True,
    )
)

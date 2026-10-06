# T01 root enum and feature gate continuation

Date: 2026-10-01 (Europe/Prague)

## Scope and ownership

- Candidate: `C:\Users\Adam\.codex\worktrees\t01-coverage-main-verify\.local-ai-hub`, base HEAD `689165fbe18101feacf5f489847a4890fc27ed1f`.
- Root inspected read-only: `C:\Users\Adam\.local-ai-hub`, HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.
- This append-only continuation supersedes the earlier T01 handoff's statement that T09 awaits a receipt enum. Root enum exists. T09 runner/config binding is still open.
- T20 owns root test serialization, root `API_COVERAGE.md` generation, and final `--check`. No root tests or document writes were performed here.

## Root action and receipt inventory

Action-specific rows are in `T01-root-registry-operation-coverage-20261001.csv` (SHA-256 `63A056FB81C84E0053DC94D11D3FDFF818B7C39032CEDE7BBEFA7142F3F94857`). It describes the current root registry and separates source/test references from fresh receipts.

- `operation_contracts.py` defines `verify_receipt` in both repo and coord action sets and gates both by `agent_os` (lines 45–81, 164). Root source SHA-256: `F51F8E395A2072B2534E4CE9F7D1A8285303B44FDF5737F49AD295A744D9B572`.
- `mcp_server.py` routes both actions to `/api/agent-state/verification` with action `receipt` (lines 2203–2206, 2746–2748). Root source SHA-256: `BFB3C65A513E2ADB669DDC52CFAAD6F8EC38B1624DCF5AD8F08361027C219DB3`.
- `VerificationReceipt` accepts `test`, `benchmark`, and `source_review`. Passed receipts require `evidence_id`; passed `test` and `benchmark` additionally require `command_id`. `source_review` may omit it. Root source SHA-256: `FDE1CF9EBC4D76324C33FDAA78190FAADBCCD7E953D8BE9D292A7AFFD96FDC73`.
- `test_repo_verify_receipt_schema_and_runtime_require_complete_typed_receipt` covers the repo action's nested schema. Existing agent consistency tests cover missing command ID for a passed test receipt and a passed source-review receipt without command ID. `test_verification_evidence_classification_is_conservative` checks benchmark classification and a typed benchmark receipt with command ID. None was run against root in this continuation.
- No action-specific behavior selector for `local_ai_coord.verify_receipt` was located in the inspected root test file; its operation behavior remains unverified.

The old enum claim is corrected. This does not prove T09's broker producer is admitted or that `command_sha256` is bound to the configured runner/current config; those remain T09/T06 acceptance.

## Operation test changes and receipts

Candidate test added: `test_local_ai_coord_feature_disabled_rejects_valid_action_before_backend_dispatch`. It calls the registered MCP tool with valid `task_rollback` parameters while `FEATURES.coord=False`, and asserts an unsupported response before any `CLIENT` access. Import-origin assertion ensures the tested module came from this candidate.

Exact command:

```powershell
$env:PYTHONPATH='src'; C:\Python313\python.exe -B -m pytest -q --tb=short tests/test_mcp_coord_operation_acceptance.py::test_http_agent_task_rejects_unknown_action_without_store_mutation tests/test_mcp_coord_operation_acceptance.py::test_local_ai_coord_task_rollback_restores_and_persists_previous_checkpoint tests/test_mcp_coord_operation_acceptance.py::test_local_ai_coord_feature_disabled_rejects_valid_action_before_backend_dispatch tests/test_surface_inventory.py::test_check_cli_preserves_stale_coverage_hash_on_drift tests/test_surface_inventory.py::test_check_cli_reports_drift_without_rewriting_coverage
```

Result: **5 passed in 8.27s**, exit 0. The two check-mode tests assert stale bytes/hash remain unchanged; one also asserts the file mtime remains unchanged. All fixtures were candidate-local; no socket, Hub, GPU, or root test was used.

Candidate test file SHA-256: `2EA4B59D11DB9519C3FC1D2A98C22AAC78E68D67B8C31C802602F16D4FFC11B6`.

Root already contains `test_registered_mcp_dispatch_rejects_non_object_output_without_replaying_handler`; its source asserts the invalid output envelope and `len(calls) == 1` (root `tests/test_operation_contracts.py`, lines 1063–1075; SHA-256 `D873FBD91CA805DE67EC62215BAC9A70834092644D2BE45853A92CE36D4B08E6`). It is source evidence only here; T20 must provide the root execution receipt.

## Root test-only patch

Prepared `T01-registry-disabled-feature-root-test-20261001.patch`, SHA-256 `0B80872091BB28FE78A15BF3905D89E35AA9A55BF02F192D965811F059DF6F38`. It adds one registered-dispatch test for valid coord action parameters while the feature is disabled, asserting HTTP-like status 403 before any backend access. The patch is test-only; root source is untouched.

- Root `git apply --check --whitespace=nowarn`: passed against HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.
- Applied to a temporary copy of the root test preimage; transformed Python AST parse: passed.
- No root pytest was run. Root execution is pending T20's test slot.

## Remaining acceptance

- The 537 operation rows previously marked behavior-unverified remain open; this receipt covers only the listed candidate selectors and the bounded root registry review above.
- T20 still owns one final root snapshot, full action-specific inventory reconciliation, `python tools/surface_inventory.py --write-doc`, then same-environment `--check` with an unchanged document hash.
- T09 runner/config binding and root integration receipts remain open. T01 is not done.

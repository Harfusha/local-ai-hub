# T06-T09 server command provenance contract v1

Status: historical volatile-ledger proposal; superseded by `T06-durable-command-provenance-v1.md`. Do not use this as the current contract.
Date: 2026-10-01

## Trust boundary

`/api/agent-state/verification` accepts caller-supplied receipts and records them. Current completion evaluation checks receipt presence, pass state, freshness, and repository revision. Those checks do not prove that `CommandBroker` issued the command identified by `command_id`.

Keep the T09 `VerificationReceipt` shape unchanged. Do not trust an `issuer` string, caller-provided artifact hash, command details, or self-consistent receipt fields as broker provenance.

## T06 producer contract

After an actual successful broker command stores its proof artifact and typed receipt, T06 records a private execution record in `CommandBroker`, keyed by the broker-generated `command_id`. The record contains:

- `command_id`, `task_id`, authenticated `tenant_identity`, task owner, and criterion;
- command SHA-256, classification, project alias/configuration/environment binding;
- evidence ID, repository revision, mutation generation, exit code zero, `cached=false`, and creation time.

The record does not contain caller-supplied issuer identity or raw command text. Cached results never mint a new proof or execution record. T06 lookup is `_get_server_command_execution_record(command_id)` and returns a defensive copy. Only broker code writes the bounded in-process ledger; public receipt APIs do not expose that writer.

## T09 consumer contract

For each command-verification receipt used at completion, T09 must look up the record by `receipt.command_id` through the server-owned broker/store interface. Require exact matches for task, tenant identity, owner, criterion, evidence ID, repository revision, command digest/classification, project binding, exit code, and `cached=false`. Fetch and validate the evidence artifact against that record. Missing, mismatched, evicted, or post-restart records fail closed. Public `coord verify_receipt` may store receipt metadata but cannot create a broker execution record.

No new parallel verification database. If restart-persistent records are required, T09 should add a private broker-only write/read API to the existing `VerificationStore` database, keyed uniquely by `command_id`; do not expose its writer through the public receipt route. T09 owns `agent_verification.py` and consumer integration. T06 does not edit that module or its tests.

## Candidate limitation

Current T06 ledger is in-process and bounded to 2048 records. It proves broker issuance only while that process retains the record. Durable cross-restart acceptance remains blocked on T09's existing-store integration and consumer lookup. Current public completion path does not yet enforce this contract.


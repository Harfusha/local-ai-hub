# T06-T09 durable provenance consumer seam

Status: producer candidate implemented; T09 consumer integration remains open. T09 owns `agent_verification.py`; T06 does not edit it.

`CommandBroker._get_server_command_execution_record(command_id) -> dict[str, Any] | None` reads the persisted, broker-written record by command ID. It validates bounded file size, schema, record digest, exact command ID, zero exit, and `cached=false`. Return is defensive JSON data. It does not create storage on lookup.

The current record lives under the existing server-private `command-transactions/execution-records` directory. It binds tenant identity, task, owner, criterion, command SHA-256/classification, evidence ID, receipt digest, repository root and root digest, revision, mutation generation, project digests, exit status, and cache state. Writer is private broker code; public receipt submission does not call it.

T09 completion integration should call `CommandBroker.get_command_execution_record(receipt.command_id, *, tenant, task_id, repository_root)` using tenant, task and root from trusted server verification context, never from receipt/evidence claims. Then compare exact receipt and evidence artifact fields against record: task, tenant identity, owner, criterion, evidence ID, receipt digest, command SHA-256/classification, repository root/hash, revision, mutation generation, project binding, exit code, and cache state. Missing/malformed/mismatched record must reject verification. Current T09 consumer has not yet been wired to this seam; producer alone does not secure completion. Private compatibility getter `_get_server_command_execution_record(command_id)` is for broker-internal inspection only and does not validate scope.

Convenience API for internal callers needing explicit scope check: `get_command_execution_record(command_id, *, tenant, task_id, repository_root)`.


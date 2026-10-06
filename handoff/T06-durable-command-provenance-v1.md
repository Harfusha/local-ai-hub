# T06 durable command provenance handoff v1

Date: 2026-10-01
Status: producer delta implemented and isolated regressions pass; T09 consumer integration remains required.

## Durable contract

T06 records broker execution provenance only after a successful real run has persisted its proof artifact and current typed verification receipt. The record uses the existing `command-transactions` state directory and `_persist_transaction_journal` atomic writer. It does not add a second database or receipt system. Sidecars live in `execution-records/<sha256(command_id)>.json`, outside `*.journal.json` recovery matching.

T09 consumer seam: `CommandBroker._get_server_command_execution_record(command_id) -> dict | None`. It reads a bounded file and validates schema, record checksum, exact command ID, zero exit and `cached=false`. Stable scoped API: `CommandBroker.get_command_execution_record(command_id, *, tenant, task_id, repository_root) -> dict[str, Any] | None`. It verifies tenant identity, task, canonical root and root hash against durable record. T09 must pass tenant/task/root from trusted server verification context, never from caller-controlled receipt fields. T09 owns `agent_verification.py`; it must compare receipt and fetched artifact fields against this record at completion. Receipt shape stays unchanged.

Record binds tenant identity, task and owner, criterion, command digest and classification, canonical repository root and hash, repository revision, mutation generation, evidence ID, receipt digest, and project alias/config/environment/execution-binding digests when present. It has no caller-set issuer field or raw command. The record digest detects accidental or untrusted state edits; authority comes from its server-private state location and broker-only write path, not from a public key signature.

Cached, coalesced, synthetic `cache_*`, failed and `outcome_unknown` runs cannot create records. A caller-submitted receipt/artifact without a broker sidecar returns no record. Lookup is read-only and does not create the record directory. Persistence failure leaves the completion check fail-closed because the durable record is absent.

## Evidence

- Fail-first overlay: restart lookup and fabricated receipt had no getter; cache hit emitted another receipt. Three failures were expected.
- Green overlay: `tests/test_t06_durable_command_provenance.py`, 3 passed; exercises actual broker pytest run across broker restart, caller-fabricated receipt absence, cache hit no second receipt/sidecar, and tenant/task/root mismatch.
- T06 worktree focused checks: `tests/test_t06_server_command_provenance.py tests/test_t06_worktree_subprocess_tracking.py`, 3 passed.
- Root pin: `HEAD=98a9a1a7611af574caf20a88620c4aa3eb2e918a`; `src/local_ai_hub/commands.py` SHA-256 `3E10F0D793FD0AC4FF0D4A74E964800A4DBBF5F89A8B74FF6FD16CCCD30A4ACC` before delta; `process_utils.py` SHA-256 `4D5A1AFBCB23BAB1FE4EEC6B9639743D17920DE93E7A822EF64840815998D4EB` unchanged.
- Narrow producer+regression patch: Updated API patch: `T06-durable-command-provenance-root-pinned-v2.patch`, SHA-256 `962FD53023DF48CE6F3201E585247270C4D1EB557CFFB6AD8DADBD9E773FCC32`. Applies against pinned `commands.py` SHA-256 `3E10F0D793FD0AC4FF0D4A74E964800A4DBBF5F89A8B74FF6FD16CCCD30A4ACC`; CRLF-aware strict check passed in fresh copy. Historical producer-only patch v1 retains hash `AE64BF67614CA9F3AEAD82F8BC812AADEB60ABE0952E8444F3AF78B9423FE3FE`. `git apply --check` passed in a separate fresh copy with exact pinned root source; root itself was not modified.
- T09 was told to call `get_command_execution_record(command_id, *, tenant, task_id, repository_root)` with scope values from trusted server context; its owned consumer code is not edited here.

## Limits

T09 still needs to read the sidecar through its consumer seam and reject missing or mismatched records when evaluating completion. No root integration, full test suite, Docker or live-daemon proof is claimed. T20 owns root merge and integration validation.


T09 consumer status: latest T09 response acknowledges the seam but does not report integration. Completion remains fail-closed only after T09 wires its consumer; producer presence alone is insufficient.



# T03 contract and transport handoff

Snapshot: 2026-10-01. Candidate: `C:\Users\Adam\.codex\worktrees\e809\.local-ai-hub`, HEAD `d68ee694c6d3f75db5c1ab2f63497226880e5010`. Root integration belongs to T20; no root writes/tests by T03.

## Candidate acceptance

Command:

```powershell
$env:PYTHONPATH='src'; python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_operation_contracts.py tests/test_features.py tests/test_feature_surface_parity.py tests/test_generator.py tests/test_mcp_wire_contract.py tests/test_mcp_stdio_contract.py tests/test_client_transport.py tests/test_sse_events_stream.py tests/test_mcp_compact_transport.py::test_local_ai_repo_non_context_actions_ignore_guard_fields
```

Result: **274 passed in 25.54s**. Scoped `git diff --check` passed.

## T03-owned deltas

- `src/local_ai_hub/operation_contracts.py`: bounded, search-only `path_hints`; typed `verify_receipt`; receipt action gate and evidence requirement.
- `src/local_ai_hub/generator.py`: generated typed receipt schema.
- `src/local_ai_hub/mcp_server.py`: search hint normalization/forwarding and runtime receipt schema. File also contains unrelated shared hunks; transfer only T03 hunks.
- `tests/test_operation_contracts.py`: schema, validation, action scope and pipeline-step hint exclusion coverage. File contains shared hunks; transfer only T03 hunks.
- `tests/test_features.py`: removed stale `codegraph` toggle expectations after `FeatureSet` became Serena-only. Candidate file SHA-256 `7E02E22209C6198220935A5182DEA6068E9402D8F36F286D5A08AA121169D256`.
- Existing HTTP fallback uses `_begin_trace` header-or-UUID assignment and validates supplied IDs before recovery dispatch. `RecoveryJournal.begin` accepts `identity` and `payload`.

Candidate receipt patch: `handoff/T03-candidate-receipt-contract.patch`, SHA-256 `40BBD27ADCB80980E221183ACDEDC7B4E8D0C0D60242A78054E6B93134F6B80E`; reverse apply-check passed.
Candidate pipeline expectation patch: `handoff/T03-pipeline-step-hints-expectation.patch`, SHA-256 `20680F51C463A16E350D2BD5E4EF6B5B0190BE40778E842C7A1E31384D7C831D`; reverse apply-check passed.

## Root-current reconciliation

Observed root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`, dirty. Static source confirms `path_hints`, typed receipt scope, request-ID fallback, and `RecoveryJournal.begin(identity, payload)` are present.

- `handoff/T03-root-receipt-scope.patch`, SHA-256 `51F87E5DF8B476452B0A09D0690893447C64B006B10EE66669F276FFD3989754`: reverse apply-check passes on current root; T20 reported combined root selector **13 passed in 10.88s**.
- Historical request-ID patch `C:\Users\Adam\.codex\worktrees\t03-contracts-resume\.local-ai-hub\handoff\t03-request-id.patch`, SHA-256 `C61200CE4D6176557B39A52AF6D38F1D2F93262265E45F5D75BF78B92530D82F`: reverse apply-check passes. T20 previously reported its focused request-ID batch **28 passed in 3.34s**.
- `handoff/T03-root-path-hints.patch`, SHA-256 `44ED6619E8B16ABF882E0F8FBF836DC2231A645258CD8D8BB0F71CE7C7908A00`: stale against current root; reverse apply-check fails due context drift. Do not reapply blindly. T20 previously reported the root path-hints batch **30 passed in 84.98s**.

## Dependencies and open boundaries

- T04 root real-child startup to HTTP `/api/search`: **1 passed** (T04 reported 8.55s). T07 root replay selectors: **11/11**. T07 candidate request-ID/replay subset: **39 passed, 45 deselected**.
- T03 request-ID fallback contract is already integrated. `normalize_transport_error` copies mapping payload before status/retry normalization, preserving `request_id`; T07 confirmed no additional change needed at this seam.
- `/api/search` journal availability remains a T07/T08 global recovery-claim concern. T21 has not released `services.repo_search`; T03 does not own a safe patch for either boundary.
- Status output schema remains general under the user's explicit decision to defer typing until all status actions have complete contracts.
- `/api/context/pack` untouched by T03.

## Path-hints current-root proof

Compared current dirty root (HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`) against the older path-hints patch. No contract hunk is missing:

- `src/local_ai_hub/operation_contracts.py:175-178,207-224,482-551,1048-1098`: `_ACTION_SCOPED_FIELDS` permits `path_hints` for `search`; schema caps list at 64 and each path at 1024, requires `path`/`purpose`/`scope`, rejects extra properties. Per-action schema builders omit or disallow the field on other actions; runtime nested validation enforces the same schema.
- `src/local_ai_hub/mcp_server.py:144-195,1888,1953-1961,2357-2378`: `_normalize_repo_search_path_hints` caps and root-confines paths; `local_ai_repo` validates, normalizes and forwards hints for search via the HubClient keyword.
- `src/local_ai_hub/http_server.py:3865-3873`: `/api/search` passes `path_hints` into `APP.services.repo_search`.
- `src/local_ai_hub/services.py:2732-2783`: current root has `repo_search(..., path_hints=...)` and existing hint parsing/use. This downstream service behavior remains T21-owned; T03 did not edit or revalidate it here.
- Root behavioral tests are present at `tests/test_operation_contracts.py:409-440,461+` and `tests/test_mcp_compact_transport.py:67-73,144-156`; they cover search-only schema/runtime validation, size bounds, path normalization/root escape, and forwarding capture.
- Current candidate behavioral selectors: **9 passed in 2.87s** across bounded/search-only schema, wrapper forwarding, Windows/root normalization, traversal rejection, and MCP guard handling. Command is the five `test_operation_contracts.py` selectors plus `test_mcp_compact_transport.py::test_local_ai_repo_non_context_actions_ignore_guard_fields`.
- T20 previously reported **30 passed** for its root path-hints batch. No root test was run in this snapshot.

The old `T03-root-path-hints.patch` (SHA-256 `44ED6619E8B16ABF882E0F8FBF836DC2231A645258CD8D8BB0F71CE7C7908A00`) fails forward and reverse apply-check because root hunks have since changed. Static current-root evidence shows the public contract/dispatch is already present; no replacement patch is needed. Do not reapply this stale patch. T21 owns downstream path-config behavior and release confirmation.

# T03 contract and transport acceptance handoff

Date: 2026-10-01. Candidate worktree: `C:\Users\Adam\.codex\worktrees\e809\.local-ai-hub`, HEAD `d68ee694c6d3f75db5c1ab2f63497226880e5010`. Root integration remains T20-owned. This is a handoff, not a claim that current root integration is complete.

## Current gate and receipts

T02 released the candidate test slot. The bounded Local AI Hub command tool was not exposed, so one native fallback ran in this T03 worktree. It completed with **274 passed in 31.77s**. The T01 exclusive test slot was announced while that command was already running; the interrupt arrived after completion output, and no further tests were started.

Command:

```powershell
$env:PYTHONPATH='src'; python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_operation_contracts.py tests/test_features.py tests/test_feature_surface_parity.py tests/test_generator.py tests/test_mcp_wire_contract.py tests/test_mcp_stdio_contract.py tests/test_client_transport.py tests/test_sse_events_stream.py tests/test_mcp_compact_transport.py::test_local_ai_repo_non_context_actions_ignore_guard_fields
```

Prior receipts: same contract/transport suite **274 passed in 25.54s**; focused path-hints selectors **9 passed in 2.87s**; T20 reported **30 root path-hints tests passed**. These are separate runs. Do not run root tests from T03 or start more tests until T20 releases the T01 slot.

## T03-owned scope

- `src/local_ai_hub/operation_contracts.py`: search-only bounded `path_hints`; receipt action scope and typed `verify_receipt` request contract.
- `src/local_ai_hub/mcp_server.py`: path-hint validation, root confinement and forwarding; receipt registration schema/gate. These files contain unrelated hunks: integrate only owned hunks.
- `src/local_ai_hub/http_server.py`: `/api/search` optional path-hint forwarding/signature gate and previously reviewed transport request-ID/SSE hunks. Do not replace the file.
- `src/local_ai_hub/generator.py`: typed receipt schema generation.
- `tests/test_operation_contracts.py`, `tests/test_features.py`: scoped contract and feature expectation coverage.

Public path-hints schema/dispatch is already present in the observed root. The old `handoff/T03-root-path-hints.patch` SHA-256 `44ED6619E8B16ABF882E0F8FBF836DC2231A645258CD8D8BB0F71CE7C7908A00` is stale and fails current-root apply-check; do not apply it. Root-current search reconciliation is in `handoff/T03-root-search-seam-reconciliation.md`.

## Ownership and omitted hunks

- T21 owns `services.repo_search` and `project_config.py`. Candidate T03's service method lacks `path_hints`; current root has the T21 adapter. Do not transfer T03 `services.py` wholesale: its dirty changes are write-set dispatch work, unrelated to path-hints.
- T06 owns safe-command/worktree cleanup. `handoff/T03-T06-cleanup-actor-caller.patch` is a one-line root-current caller suggestion with an earlier apply-check PASS against root HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`; T20 must recheck against its current root before use. Its HTTP cleanup actor bridge is separate from T03 acceptance.
- Omit receipt/pipeline hunks unless separately approved for integration; omit MCP tool-catalog/status/transport and non-search changes; omit every HTTP route except the explicitly released `/api/search` seam; omit `/api/context/pack`, T13 gaming/operational-mode, and T06 cleanup source hunks; omit unrelated docs and tests.

## Relevant candidate selectors for post-release run

```text
tests/test_operation_contracts.py::test_repo_path_hints_schema_is_bounded_and_search_only
tests/test_operation_contracts.py::test_local_ai_repo_path_hints_forward_only_when_consumer_supports_them
tests/test_operation_contracts.py::test_local_ai_repo_search_normalizes_windows_path_hints_within_root
tests/test_operation_contracts.py::test_local_ai_repo_search_rejects_path_hints_outside_root_before_dispatch
tests/test_operation_contracts.py::test_local_ai_repo_search_rejects_backslash_traversal_for_posix_root
tests/test_mcp_compact_transport.py::test_local_ai_repo_non_context_actions_ignore_guard_fields
```

Patch artifacts and scope:

- Candidate receipt contract: `handoff/T03-candidate-receipt-contract.patch`, SHA-256 `40BBD27ADCB80980E221183ACDEDC7B4E8D0C0D60242A78054E6B93134F6B80E`.
- Pipeline expectation: `handoff/T03-pipeline-step-hints-expectation.patch`, SHA-256 `20680F51C463A16E350D2BD5E4EF6B5B0190BE40778E842C7A1E31384D7C831D`.
- Root receipt-scope patch: `handoff/T03-root-receipt-scope.patch`, SHA-256 `51F87E5DF8B476452B0A09D0690893447C64B006B10EE66669F276FFD3989754`; root reverse apply-check had passed in the prior snapshot.
- Search path-hints patch `handoff/T03-root-path-hints.patch`, SHA-256 `44ED6619E8B16ABF882E0F8FBF836DC2231A645258CD8D8BB0F71CE7C7908A00`, is stale and must not be applied. Root-current reconciliation says no patch is needed.
- Historical request-ID patch at `C:\Users\Adam\.codex\worktrees\t03-contracts-resume\.local-ai-hub\handoff\t03-request-id.patch`, SHA-256 `C61200CE4D6176557B39A52AF6D38F1D2F93262265E45F5D75BF78B92530D82F`; prior root reverse apply-check passed.

Use the candidate worktree revision plus its scoped hunks as source of truth; do not apply whole-file replacements from dirty shared files. `/api/context/pack` was not edited by this handoff.

## 2026-10-04 continuation

- User approved the bounded search-only `path_hints` MCP contract and notification to T21. The candidate contract and forwarding selectors are present; T21 was notified. T03 did not edit T06's HTTP route or T21's service adapter.
- Candidate focused contract/dispatch/journal/wire selection: 108 passed in 26.83s. Explicit safe-POST transport selection: 3 passed in 1.35s. These receipts do not prove live Hub transport.
- Root compatibility probe for candidate-only output-schema gates: patch applied only to a scratch copy; `git apply --check` and scratch apply passed, but scratch pytest failed (11 failed, 1 passed, 1 error). The probe emitted no root patch. Per user decision, defer action-specific status output schemas until complete contracts exist.
- Bugbot found a T06 `/api/search` capability-check edge: a `VAR_POSITIONAL` parameter named `path_hints` is treated as keyword-callable. Finding sent to T06; T03 did not edit the route.

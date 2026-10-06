# T04 merge-ready handoff

Date: 2026-10-01 (Europe/Prague)

## Delivery

- T04 worktree: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`
- Branch: `codex/t04-integration-2b33602`
- Candidate HEAD: `3658d5056354849ddf17883ed04f807f16cc44c1`
- Committed T04 API/query work: `e2dcd2c`, `f305ec6`, `3658d50` (HEAD above). These commits are the exact immutable delivery for public API contracts, task-list query filtering, and artifact-list tenant filtering.
- Root-compatible subset already integrated by T20: `artifacts/t04-current-root-api-acceptance.patch`, SHA-256 `1E8740300FDACFC3B407788E2DD5D20321407A005EB6F802B84F85FDAF4171A1`. T04 did not write to root. Root receipt: `artifacts/t04-current-root-acceptance-receipt.md`, SHA-256 `3FE4FB3DC7E078A413B8DD9911F66486F67CCC572632CC1459849A2B91547095`.

## Verification receipts

- T04 assigned nine-file suite: **132 passed in 26.57s**, exit 0; log `artifacts/t04-full-assigned-suite-after-fix.log`, SHA-256 `7CC3BE41A4D4E4CD8471DDEE0287A3BD8FF5F3318D80E56D2A10277B70E03403`.
- T04 public API/conversation/query/inventory selectors: **39 passed in 43.83s**, exit 0; log SHA-256 `9FC7FD1F9D623B9503C798DFDA70F15AF5F0E8A945830D12CE59E3C6335178A5`.
- T04 client-to-loopback HTTP path-hint file: **7 passed in 2.31s**; log SHA-256 `347095BA30F1D9A4A000FF9E0345103D6501A7031E4B79E6857041DC8FCB0836`.
- Current root after T20 integration: **30 passed in 84.98s**, exit 0, exact command and source hashes recorded in `artifacts/t04-current-root-acceptance-receipt.md`.
- `git diff --check`: passed; only line-ending advisories.

## Ownership and transfer boundary

- Transfer the three commits above as the API/query slice. Root already contains equivalent behavior and a focused acceptance patch; use the root receipt rather than replaying the candidate commits blindly.
- The dirty candidate checkout is mixed-owner and must not be transferred wholesale. Confirmed T04 dirty hunks: failed startup-lock-write descriptor cleanup in `client.py`; real-child startup regression in `tests/test_client_startup_resilience.py`; operational-mode regression in `tests/test_operational_mode.py`; compact transport fixture correction in `tests/test_mcp_compact_transport.py`; discrete `include_code` forwarding fix in `mcp_server.py` and its selector.
- Preserve T10's runtime fixture hunk, T13's `operational_mode.py`, T07 request-ID hunks, and T21 path-hint client/service hunks under their owners. The provenance map in `artifacts/t04-client-hunk-provenance-current.md` records per-file boundaries and inherited dirty paths.
- `/api/context/pack` remains outside T04 scope and untouched by the T04 root acceptance patch.

## Open acceptance blocker

Full production path-hint acceptance is **not complete**. T04 proves HubClient serialization over a real loopback HTTP socket, but the current T04 MCP wrapper does not expose/forward `path_hints`; T03 owns that public wrapper. T21 owns the repository service consumer/runtime. No exact T03/T21 handoff authorizes copying their mixed hunks, and there is no production MCP-to-service result receipt. Do not claim this gate passed or merge those owner hunks by filename. Obtain exact T03/T21 owner-reviewed transfer boundaries, then schedule one shared test slot for the integrated MCP → HTTP → service result.

T04 did not modify root/master. No further validation was run for this handoff; receipts above are actual prior results.

## Root-only T04 delta (2026-10-01)

Read-only dirty-hunk comparison found the T04 real-child process acceptance has no root equivalent. A test-only patch isolates that exact T04-owned test into `tests/test_t04_real_child_startup_acceptance.py`; patch is `handoff/t04-real-child-startup-root-test.patch`, SHA-256 `DF2A2C5967885E0784EFEEA5BFF13B74DB57B81B3126BE8FBB8B4FDE2FFDFD76`. It adds one selector only. `git apply --check` against the current root exited 0; patch was not applied by T04.

Candidate evidence for the original test: `tests/test_client_startup_resilience.py::test_autostart_launches_real_hub_child_and_returns_http_search_result` was included in the assigned nine-file suite, **132 passed in 26.57s**, exit 0; suite log SHA-256 `7CC3BE41A4D4E4CD8471DDEE0287A3BD8FF5F3318D80E56D2A10277B70E03403`. Root focused command after T20 applies patch: `PYTHONPATH=src python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t04_real_child_startup_acceptance.py::test_autostart_launches_real_hub_child_and_returns_http_search_result`. No root result exists yet; T20 owns the slot.

Root-owner integration observed 2026-10-01: `tests/test_t04_real_child_startup_acceptance.py` is now present in root, untracked, SHA-256 `A9237EB5349C15CE4C7DEC92842A907593EA05C670D92C97C56B2A8FA4E2E9AA`; root HEAD remains `98a9a1a7611af574caf20a88620c4aa3eb2e918a`. No pytest process was running during the check. T04 did not write root or run the selector; focused root result remains pending T20 slot assignment.

No T04 production source patch is proposed: remaining `client.py` lock lifecycle hunks intersect T03 identity semantics, and MCP/request-ID changes are T07-owned. This root-only test delta does not close the separate T03/T21/T16 path-hint adapter blocker recorded above.

## Continuation checkpoint (2026-10-01)

T03 released its current-root path-hint schema/forwarding patch (`T03-root-path-hints.patch`, SHA-256 `44ED6619E8B16ABF882E0F8FBF836DC2231A645258CD8D8BB0F71CE7C7908A00`; owner-reported root batch 30 passed). A read-only `git apply --check` against the T04 candidate failed because `operation_contracts.py` and `tests/test_operation_contracts.py` are absent at this older candidate base and MCP/test hunk context differs. No partial patch was applied.

T21's current owner matrix assigns `services.py` search/adapter work to T16 (possible T06 overlap), keeps project-config core in T21, and marks consumer adapters frozen under the latest user boundary. T04's `services.repo_search` has no `path_hints`; T04 `/api/search` rejects hints when the service signature lacks support. No T21/T16/T06 exact service-consumer release is available. Thus full MCP → HTTP → service path-hint acceptance remains blocked by explicit shared ownership, not by a test failure. T04 client-to-loopback HTTP evidence remains 7 passed; it is not production E2E.

No root writes or tests occurred in this continuation. T20 was asked to adjudicate whether any narrow owner-release path is authorized; wait for its direction before touching shared adapter hunks or scheduling root validation.

Candidate refresh (2026-10-01): after the preceding suite receipt, T04 reran only `tests/test_client_startup_resilience.py::test_autostart_launches_real_hub_child_and_returns_http_search_result` in the T04 candidate worktree. Exact command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_client_startup_resilience.py::test_autostart_launches_real_hub_child_and_returns_http_search_result` with `PYTHONPATH=C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub\src`. Result: **1 passed in 8.55s**, exit 0. Candidate-only evidence; does not substitute for the separate root selector. Shared test slot released to T20 after completion.


## Fresh candidate transport/E2E validation (2026-10-01)

See artifacts/t04-client-transport-e2e-current-receipt.md for exact selectors, results, and SHA-256 bindings. Fresh focused candidate batches: 9 connection/replay selectors passed (2.19s), 7 request-ID/retry selectors passed (3.37s), 4 real HTTP conversation selectors passed (10.85s), and 7 client path-hint selectors passed (2.97s). The real-child startup → HTTP /api/search selector passed 1/1 in the immediately preceding continuation (8.55s). Total 28 passed across these non-overlapping commands; no root writes. Root real-child selector remains T20-owned. Full production MCP-to-service path-hint acceptance remains outside the current T04 ownership boundary.

## Explicit request-ID root-current handoff (2026-10-01)

`artifacts/t04-request-id-root-current-handoff.md` records symbol-level comparison, exact hashes, T07 boundary, and the focused 2-pass candidate run. The allowed T04 request-ID validation/signature/header/forwarding symbols and both selectors already match current root, so this slice has no non-empty root patch. T07 uncertain-retry/replay-result code and fixtures remain excluded.

## T04 root-current transport classification handoff (2026-10-01)

Two unowned T04 transport-classification selectors have a test-only patch at `handoff/t04-root-current-transport-classification.patch` (SHA-256 `7FC09745E399D76DADF0EB808327EA01980E6CC1C29713C0B30CEE75BAAD17BC`). Root `git apply --check --whitespace=error` passed; root stayed unchanged. Candidate coverage exists in the earlier 9-pass connection group. Per current T02 slot instruction, the exact two-selector rerun is queued until T02 releases. See `artifacts/t04-root-current-transport-classification-handoff.md` for paths, root hashes, scope exclusions, and command.

T02 released the shared test slot. The two T04 classification selectors then passed in the candidate (**2 passed, 1.83s**) and against root source through a temporary patched test overlay (**2 passed, 14.95s**, root HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`). Root was not modified. Current receipts and patch SHA are in `artifacts/t04-root-current-transport-classification-handoff.md`.

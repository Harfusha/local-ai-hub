# T04 continuation acceptance receipt — 2026-10-01

Candidate worktree: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`
Candidate branch/HEAD: `codex/t04-integration-2b33602` / `3658d5056354849ddf17883ed04f807f16cc44c1`
Root HEAD observed for assigned selectors: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.
Root was not edited by T04.

## Owned autostart proof

Candidate command:
`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_client_startup_resilience.py::test_readiness_timeout_terminates_only_owned_child_and_cleans_lock tests/test_client_startup_resilience.py::test_blocked_operational_modes_never_spawn_for_offline_request tests/test_client_startup_resilience.py::test_autostart_launches_real_hub_child_and_returns_http_search_result`

Result: **4 passed in 11.36s**. The actual child uses temporary TOML/state and an ephemeral loopback port. Ollama, smart Ollama, llama.cpp, Serena, and background preprocessing are disabled. Test checks actual HTTP `/api/search` output, bounded exact-child cleanup, lock cleanup, and gaming/maintenance no-spawn failure classification.

Root-current patch: `handoff/t04-autostart-cold-child-root-current.patch`, SHA-256 `27bc3212b4d914361a45354359a7f3b285d7593f34f35ce41b49d0ca524a7198`; path `tests/test_t04_real_child_startup_acceptance.py`. Root apply-check passed. Test preimage SHA-256 before application: `a9237eb5349c15ce4c7dec92842a907593ea05c670d92c97c56b2a8fa4e2e9aa`. Root selector `C:\Python313\python.exe -B -m pytest -q -p no:cacheprovider --tb=short -c pyproject.toml tests/test_t04_real_child_startup_acceptance.py::test_autostart_launches_real_hub_child_and_returns_http_search_result` passed **1 in 7.58s**, root HEAD unchanged.

## SSE disconnect and classifier parity

A RED test proved a live SSE client disconnect finalized the request as success. Candidate fix now records disconnect as `success=False`, error `client disconnected`; unknown stream exception records `stream failed`. Subscription is still removed in `finally`.

- RED: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_sse_events_stream.py::test_sse_stream_replays_and_receives_live_events` — **1 failed in 2.21s**, expected old `(True, "")` classification.
- GREEN: same command after fix — **1 passed in 0.35s**.
- Cancel/disconnect, stable/rejected request ID and client classifier command recorded in `artifacts/t04-sse-and-transport-parity-receipt.md` — **16 passed in 2.93s**.

Root-current SSE patch: `handoff/t04-sse-disconnect-root-current.patch`, SHA-256 `d17394eb216f92a783555ccf420435231da268a75d1e0dfc0d88a33ed8a32271`. Paths: `src/local_ai_hub/http_server.py`, `tests/test_sse_events_stream.py`. Root preimage SHA-256: HTTP server `c619ae6297f9b99466304722e95455994bffdf88258e32b1487fed247f159e15`; SSE tests `fd278ef2a1472203b50c99f9d5e2d1af0f87397b6db3a103952d91be5bd88cbd`. Root apply-check passed. Patch touches only stream lifecycle and disconnect regression assertion; unrelated dirty HTTP hunks preserved.

## Current-candidate API/conversation acceptance

Command:
`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t04_public_api_contracts.py tests/test_conversations.py tests/test_conversation_continue_route_contract.py tests/test_mcp_agent_routing.py::test_local_ai_repo_investigate_preserves_include_code tests/test_mcp_agent_routing.py::test_repo_review_diff_returns_foreground_result_by_default`

Result: **35 passed in 40.29s**.

Additional command for RAG/work descriptions, bounded task-query behavior, and v2/legacy artifact-list isolation: 8 explicit selectors in `tests/test_t04_public_api_contracts.py` — **8 passed in 21.50s**. Exact selector list appears in command receipt in task history; no root suite was run.

A mistaken selector lookup in `test_mcp_agent_routing.py` matched no tests and executed zero tests. Correct selectors were located in `test_t04_public_api_contracts.py` and the corrected command passed. No retry of the same command.

## Remaining acceptance gaps

- Candidate branch itself still lacks T03/T21 caller `path_hints` forwarding. A test-only isolated subprocess against the current root source overlay now proves actual registered FastMCP-to-`HubClient`-to-HTTP forwarding; production ownership/integration remains T03/T21 and is not edited by T04.
- T20 owns integration and root validation of the autostart and SSE patches. No root polling or root tests were run after handoff.
- Therefore T04 remains open; this receipt does not claim whole-task completion.

### Additional client-path and mode evidence

Command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_client_path_hints.py tests/test_client_operational_mode_autostart.py`

Result: **12 passed in 2.55s**, exit 0. This proves `HubClient` path-hint serialization over a real local HTTP fixture and active/missing-vs-blocked autostart policy. It does not prove caller-level MCP path-hint forwarding. Static search in current T04 `src/local_ai_hub/mcp_server.py` returns no `path_hints` references. `T03` public wrapper and `T21` private adapter remain ownership boundary.

SSE source/test scoped `git diff --check` passes after the fix. Candidate whole-task acceptance remains open for the MCP path-hint chain and T20 root integration.

### Daemon-off and MCP transport

Command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_mcp_compact_transport.py::test_mcp_status_remains_usable_when_hub_daemon_is_offline tests/test_mcp_compact_transport.py::test_mcp_delegate_autostarts_owned_daemon_and_preserves_http_payload`

Result: **2 passed in 11.70s**, exit 0. Covers daemon-off status without process spawn and MCP delegated request over the existing auto-start/in-process test server with preserved HTTP payload. This is distinct from the real-child E2E selector above.

### Root-overlay caller path-hint chain

Test-only candidate selector:
`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t04_root_path_hint_chain.py::test_registered_repo_search_forwards_hints_over_real_root_http`

Result: **1 passed in 9.16s**, exit 0. Test starts an isolated Python subprocess with `PYTHONPATH` explicitly set to `C:\Users\Adam\.local-ai-hub\src`, verifies imported module origin, uses temporary config/state/repository plus ephemeral loopback HTTP server, and invokes real registered FastMCP `local_ai_repo` through real `HubClient`. It verifies positive hints reach `/api/search` and `repo_search`, empty hints are omitted, malformed/traversal hints return terminal 400 before HTTP, and hints cannot restore excluded paths. No production file or root file changed. Test SHA-256 `69391152DD30E4E573E62DB2541D3B0076671C6C02147D4BBC7F2C808650B672`.

Root overlay was read at unchanged HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`; source SHA-256s: `http_server.py` `C619AE6297F9B99466304722E95455994BFFDF88258E32B1487FED247F159E15`, `test_sse_events_stream.py` `FD278EF2A1472203B50C99F9D5E2D1AF0F87397B6DB3A103952D91BE5BD88CBD`. Candidate-source status remains separate: its `mcp_server.py` lacks caller hint propagation.

### T04 SSE patch versus T13 mode patch scope

Read-only symbol comparison against root HEAD above: T04 patch changes only `Handler._stream_agent_events` (`http_server.py`, line 1464) and SSE fixture/regression assertion. T13 mode changes in `http_server.py` are in `Handler.do_GET` (line 1563) and `Handler.do_POST` (line 2222), including mode cancellation state (`cancellation_error`, line 2256) and mode transition logic later in that method. No shared function or test fixture symbol detected; patch applies cleanly to current root using `git apply --check --whitespace=error handoff/t04-sse-disconnect-root-current.patch` from candidate worktree: **PASS**. Root files remain unmodified.

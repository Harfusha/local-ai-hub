# T04 continuation acceptance receipt — 2026-10-01 v2

## Candidate and current root snapshot

- Candidate worktree: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`
- Candidate HEAD: `3658d5056354849ddf17883ed04f807f16cc44c1`
- Root HEAD (read-only): `98a9a1a7611af574caf20a88620c4aa3eb2e918a`
- Root `src/local_ai_hub/http_server.py` SHA-256: `15BD92CE83A7FB472AAC4581F1A5FAD42ECF6E303C73C7DBC463E05A4528F57F`
- Root `src/local_ai_hub/client.py` SHA-256: `252F1781BE55DD2545DD7E3B21915F7A8AE20814DD2DB351E823124C6BFA1A19`
- Root remained untouched by this continuation. Existing root dirty paths remain T20-owned.

## New candidate evidence

- `src/local_ai_hub/client.py` SHA-256: `DCDF8BB8FF150B5FCD4EDD3A25B53991DD6B87CDB9DDDEC0714A7F11B2FAE5B1`
- `tests/test_t04_http_sse_integration.py` SHA-256: `B8237ABB33EE78C051DC43FBFFA871A13B31FF6354299BA6CF90D0554314C89E`
- Added explicit `HTTPConnection.close()` during SSE interrupt cleanup.
- Closed captured `HTTPError` response in missing-token integration test. Warning traceback showed the forgotten unauthorized-response socket, allocated by `urllib.request`; it was a test-fixture leak, not the SSE deadline response.

## Validation

- `python -X tracemalloc=6 -B -m pytest -q -W error::ResourceWarning --tb=short tests/test_t04_http_sse_integration.py tests/test_client_transport.py::test_stream_events_cancel_event_closes_blocked_response tests/test_client_transport.py::test_stream_events_sends_client_identity_and_caps_timeout`
  - `5 passed in 9.29s`, exit 0.
- `python -B -m pytest -q --tb=short tests/test_t04_root_path_hint_chain.py::test_registered_repo_search_forwards_hints_over_real_root_http`
  - `1 passed in 9.80s`, exit 0; subprocess imported current root source; root HTTP SHA matched above.
- `git diff --check -- src/local_ai_hub/client.py`
  - exit 0.

## Remaining acceptance gap

Candidate `_local_ai_repo_impl` and public `local_ai_repo` do not accept `path_hints`; the `search` branch posts only `root`, `query`, `top_k`, and `enrich`. Therefore `HubClient` path-hint serialization is not reachable through the MCP public API in this candidate. T03 wrapper/T21 integration ownership handoff is required. T21 adapter/runtime evidence also remains absent. Full T04 acceptance is partial until those owners provide current-candidate evidence and root integration receipts.

Shared test-slot ownership was not refreshed for this continuation. Do not schedule more tests until T06 releases the slot.

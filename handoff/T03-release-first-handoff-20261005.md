# T03 release-first handoff — 2026-10-05

## Base and scope

- Candidate worktree: `C:\Users\Adam\.codex\worktrees\e809\.local-ai-hub`
- Candidate base commit: `d68ee694c6d3f75db5c1ab2f63497226880e5010`
- Root checked read-only: `C:\Users\Adam\.local-ai-hub`, HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`; root was not edited.
- Candidate whole-worktree binary diff fingerprint: `F68BB8F0A8862B2182C276F0054C22F9E4F6D7EA5A55274B38EAB32BE89778B7`. This includes unrelated/inherited dirt and is not an adoption patch.

## T03 release packet paths

1. Candidate-owned HTTP search path-hint hunk in `src/local_ai_hub/http_server.py`. Candidate scoped binary diff SHA-256: `7E1E312C8A5DF12B2D7DDDBCF7B8F872056890AE05FDFF659ADBE0EAE77249D8`. Root already has path-hint forwarding and SSE behavior. This old source hunk is stale against root and is not included for integration.
2. New stdio-to-HTTP regression test packet:
   - `handoff/test_t03_stdio_http_proxy.py`, source SHA-256 `01FF52158EC022D75F39A1EE41C8C5E85A167F1C6ED7B325A67F29BF5405B6E8`.
   - `handoff/T03-root-stdio-proxy-20261005.patch`, SHA-256 `DB82AF57D3F26C34E312474BCC9040666B4824E9CA29931731AAC493E3AA8FCA`.
   - Root target: `tests/test_t03_stdio_http_proxy.py` (absent at check time).
3. New multi-process single-spawn-authority regression test packet:
   - `handoff/test_t03_multi_client_single_daemon.py`, source SHA-256 `24F11C7FB015B1846CCA7FC05AF3AD02AE0911DA8C72B85C00445AA3DD235F95`.
   - `handoff/T03-root-multiclient-20261005.patch`, SHA-256 `98E51F7080A28367DF99D8331503801F0A2F727C1126F0B2F470994AB4C7FB22`.
   - Root target: `tests/test_t03_multi_client_single_daemon.py` (absent at check time).

Both test-only patches passed `git apply --check` against root; neither was applied. The test packets do not change source. No `client.py`, `supervisor.py`, `mcp_server.py`, `/api/context/pack`, or `/api/memory/promote` changes are included.

## Root-current test receipts

The root was a dirty checkout; receipts identify its exact revision fingerprint. Commands/results:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_sse_events_stream.py tests/test_api_search_path_hints.py tests/test_mcp_contract_dispatch.py::test_stdio_tools_list_hides_feature_disabled_tools
```

**7 passed in 2.58s**, execution `65e96aac0d50454c9286e29873c436c6`, repository revision `317b54151db08dc4c03934721826d53b611226313283aa39691ed1f28c4028ff`. T20's missing `id=2` report did not reproduce.

```powershell
python -B -c "import sys; sys.path.insert(0, r'C:\Users\Adam\.local-ai-hub\src'); import local_ai_hub.mcp_server; import pytest; raise SystemExit(pytest.main(['-q','-s','-p','no:cacheprovider','--tb=short', r'C:\Users\Adam\.codex\worktrees\e809\.local-ai-hub\handoff\test_t03_stdio_http_proxy.py']))"
```

**1 passed** (one pytest assertion-rewrite warning), execution `b346d1239b1e42e08ba384bbaa1717ff`, revision `6450116574f879bf328c67ca44102899a7fcac6d38200420c79bc95ad0797e31`.

```powershell
python -B -c "import sys; sys.path.insert(0, r'C:\Users\Adam\.local-ai-hub\src'); import local_ai_hub.client, local_ai_hub.supervisor; import pytest; raise SystemExit(pytest.main(['-q','-s','-p','no:cacheprovider','--tb=short', r'C:\Users\Adam\.codex\worktrees\e809\.local-ai-hub\handoff\test_t03_multi_client_single_daemon.py']))"
```

**1 passed in 2.38s**, execution `60eb20ea0c9144c398a078f2e647383e`, revision `7b5f245816604b9751210d73d75f6bd7d77d340577ba623ff63a3094cba77d49`. Measurement: 8 separate HubClient processes issued 8 `service start` requests; the real root `Supervisor.acquire()` yielded exactly 1 spawn authority. The test did not start a Hub daemon.

Native read-only `git apply --check` passed for each test-only packet after `local_ai_command` refused that command because root is not a registered task-owned worktree (`terminal=true`, `retryable=false`).

## Candidate-worktree receipts

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_sse_events_stream.py
```

**31 passed in 2.07s**, execution `437f8a09b71f404c92d46bc16280a72d`.

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t03_http_search_hints.py tests/test_repo_path_hints_search.py
```

**3 passed in 0.26s**, execution `e221f5d0a8634bfb9cb3a9a32d38c075`.

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_mcp_compact_transport.py::test_mcp_stdio_initialize_tools_list_and_call_use_http_proxy
```

**1 passed in 1.82s**, execution `eb9f0e76b11e4afbbcc58c37bb08c976`.

## Other dirty state preserved, outside this release packet

Tracked modified paths:

- `docs/INSTALL_PROMPT.md`
- `docs/UPDATE_PROMPT.md`
- `src/local_ai_hub/async_jobs.py`
- `src/local_ai_hub/client.py`
- `src/local_ai_hub/generator.py`
- `src/local_ai_hub/mcp_server.py`
- `src/local_ai_hub/operation_contracts.py`
- `src/local_ai_hub/services.py`
- `tests/test_features.py`
- `tests/test_mcp_agent_routing.py`
- `tests/test_mcp_compact_transport.py`
- `tests/test_mcp_output_contracts.py`
- `tests/test_mcp_stdio_contract.py`
- `tests/test_operation_contracts.py`
- `tests/test_task_context_task_integration.py`

Other untracked paths outside `handoff/`:

- `.t03-root-overlay/`
- `docs/superpowers/plans/2026-09-30-hub-owned-autostart.md`
- `src/local_ai_hub/inprocess_transport.py`
- `tests/test_async_operational_mode.py`
- `tests/test_hub_startup_coordination.py`
- `tests/test_inprocess_transport.py`
- `tests/test_mcp_operational_mode_dispatch.py`
- `tests/test_repo_path_hints_search.py`
- `tests/test_service_write_set_dispatch.py`
- `tests/test_t03_alias_contract.py`
- `tests/test_t03_http_json_contract.py`
- `tests/test_t03_http_search_hints.py`

These files were preserved and are not part of either root test-only patch. `client.py` is T04-owned; `mcp_server.py` includes T14-owned work; `services.py` remains T21-owned. Other mixed/inherited paths were not reclassified or changed here.

## Release boundary

Functional source paths for HTTP SSE/path-hints and stdio dispatch are present in dirty root and the scoped tests pass. Concurrent process test proves a single supervisor spawn authority, not one actually running Hub process. No live-daemon end-to-end receipt exists; if release requires that proof, it remains the concrete blocker. All T03 packet hunks remain unintegrated, awaiting owner acceptance.

## Live process acceptance attempt — blocked

Test-only probe preserved for diagnosis: `handoff/test_t03_live_mcp_single_daemon.py`, SHA-256 to be recorded in the owner message. No production source changed.

Exact command:

```powershell
$env:PYTHONPATH='src'; python -B -m pytest -q -s -p no:cacheprovider --tb=short handoff/test_t03_live_mcp_single_daemon.py
```

Result: **failed** in 10.42s, execution `9154eed5ec1a48cfb439aced725f78b4`, request `req_08e4e64b3094`, candidate revision fingerprint `78b67baacc00094d3d0c54b0fe666a012a35ff49acde91d2515a5ad95a9b0f42`.

The run did launch independent stdio MCP processes and reached MCP request handling, but the test could not parse responses containing ids 1, 2, and 3 (`assert {1, 2, 3} <= set(by_id)` failed). Cleanup terminated the Hub process; final assertion found stale `state/hub.pid` still present in the ephemeral pytest state directory. A bounded post-run Windows process query found no live `-m local_ai_hub` process with a pytest config path (only the query's own PowerShell process). Therefore no live daemon count receipt was produced. Probe remains an unaccepted diagnostic artifact; do not merge it.

Release blocker: stdio wire response framing/response parsing and graceful temp-state PID-file cleanup need a focused owner repair before this proves eight real MCP clients share exactly one live Hub process and leave no process/state residue. No more process tests run in this pass.

# T03 transport acceptance receipt — 2026-10-03

## Change

In `tests/test_mcp_compact_transport.py`, removed the obsolete no-argument `_build_mcp_client()` assertion that expected an empty tenant. The existing factory test checks tenant/config forwarding; the stdio AST test now checks `CLIENT = _build_mcp_client(TENANT, CONFIG_PATH)`, the builder parameters, and `HubClient(tenant=tenant, config_path=config_path, auto_start=True)`.

The public `local_ai_repo(action="search")` `path_hints` schema, scoped validation, MCP forwarding and `/api/search` service-signature forwarding are present in the current T03 dirty diff. User approved the contract and T21 was notified. This is source status only; it is not end-to-end acceptance.

## Evidence

- `tests/test_mcp_compact_transport.py` SHA-256: `CF8E7C906C27969E70F9FBEC33EF0C2D2B701C5125B0B86A4B1B32E09E8D3636`
- `src/local_ai_hub/operation_contracts.py` SHA-256: `20863DFEDE5AD7E5ABF25D356E2751650568E984E03DCD8A49EB8642122501F0`
- `tests/test_operation_contracts.py` SHA-256: `6BB806742DCE766F13A1601BC638C036E508C56B2D694F26B9186ABDD2E11234`
- `src/local_ai_hub/http_server.py` SHA-256: `BBC2510ED6365CE52DE207869F72C715F16345E7F216AC8050842278A5F2742B`
- Bounded check: `git diff --check -- tests/test_mcp_compact_transport.py` passed, exit 0, command execution `7b79a4a5382b420b9da593ee60618749`.
- Bugbot reviewed the T03 builder-test edit; no actionable bugs found.
- No tests ran. Latest T20 state is **UNKNOWN / no test-slot grant**.

## Acceptance blockers

- e809 `HubClient.post` still has no `path_hints` parameter. T04 owns `client.py`; the approved T04 candidate signature is not integrated here. Calling the T03 MCP search adapter with hints is therefore not transport-verified.
- `tests/test_mcp_repo_path_hints.py` and `tests/test_api_search_path_hints.py` are absent from this worktree, so the route chain has no focused local regression selectors yet.
- Indexed `review_diff` could not review the worktree diff safely: it found 72 segments against a limit of 8. Bugbot reviewed only the requested T03 test edit.
- The mandated `ensure-tools.ps1` path is absent under `C:\Users\Adam\.agents\skills\token-economizer\scripts`; no tools were installed and no PATH was changed.

## Pending serial test selectors

- `tests/test_mcp_compact_transport.py::test_mcp_client_factory_forwards_tenant_and_config`
- `tests/test_mcp_compact_transport.py::test_mcp_stdio_main_starts_proxy_then_runs_without_local_app_stack`
- `tests/test_operation_contracts.py::test_repo_path_hints_schema_is_bounded_and_scoped`

T03 is **partial** until T04 client support is integrated, focused route tests exist, and the authoritative serial test-slot owner grants validation.

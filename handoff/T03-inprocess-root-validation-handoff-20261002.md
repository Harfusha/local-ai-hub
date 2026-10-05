# T03 in-process MCP validation handoff

## Worktree and scope

- Attached T03 worktree: `C:\Users\Adam\.codex\worktrees\e809\.local-ai-hub`, HEAD `d68ee694c6d3f75db5c1ab2f63497226880e5010`.
- This checkpoint changes no source. e809 still lacks `src/local_ai_hub/inprocess_transport.py`, `tests/test_inprocess_transport.py`, and `tests/test_mcp_contract_dispatch.py`; it is not the root integration target.
- e809 current owned/dirty evidence: `mcp_server.py` SHA-256 `BD27FCEE01B75365648CD209A950EE9C18F24FAD3B03048045C5E4B1F4353C5E`, `operation_contracts.py` `80C10F77E786B1D8E8F5CA8FA18405155EADD2B4A1D5AC894D319F8AA1254C58`, `http_server.py` `BBC2510ED6365CE52DE207869F72C715F16345E7F216AC8050842278A5F2742B`. Preserve existing changes and `.t03-root-overlay/` artifacts.
- `/api/context/pack` stays outside this work.

## Root integration static confirmation

- Root target: `C:\Users\Adam\.local-ai-hub`, HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc`.
- Root current SHA-256: `mcp_server.py` `E9DFF220BB273DFFC3CFBCA479008C04489CA017A1216B5F29FFC0B04901B3AA`; `client.py` `0C3690E24499DEC22A4EC1295BAEA06FF52E54880021E7A432A4BD733D15BC1D`; `inprocess_transport.py` `4820102BE7AB5BF2E4F2C2F47CC45A500DA65F679FFCB67B7EB122D25C703982`; `tests/test_mcp_contract_dispatch.py` `1608DCFB5A57B0A4F5AE8CDDB80B2576D0A54A7D2FFE84035989041A344343D0`.
- Refreshed preflight 2026-10-02: root HEAD unchanged; current `tests/test_inprocess_transport.py` SHA-256 `F9E06F92FC3406E46AFD1122C41656C7102001806636AE587F3D8EDC81A8903A`. AST-only presence check found all ten selectors below (6 MCP contract, 4 transport). No tests executed.
- Static call-path: MCP `CLIENT` injects `InProcessTransport`; reporter uses that same `CLIENT` for `/api/telemetry/tool-accounting` with `("telemetry", False)`; `HubClient._open()` chooses injected transport; transport calls `Handler.do_POST()` via in-memory streams. T04 confirmed hashes and agreed prior accounting HTTP gap is closed. No source change needed from this T03 checkout.
- Checkpoint detailing the accounting seam and T04 review: `handoff/T03-mcp-inprocess-continuation-20261002.receipt.md`, SHA-256 `75661271DDFECBBB0F399323C4A2EA9A5CB4D740A55E55B505B258D66C5BC437` at last recorded update.

## Exact root test handoff

Run only in the root target after T20 grants the serial slot and pins pre-run hashes. No tests were run during this checkpoint.

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short `
  tests/test_mcp_contract_dispatch.py::test_mcp_transport_selection_injects_lazy_transport_with_same_config_and_tenant `
  tests/test_mcp_contract_dispatch.py::test_mcp_transport_metadata_keeps_deterministic_reads_light `
  tests/test_mcp_contract_dispatch.py::test_mcp_client_adapter_forwards_semantic_metadata_to_hub_client_request `
  tests/test_mcp_contract_dispatch.py::test_instrumented_mcp_action_reaches_inprocess_client_with_classified_metadata `
  tests/test_mcp_contract_dispatch.py::test_protocol_accounting_uses_shared_mcp_client_as_light_telemetry `
  tests/test_mcp_contract_dispatch.py::test_mcp_command_run_is_gated_as_heavy_and_repo_map_read_stays_lightweight `
  tests/test_inprocess_transport.py::test_inprocess_transport_routes_to_services_without_http_or_spawn `
  tests/test_inprocess_transport.py::test_inprocess_transport_lazily_creates_app_without_http_or_process `
  tests/test_inprocess_transport.py::test_inprocess_transport_preserves_auth_and_payload_validation `
  tests/test_inprocess_transport.py::test_inprocess_transport_keeps_deterministic_read_allowed_in_restricted_mode `
  tests/test_mcp_contract_dispatch.py::test_mcp_command_run_is_gated_as_heavy_and_repo_map_read_stays_lightweight
```

These selectors cover MCP transport injection/classification/accounting, no-HTTP/no-process service routing, auth/payload validation, lightweight deterministic reads, and heavy action gating. They do not prove every eight-tool action or full release acceptance.

## Blocker

- T20 owns serial queue. Latest queue from T20: T13 slot 09, T19 slot 10, T11 slot 11, T05 slot 12, T03 slot 13. Wait for explicit slot 13 assignment before running anything.
- e809 cannot run the root selectors as a candidate suite: it lacks the root-only test module and T04 transport files. Root postimage integration and runtime evidence remain T20-owned.

# T03 end-to-end MCP acceptance checkpoint

## State

- Objective remains open: prove MCP dispatch works without Hub HTTP/daemon and preserves tenant, auth, request ID, payload validation, and operational-mode policy.
- T03's earlier root-current wiring patch was integrated by T20. Root `mcp_server.py` and `test_mcp_contract_dispatch.py` hashes equal that patch's proposed postimages: `4F6CF5F40FE3E49D563042029831A3D00FFE503F5F428C64D7867B22772F9EB8` and `C30B0309F5DC97A27A4E86CDEB477299E43950AADAFAD479FD2992DA8BE218EA`.
- A T04 read-only review found the background metadata accounting reporter still created a separate `HubClient(auto_start=False)` and attempted HTTP. Decision: include this telemetry path in daemon-off acceptance; it is part of every instrumented MCP call, even though failures are swallowed.
- T04 reviewed the telemetry overlay read-only and reported no static findings: `_send` sets `("telemetry", False)`, uses shared `CLIENT`, resets the context token in `finally`; regression forbids a new `HubClient` and checks policy/payload.

## Follow-up patch

- Reuse shared MCP `CLIENT` for `/api/telemetry/tool-accounting`; set context explicitly to `("telemetry", False)` because accounting runs on its own worker thread. Keep bounded timeout, queue, batch ID, best-effort failure handling, and batch behavior.
- New regression verifies reporter reuses shared client, passes lightweight telemetry policy, and never constructs a second `HubClient`.
- Root-current patch: `handoff/T03-mcp-inprocess-accounting-root-current.patch`.
- Patch SHA-256: `D2E351EE290822990105CD583AC3966CF3110C3D06BE692B60645E67CEF75673`.
- Target root: `C:\Users\Adam\.local-ai-hub`, HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc`.
- `git apply --check --whitespace=nowarn` passed against current root. Patch has only `mcp_server.py` and `test_mcp_contract_dispatch.py`; it does not mention `/api/context/pack`. Patch was not applied.
- Current preimage SHA-256 -> proposed postimage SHA-256:
  - `src/local_ai_hub/mcp_server.py`: `4F6CF5F40FE3E49D563042029831A3D00FFE503F5F428C64D7867B22772F9EB8` -> `E9DFF220BB273DFFC3CFBCA479008C04489CA017A1216B5F29FFC0B04901B3AA`.
  - `tests/test_mcp_contract_dispatch.py`: `C30B0309F5DC97A27A4E86CDEB477299E43950AADAFAD479FD2992DA8BE218EA` -> `1608DCFB5A57B0A4F5AE8CDDB80B2576D0A54A7D2FFE84035989041A344343D0`.

## Blocker and next step

- No tests or benchmarks run. T02 owns the only serial test/benchmark slot.
- After T02 explicitly releases the slot, T20 can apply this follow-up only if both preimage hashes still match, then run the combined T03/T04 daemon-off MCP test proving service dispatch, telemetry, no HTTP connection, and no child process. Preserve root ownership and release the slot to the next queued task afterward.
- No root files were written by T03. End-to-end acceptance remains open until that combined root validation passes.

## Current root call-path recheck

- Current root `mcp_server.py` SHA-256 is `E9DFF220BB273DFFC3CFBCA479008C04489CA017A1216B5F29FFC0B04901B3AA`; this equals follow-up telemetry patch postimage. `client.py` SHA-256 is `0C3690E24499DEC22A4EC1295BAEA06FF52E54880021E7A432A4BD733D15BC1D`; `inprocess_transport.py` SHA-256 is `4820102BE7AB5BF2E4F2C2F47CC45A500DA65F679FFCB67B7EB122D25C703982`.
- Confirmed reporter path: `_ProtocolAccountingReporter._send` sets `("telemetry", False)`, calls shared `CLIENT.post`, then resets context in `finally`. MCP `CLIENT` is built with `InProcessTransport` because module exists in root. `_MCPHubClientAdapter` wraps `HubClient.request`; `HubClient.post()` invokes it with action metadata. `HubClient._open()` calls `InProcessTransport.open()` when injected; transport dispatches existing `Handler.do_POST()` through in-memory streams.
- No separate accounting `HubClient` remains. `HubClient._open()` uses `_inprocess_transport.open()` when injected (`client.py:233-240`); `InProcessTransport` invokes `Handler.do_POST()` through in-memory streams (`inprocess_transport.py:209-211`). The client exception branch also retries request-not-sent through the same injected transport instead of `ensure_server()` (`client.py:594-604`). Thus accounting does not open HTTP or start the Hub process while this transport is present.
- No tests run. T02 still owns serial test/benchmark slot. T04's possible HTTP accounting leak is resolved in current root source; combined daemon-off runtime acceptance remains unverified until slot clears.
- T04 confirmed the current root postimage hashes and agreed the accounting HTTP gap is closed. Only serial runtime validation remains pending T02's slot release.

# T03 proxy and transport handoff

## Candidate

- Worktree: `C:\Users\Adam\.codex\worktrees\e809\.local-ai-hub`
- HEAD: `d68ee694c6d3f75db5c1ab2f63497226880e5010`
- Patch: `handoff/T03-proxy-http-transport-20261002.patch`
- Patch SHA-256: `700A4D11A870A247922999FF3F8CDEC283873B43C53A6D3C3201BA647FCB2FC0`
- Paths: `src/local_ai_hub/mcp_server.py`, `tests/test_mcp_compact_transport.py`; 147 insertions, 1 deletion.
- Candidate source hashes: `mcp_server.py` `D3526099FF319F0E2A2221AB2897E57F80A76C9DAC751A3B180DC476C56255B1`; test file `AF67BFD4FEF1F08CC2B42367DF3D4EA1E1C4D2B0DC7F80AE736C0E99BBF50BBE`.
- The patch was copied byte-for-byte from the isolated proxy patch. `git apply --check` passed against a clean archive of the recorded e809 HEAD (exit 0). It was not applied to root.

## Contract and ownership

- T13's server-side mode gate remains authoritative. Proxy does not send client-selected `operational_action` or `requires_heavy_work` fields.
- T13 requires root-scoped requests to omit generated `X-LocalAI-Tenant=agent-{pid}` or use configured principal only as consistency hint. Current e809 `client.py` fills empty tenant with `agent-{pid}` and sends that header. This remains an unresolved root-scoped MCP contract seam. T04's current owned scope is bounded HubClient autostart/singleton readiness/recovery; its usable checkout is unavailable and owner forbids client/root edits or tests until T20 GO. T03 did not edit `client.py`.
- T21 received the `path_hints` contract handoff and confirmed no mismatch. Candidate: `handoff/T03-root-path-hints.patch`, SHA-256 `44ED6619E8B16ABF882E0F8FBF836DC2231A645258CD8D8BB0F71CE7C7908A00`. T03 does not edit T21's service adapter.
- Output schemas remain deferred until complete status-action contracts are available.

## Validation gate and pins

- No tests run in this checkpoint. Latest T20 receipt (2026-10-03) denies slots to T03/T04/T08; T05 remains active test blocker. T20 has not issued T03 serial GO.
- T20 matrix observed at `C:\Users\Adam\.codex\worktrees\t20-release-acceptance-recovery\.local-ai-hub\docs\superpowers\plans\T20-release-acceptance-matrix-20261002.md`, SHA-256 `334AE986618E77AF405CE1D93D6A991ECA07F81BD687A0BF1437B08947016591`.
- That matrix records an earlier T03 receipt of 6 proxy tests passed in 2.47s and truncated pins `DA0DF36C…E09797` / `81EE0470…D2C2E6`. These do not match this e809 candidate's pins above; T20 should reconcile before integration or acceptance.
- Prior e809 history reported 7 scoped selectors passed in 9.43s. This is historical, not a fresh T20-slot receipt; do not treat it as current root acceptance.
- Selector-count reconciliation: the earlier six-selector run predates `test_mcp_stdio_initialize_tools_list_and_call_use_http_proxy`; the later seven-selector run included that new initialize/list/call protocol selector plus four root/task-scope selectors. Counts refer to different test sets, not a missing/failed test. Matrix pins still refer to the earlier e809 revision; current e809 dirty-file pins are listed above. Neither receipt is a root integration receipt.
- Root-current snapshot checked read-only: HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc`; `operation_contracts.py` SHA-256 `1CB6942E888506897F4C994062654D08524D546CE93A12707EE1C08D99A783BB`; `mcp_server.py` `16E64C3EBDF0C23B5AF133E44DE76AD2898AC290E78C4A23521B19C9217297E0`; `client.py` `75B07C21735B881ED58C03BFC80B450410C3778C248D662A7C8E675549180D4F`; `tests/test_operation_contracts.py` `6F15CBF4E045B6D5D6A316CD27636090661270142376AA13C97A8A85B24DD3F1`; `tests/test_mcp_compact_transport.py` `53F3DEAA1AD26EFD8BE6F32A9AEB7A69D8116EFEFE0FFDF81790931ABD885C03`.
- The four root patch apply-check failures were against the 2026-10-02 dirty root snapshot only; they are not a current root migration verdict. User-provided 2026-10-03 evidence corrects earlier topology: current root `mcp_server.py` uses `_build_mcp_client(HubClient)` and stdio proxy around line 3162. The reported 54 `mcp_server` processes are adapters, not 54 daemons/full `HubServices` stacks. One supervisor plus HTTP parent PID 150832 and child 123204 form one logical HTTP instance. T03 did not modify root.
- Historical 2026-10-02 path-hints snapshot showed root `operation_contracts.py:193` scoping `path_hints` to `search` and `context`; its schema/test allowed context use only for `adaptive`. Candidate e809's contract patch is search-only. Keep T21's adaptive-context extension intact; do not transplant T03 contract hunks wholesale. T03 announced its search contract to T21; current root contract should be reconciled by its owner, not inferred from old preimages.

## 2026-10-03 T03 follow-up

- User corrected root topology: root `mcp_server.py` already uses `_build_mcp_client(HubClient)` and stdio proxy near line 3162. Snapshot reported 54 stdio adapter processes; HTTP parent PID 150832 and child PID 123204 are one logical supervised HTTP service under supervisor PID 231460. This is not evidence of 54 `HubServices` instances. No root reads/writes/tests performed for this follow-up.
- e809 static AST audit passed (no runtime `HubServices`, `LocalAIApp`, `LocalAIServices`, `RAGStore`, `EmbeddingIndex`, `InProcessTransport`, or full-stack imports in `mcp_server.py` and `client.py`; exactly one `HubClient(auto_start=True)`; `main()` calls bounded `ensure_server()` before stdio). A separate lazy `_ProtocolAccountingReporter` client uses `auto_start=False`; no second auto-start path.
- MCP protocol regression at `tests/test_mcp_compact_transport.py:151-183` performs initialize/list/call against a mocked HTTP client. It asserts exact eight advertised tools, no HTTP request for `tools/list`, and one status request for `tools/call`. Historical seven-selector candidate receipt includes this test; not rerun under current T20 gate.
- Search hints are already present in e809: `_local_ai_repo_impl` accepts `path_hints`, normalizes them within root, and forwards them only to `/api/search`; public `local_ai_repo` rejects the field outside `action="search"`. Historical focused path-hints receipt: 9 passed in 2.87s; no rerun. T04 was given exact signatures, selector/file pins, and advised to reuse this wrapper.
- T04 clarified it owns HubClient startup/readiness/recovery only; its usable checkout is unavailable and it will not edit `client.py`, root, or run tests before T20 GO. T03 should keep one HubClient auto-start owner and avoid transport-specific process spawning. Current T20 receipt denies T03/T04/T08 test slots; T05 remains blocker.
- After T20 GO and T04 client handoff, run the three proxy selectors:

```powershell
$env:PYTHONPATH='src'; python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_mcp_compact_transport.py::test_mcp_client_builder_uses_http_proxy_without_client_tenant tests/test_mcp_compact_transport.py::test_mcp_stdio_main_starts_proxy_then_runs_without_local_app_stack tests/test_mcp_compact_transport.py::test_mcp_stdio_initialize_tools_list_and_call_use_http_proxy
```


# T03 MCP in-process root-current patch receipt

## Scope and evidence

- Target root: `C:\Users\Adam\.local-ai-hub`.
- Target HEAD observed: `01df56605ccf484ebfe2808ac60d696c4e81dffc`.
- Prepared patch: `handoff/T03-mcp-inprocess-root-current.patch`.
- Patch SHA-256: `11F743B9D5FEAC71E02312619A85FDACDF5A29DBCED4E83BDA6086E33E8B6A90`; 14,021 bytes.
- Patch includes exactly `src/local_ai_hub/mcp_server.py` and `tests/test_mcp_contract_dispatch.py`.
- Patch does not mention or modify `/api/context/pack`.
- Read-only `git apply --check --whitespace=nowarn` against the target root passed. No patch was applied; root hashes stayed at their preimage values.

## Root preimage and proposed postimage SHA-256

| Path | Current root preimage | Proposed postimage |
|---|---|---|
| `src/local_ai_hub/mcp_server.py` | `2A78162B9B5157076ECF3281968369501EF38E451BB8AA01CE9E6FFE9A49C577` | `4F6CF5F40FE3E49D563042029831A3D00FFE503F5F428C64D7867B22772F9EB8` |
| `tests/test_mcp_contract_dispatch.py` | `C555C2D8205EF9537EBED997D1510A31617EEFB208B4B07F28CA4B2C13187352` | `C30B0309F5DC97A27A4E86CDEB477299E43950AADAFAD479FD2992DA8BE218EA` |

## Included changes

- Inject T04 `InProcessTransport` into MCP-owned `HubClient` with identical `TENANT` and `LOCAL_AI_CONFIG`; keep legacy HTTP client construction if T04 module is absent.
- Forward classified action and heavy-work metadata through POST/request, GET, and status calls. Preserve `HubClient.post()` payload normalization and retry-safety behavior. Close MCP client at exit.
- Classify repo `map`/`code_index`, artifact actions, and status `brief`/`cache`/`telemetry` as light; `search` and status `agent_state` as heavy. Keep operational-mode gate before MCP route dispatch.
- Add four focused tests for transport injection, light/heavy classification, request/GET metadata forwarding, and instrumented dispatch metadata.

## Validation boundary

- No tests run, per T20 queue instruction.
- The root-current patch applies cleanly under `git apply --check`; this proves patch applicability only.
- Root source/test hashes remained identical after patch check. No root writes were issued.

# T14 test-only root-current packet — 2026-10-04

## Scope and diagnosis

Root source `mcp_server.py` remains at SHA-256 `04FF58CA3F82E1A8271D499585DE5F99F5A28986B4650DD0E0CCC5DBDE659B0F`; no production change is included.

The MCP context path issues one `/api/context/pack` request. Instrumentation separately queues accounting, whose background reporter may POST `/api/telemetry/tool-accounting` through the same client. The test must count only `/api/context/pack`; telemetry POSTs are independent. This packet changes that assertion only.

## Preimage and postimage

- Root HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
- Root test preimage SHA-256: `6AE1494740BDEFB8CA3CA7032ED2494E7FB9140C95C031466395379D4BD16B51` (125 CRLF lines).
- Projected root test postimage SHA-256: `102E788121141C4F7AF8C3360AEC314A4D4EF755A88ABEF4FFABEEB099182D9E` (126 CRLF lines; generated in a scratch copy).
- Candidate test SHA-256: `DADBCAC34614189AECA2D536289339EB0DEE48F8D49EA55326A4A2D901B9EF3B` (LF working copy; normalized content matches projected postimage).
- Packet SHA-256: `980F077E2D6D0F618014377AA570B25269C164AFE6831FA8068A09C58D714AF6`.

## Validation

- Root-current `git apply --check`: `ROOT_CURRENT_APPLY_CHECK_PASS`.
- Candidate E2E: `2 passed in 4.15s`.
- Corrected candidate focused batch: `24 passed in 7.84s`.
- Candidate `git diff --check`: exit 0; only existing LF-to-CRLF notices.
- Root was not modified or tested.

## Packet

`T14-root-current-test-only-20261004.patch` — test assertion only; apply only against the preimage SHA above.

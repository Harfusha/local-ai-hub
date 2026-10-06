# T04 root-current pre-run inventory — 2026-10-02

State: READY / NOT RUN. This receipt records read-only verification only. No root files changed and no tests, imports, builds, or benchmarks were run.

## Revisions

- Root: `C:\Users\Adam\.local-ai-hub`, HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc`.
- T04 worktree: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`, HEAD `3658d5056354849ddf17883ed04f807f16cc44c1`.

## Root-current owned paths and SHA-256

- `src/local_ai_hub/client.py`: `0C3690E24499DEC22A4EC1295BAEA06FF52E54880021E7A432A4BD733D15BC1D`.
- `src/local_ai_hub/inprocess_transport.py`: `4820102BE7AB5BF2E4F2C2F47CC45A500DA65F679FFCB67B7EB122D25C703982`.
- `tests/test_inprocess_transport.py`: `D458FD0608CFC86A75FB984EA3C87A40E0A6A9CFE7651276369C5FAE9A213A1A`.
- `tests/test_client_transport.py`: `03000F1016075FC4B4025F9185CFFB471043663028F04496B0CD4F42D5EA06A0`.

T04 worktree source hashes differ where root-current patch was adapted to the divergent root client. New transport and in-process test normalize byte-for-byte from T04 LF to root CRLF.

## Static acceptance review

- `HubClient._open` dispatches to injected `InProcessTransport.open`.
- MCP construction injects the transport; action metadata reaches client calls.
- Adapter reuses the existing `Handler.do_GET/do_POST` with in-memory streams and existing authorization, schema, tenant, rate-limit, and service routing.
- Accounting reporter now uses shared MCP client under `("telemetry", False)`; T03 static review confirms no second HTTP client on this path.
- Test inventory: 9 in-process transport tests and 28 client transport tests. Critical transport tests cover no HTTP/process spawn, lazy real app creation, identity/cancel route, persistent rate limit, auth/payload validation, restricted-mode gate/read, timeout after dispatch and timeout before admission. Run both named files as authorized; this preserves client regression coverage.

## Exact validation after slot release

1. Import assertion only:
   `python -B -c "from local_ai_hub.client import HubClient; from local_ai_hub.inprocess_transport import InProcessTransport; assert HubClient and InProcessTransport"`
2. Focused root tests only:
   `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_inprocess_transport.py tests/test_client_transport.py`

Expected selector count: 37. No other tests, benchmarks, or builds are authorized in this receipt.

## Slot and blockers

- T07 currently owns serial slot 06.
- T04 is queued for slot 07, which T20 must explicitly allocate after T07 releases slot 06.
- Do not run step 1 or 2 before T20's explicit slot-07 release. Release slot immediately after both finish.
- Root T04 hunks are already integrated; no T04 root edit is planned.

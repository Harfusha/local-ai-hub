# T18 root-current acceptance addendum — 2026-10-02 v3

This addendum corrects the mode-route statements in `T18-root-current-acceptance-20261002-v2.md`. The earlier missing-mode-API conclusion is superseded by `T18-root-mode-route-review-20261002-v1.md` and checkpoint v4. The v2 48-pass receipt remains historical evidence for its recorded source pins; no tests ran during this update.

## Current root source evidence

At 2026-10-02 06:26 UTC, root remained HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc`. Current SHA-256 pins match the reviewed sources:

- `src/local_ai_hub/http_server.py`: `8443F8E178C717C92C063394C585C8C38721BD18F644DB053DB6EF81A5F0E047`
- `src/local_ai_hub/telemetry.py`: `59A8F461CCF11C09526624EDEBD4D4FD99FB314935BE893BBFCE052CAF09281B`
- `src/local_ai_hub/dashboard.py`: `9FC006FD0F5A3E3EBE2CFA0DA79F8786DFD4CB7BE1AB2CD6599CF7363C51A760`

Root `http_server.py` includes `/api/mode` and `/api/admin/mode` action classification, the loopback GET authorization exception, the persisted-mode GET handler, and the mode-update POST handler. No T13 production-source transplant is indicated. The previous candidate selector's 22 failures came from its absent `_operational_mode_api` injection seam; they do not show missing root routes.

## Original T18 candidate pins

Verified worktree: `C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub`, HEAD `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`.

- `src/local_ai_hub/http_server.py`: `771D62EA4C5809255E985F40CF46E59A8093AF2F5381813E49A1C74BDFAA93F0`
- `src/local_ai_hub/telemetry.py`: `B58636B4FDD994279C5BA2659A80FCF87D4C7233AF3D7337FB7CCB1685D5E338`
- `src/local_ai_hub/dashboard.py`: `91AAAD7FD3D881EA6EEE428AABA38F9DCDFB1E32DF10430F629075AD57C21705`

These are whole-file pins for mixed-owner dirty files. They identify current bytes; they do not assign ownership of every hunk.
## Acceptance still required

The 48-pass root receipt in v2 covers its listed telemetry, privacy, admin-auth, status, and dashboard selectors. The 42-pass candidate receipt in checkpoint v4 is candidate-only. Neither receipt establishes full release acceptance.

The root-current overlay does not stub `_require_authorized`; it runs root HTTP handlers with `security.api_token` empty and makes one loopback GET. It proves that empty-token case, not configured-token behavior or remote denial. This corrects the overlay description in checkpoint v4 and route-review v1. Remaining gap: add a pinned root-current regression proving configured-token loopback GET `/api/mode` succeeds while the same unauthenticated request with a non-loopback client address gets 401. Run it only after T02 explicitly releases the single test slot.

## External root-current handoffs

- T20 T19 prompt receipt: `C:\Users\Adam\.local-ai-hub\artifacts\handoff\T20-t19-prompts-root-current-receipt-20261002.json`, SHA-256 `D529F138C0D33AE82180738571A7CD276CF09B09668C9AA20C3616C9D70EDFBE`.
- T20 T03 accounting receipt: `C:\Users\Adam\.local-ai-hub\artifacts\handoff\T20-t03-accounting-root-integration-receipt-20261002.json`, SHA-256 `277E80F2C1B84F62925B4D858DF58D8CF684BDF5926B5D1CC406E15A1A866813`.
- T08 checkpoint r4: `C:\Users\Adam\.codex\worktrees\t08-agent-os\.local-ai-hub\artifacts\t08-end-to-end-acceptance-checkpoint-20261002-r4.json`, SHA-256 `0437D2DBE9446194583A93375BF5198D9AD8EC244FC56DE64385708D7794914C`. It proves 21 paths and 16 selectors exist; no runtime acceptance.

## Live coordination state

A bounded snapshot at 2026-10-02 06:42 UTC showed T02 active on its baseline measurement without a completed case or release; the exclusive test slot remains occupied. T20 is active applying test-first review to T14 MCP budget/accounting overlap with T03 telemetry; tests stay deferred. Its latest completed release report leaves T01 regression and T21 integration open, while T19 full-suite acceptance is also unverified. T13 is idle after candidate-only async-job schema correction; root/candidate blocks match and AST parsing passed, but no T13 root mode-route receipt exists. No tests or benchmarks ran. This update changed no root files. Local AI Hub was omitted per user instruction.

T20 still owns overall release acceptance. Do not report full release acceptance until T20 integration and required root-current receipts are verified.

## Prepared root-current auth regression

Existing overlay uses root `Handler` over HTTP and exercises `_require_authorized`; its configured global `api_token` is empty while `action_tokens` contains `mode.control`. Close the remaining gap by setting a nonempty global token in that fixture while preserving the scoped mode token. Keep the real loopback GET `/api/mode` assertion. Add a root-pinned `Handler.__new__` case with `command="GET"`, `path="/api/mode"`, empty request token, configured global token, and `client_address=("203.0.113.7", 23456)`; assert `_require_authorized()` returns false and sends 401. Reuse fixture telemetry for the authorization audit and keep host/origin and tenant guards valid. This proves the actual root authorization method for loopback override versus non-loopback denial without candidate-only seams.

Do not edit or run this regression until T02 releases the exclusive test slot. No test source changed for this design note.

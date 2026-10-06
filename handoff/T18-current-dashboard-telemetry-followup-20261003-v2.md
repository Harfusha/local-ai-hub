# T18 dashboard and telemetry follow-up — 2026-10-03

## Ownership and current state

- T18 candidate: `C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub`, HEAD `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`.
- Root examined read-only: `C:\Users\Adam\.local-ai-hub`, HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
- Hub tools skipped per user. No root edits. T13 mode HTTP handlers and T14 `/api/context/pack` untouched.
- T02 serial lease `lease_fc36c8e2e311` remains unreleased/unverified. No T18 test GO. No pytest run in this continuation.

## Root-current patches prepared

Both patches target current root preimages and pass `git apply --check --ignore-space-change --whitespace=nowarn`. Neither is applied.

| Patch | SHA-256 | Root preimage SHA-256 | Delta |
|---|---|---|---|
| `T18-root-current-mode-dashboard-pending-unload-20261003-v1.patch` | `BD4C294E0B6A20E1D0C8F9097F007927CEC2F15D53E2B254853664A3005B4F88` | `src/local_ai_hub/dashboard.py` `6212C9D58EF6E3315A048DFF501D1B33B425E554CD96893932C3EAEE18516FE7` | 5 insertions, 2 deletions: show VRAM unload state and retry `/api/mode` at 1.5 s intervals, capped at 8; retry once after accepted gaming transition reports pending unload. Client UI only; no route body edits. |
| `T18-root-current-telemetry-error-redaction-fixtures-20261003-v1.patch` | `37DB2BF616FD64062F2EFE7F9DFB2FEA9FA0E4C0B54EE023A34571FE7ABA5A12` | `tests/test_telemetry_error_diagnostics_t18.py` `325323CD2FFA5F2C34DDC3D54D5BEFFF2A032BBC988291F0E9719128E379D0AD` | 3 insertions, 1 deletion: add path/token sentinels to `FileNotFoundError` and `PermissionError` without errno; assert token absent from persisted diagnostics. Test only. |

Existing integrated T18 degraded-polling, status-fixture and telemetry-cursor patches remain in root; their reverse checks passed in the prior receipt `T18-end-to-end-current-root-20261003-v1.md`.

## Candidate pins for bounded validation

- `src/local_ai_hub/dashboard.py` `88C50B4E2DD4B9EA6F1B526773C750DF37707C1FC288D00C958DCA36AA808A2B`
- `src/local_ai_hub/telemetry.py` `B58636B4FDD994279C5BA2659A80FCF87D4C7233AF3D7337FB7CCB1685D5E338`
- `tests/test_dashboard_mode_playwright_t18.py` `6A5C513A00B32A9E3F475B4421A93BD37D3864875C823BFAF3235052E1AAE257`
- `tests/test_dashboard_polling_quality.py` `57E87561F9D04E0153027EE10FEC886B2FB46CB7CC14171B96EC85D417D85835`
- `tests/test_telemetry_error_diagnostics_t18.py` `B0303169B5AE7728B4A444B724F7F3BDA0A2EACCE1B681DDAE4884C82DE1BCC2`
- `tests/test_telemetry_report_bounds_t18.py` `AA0D1D9C563A590B3401BBDB136EF2F12A02A54879008560430C0B15AC0D07E2`
- `tests/test_status_snapshot_quality.py` `A52903B3BD50B8A73871977C4C8E81D1F0A63D43FC2F88FD66C13918AC6D3172`

## Bounded test command and receipt

Run only after T02 releases the serial lease and T20 assigns T18:

```powershell
python -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short tests/test_dashboard_mode_playwright_t18.py::test_dashboard_mode_dom_auth_and_error_projection tests/test_dashboard_polling_quality.py tests/test_status_snapshot_quality.py tests/test_telemetry_error_diagnostics_t18.py tests/test_telemetry_report_bounds_t18.py::test_report_budget_truncation_advances_cursor_after_retained_rows
```

**Output this continuation:** NOT RUN — serial lease remains unreleased. Do not count patch preflight as test acceptance. Historical candidate receipts (24 status/polling passes; 65 dashboard/admin/telemetry passes) use earlier pins and do not verify these current root preimages.

The Playwright fixture exercises a stub loopback service. Live `/dashboard`, real backend recovery, and admin authorization remain separate runtime acceptance gates.

# T18 ownership map and minimal root handoff (2026-10-01 v1)

## Boundary

Candidate: `C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub`, detached HEAD `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`.
Root target: `C:\Users\Adam\.local-ai-hub`, HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`. Root was read-only for T18. HUB was skipped as instructed.

The candidate has mixed, dirty work from several owners. This handoff contains only proven T18-owned tests absent from current root. It contains no production source changes. No broad candidate file diff is safe to transfer.

## Ownership decisions

| Scope | Current finding | Handoff action |
|---|---|---|
| `TelemetryStore._safe_error_message` and SQLite/diagnostic coverage | T18 ownership recorded in `T18-status-dashboard-telemetry-acceptance-20261001-v4.md`. Root already has the classification behavior and both owned test bodies. Root preserves extra errno-specific `OSError` cases that candidate version lacks. | No source or test delta. Do not transplant candidate telemetry function. |
| Telemetry metadata redaction (`_safe_metadata`, extra path tests) | Candidate-only changes; explicit T18 ownership not established. | Excluded pending provenance. |
| Telemetry report cursor/store paging | Candidate function/test bodies match current root; route cursor forwarding was integrated by T20. | No delta. |
| Agent-event paging | Candidate source is older and lacks root `through_seq` bound. Root source and test bodies already cover it. | No delta; do not transplant candidate source. |
| `DebugTraceStore` retention | T18 source patch is already integrated. `test_trace_retention_days_override_terminal_ttl_and_are_reported` is present in current root `tests/test_debug_traces.py`. | No delta. |
| Dashboard activity-transition display and failure regression | T18 display patch is reported integrated by T20; root has matching transition test. | No delta. |
| HTTP agent-state diagnostics | Root has `agent_state_enabled` behavior and matching test body. | No delta. |
| Admin action authorization | Behavior and test counterpart exist in root; earlier ownership/review receipt was pending and integration attribution is not established. | Excluded; no duplicate patch. |
| Dashboard poller module extraction | Candidate adds `dashboard_status_poller.py`; root has equivalent inline poller. Ownership is unproven; extraction creates no identified behavior gap. | Excluded. |
| Operational-mode source / `tools/hubctl.py` | Mode production belongs to T13; candidate route is stale against current API. CLI source attribution is uncertain. | Excluded. |
| Realtime status SQLite error summary regression | T18 synthetic privacy assertion is absent from root; root `app.py` already surfaces the SQLite summary. | Included as one function-only test hunk. |
| Current-root mode overlay and real dashboard DOM evidence | T18 receipts identify these candidate test fixtures; production mode behavior belongs to other owners. All four files are absent from root. | Included as test-only files. |

## Patch

`T18-owned-current-root-tests-20261001-v1.patch`

SHA-256: `941263DD08C157BA88CEC7C9165A259911FAFFD8E95BA1D80BEBF825ADAB8BB2`

It adds only:

- One 27-line regression test in `tests/test_status_snapshot_quality.py`.
- `tests/test_root_current_mode_overlay_t18.py`.
- `tests/test_dashboard_mode_playwright_t18.py`.
- `tests/fixtures/dashboard_mode_playwright_t18.cjs`.

Preimage for existing target `tests/test_status_snapshot_quality.py`:

- Current root SHA-256: `1A08CC0F690FF70D4A3D78F9C2A122965CC4FBCD2063544090627B4A4C4CF0C8`.
- Candidate SHA-256: `00EC4D2ABD65ABBF07EBF4981D41C2B0893F5FAB9A67CFF005F0CB39B1EF5DE7`; only the named function is exported.

New-file candidate SHA-256 pins:

- `tests/test_root_current_mode_overlay_t18.py`: `42C9EAE05F83B466D5B98C3B90300FB2F40D63EB2EFEB04209B48ECA678731A3`.
- `tests/test_dashboard_mode_playwright_t18.py`: `6A5C513A00B32A9E3F475B4421A93BD37D3864875C823BFAF3235052E1AAE257`.
- `tests/fixtures/dashboard_mode_playwright_t18.cjs`: `35BDBB553FEEC9DC7849379F78DA4DC720EC4D5441BFE19D8F49D8B9DC8B7799`.

Root source pins at apply-check:

- `src/local_ai_hub/http_server.py`: `BDB4ECF50C149FCB144F3745EC9AB58FCE029F900A6ED83A41C5FAF1D2C9BECB`.
- `src/local_ai_hub/dashboard.py`: `9FC006FD0F5A3E3EBE2CFA0DA79F8786DFD4CB7BE1AB2CD6599CF7363C51A760`.
- `src/local_ai_hub/app.py`: `2B6E826FEF08863EF9BF1528E402F7DE041A6A2B08A3812E8454398BC1750546`.
- `src/local_ai_hub/telemetry.py`: `191DC35FEC06D804261D14BDA91837FBD088FEE82FE8B6A8BB6D266AAE2E10E5`.
- `src/local_ai_hub/agent_events.py`: `30AB4485F34A67D8212E6151057E06EF806D40F92073036D8F9F4F4546B44822`.

## Verification receipts

- `git -C C:\Users\Adam\.local-ai-hub apply --check <patch>`: exit 0 against the root worktree state at handoff creation. No root files were changed.
- `git apply --stat`: four paths, 509 insertions.
- Earlier candidate status/dashboard/admin/telemetry selector: 65 passed.
- Earlier root-pinned mode/UI/SQLite/realtime selector: 11 passed.
- Earlier root-pinned telemetry batch: 28 passed, 1 failed. Only failure was asynchronous `TelemetryStore.flush(1)` in `test_error_telemetry_persists_classification_without_exception_text`, before privacy assertions. Same test passed alone: 1 passed. Keep these results distinct; no blanket clean-suite claim.
- Earlier T20 route-cursor selector: 1 passed. Earlier isolated root telemetry store/DB/route selector: 3 passed.

Patch apply-check validates applicability only. The test-only patch has not been applied to root or run there. T20 owns root integration and final root-suite evidence.

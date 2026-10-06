# T18 remaining telemetry and bounded-inspection receipts

Date: 2026-10-01. Root HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`; candidate HEAD `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`. No root files written. HUB ignored.

## Green root-pinned batch

Excluded prior errno, accounting, admin/status/dashboard 25-case, and 11-case mode/UI receipts.

Root modules were preloaded and source path/SHA asserted:

- `src/local_ai_hub/agent_events.py`: `30AB4485F34A67D8212E6151057E06EF806D40F92073036D8F9F4F4546B44822`
- `src/local_ai_hub/http_server.py`: `6F0B986255DD231F40761538227A66F0A9B97F7659064952593FB83B48130DB3`
- `src/local_ai_hub/telemetry.py`: `79146032D1C904FA57875858A4C4265A8FE6D02BCC62F9CBCEE258D7DAF685EE`
- `src/local_ai_hub/app.py`: `2B6E826FEF08863EF9BF1528E402F7DE041A6A2B08A3812E8454398BC1750546`

Root selector: `tests/test_agent_event_page_t18.py tests/test_db_query_bounds_t18.py tests/test_telemetry_report_bounds_t18.py tests/test_telemetry_timeline_paging_t18.py tests/test_http_telemetry_paging.py`.

```text
python -B -W error::ResourceWarning -c <preload root agent_events/http_server/telemetry/app, assert paths and hashes above, pytest.main(['-q','-p','no:cacheprovider','--tb=short', absolute root paths for the five selectors])>
23 passed in 13.24s
```

Coverage: event page cursor/gap/snapshot and HTTP serialization, bounded SQLite query work/rows, error report offset pagination/response budget, timeline before-id paging, HTTP telemetry report page navigation and invalid numeric page values.

## Root-current residuals

Ran only two missing assertions from candidate test files while importing and hash-pinning root `http_server.py` and `telemetry.py`:

```text
python -B -W error::ResourceWarning -c <preload pinned root http_server/telemetry; pytest.main(['-q','-p','no:cacheprovider','--tb=short','C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub\tests\test_db_query_bounds_t18.py::test_read_only_db_query_rejects_results_over_byte_budget','C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub\tests\test_telemetry_report_bounds_t18.py::test_telemetry_error_cursor_survives_rank_changes_between_pages'])>
2 failed in 0.87s
```

1. `test_read_only_db_query_rejects_results_over_byte_budget`: root handler returned `success=True`, `count=40` for forty 8,192-character rows. Expected `{"success":false,"error":"query result exceeded byte limit"}`. Root `_handle_db_query` fetches up to 100 rows then returns them without serialized byte-size check. Candidate test SHA-256 `F809E0221994C1DD0AFFBF3C8E4C930F2320C02BA62BB50E6696CD44F9175B52`.
2. `test_telemetry_error_cursor_survives_rank_changes_between_pages`: root raised `TypeError: TelemetryStore.report() got an unexpected keyword argument 'error_cursor'`. Root report supports offset pagination; stable cursor pagination is absent. Candidate test SHA-256 `E65B40D7A739E6514B8D1AE70B70E5A42ED8BC060ED7BEE8D54558188E9807D4`.

These are root-current feature gaps, not test expectation mismatches; candidate regression tests independently passed in the prior candidate suite. No root fix was made. T20/source owners must decide integration and receipts.

## Pins for green root tests

- `tests/test_agent_event_page_t18.py`: `39BE401F6709F46F52FFAE904CF87D7DB5B9D329DF381206E98EB633C2CA0B68`
- `tests/test_db_query_bounds_t18.py`: `F809E0221994C1DD0AFFBF3C8E4C930F2320C02BA62BB50E6696CD44F9175B52`
- `tests/test_telemetry_report_bounds_t18.py`: `E65B40D7A739E6514B8D1AE70B70E5A42ED8BC060ED7BEE8D54558188E9807D4`
- `tests/test_telemetry_timeline_paging_t18.py`: `69692CA772553518CE4EE840F22D525A85941C0A5B36047FDEFF95E3E019CDC8`
- `tests/test_http_telemetry_paging.py`: `958FE2B0A5E828519804B34D7568D30407CB6E39DE02C266AC991323AF58219A`

T18 acceptance remains **OPEN** on response-byte bound and stable error cursor in current root. No full root suite, live Hub, GPU, or user-browser check performed.

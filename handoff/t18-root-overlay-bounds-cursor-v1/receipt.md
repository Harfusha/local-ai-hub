# T18 root-current overlay handoff: bounds + telemetry cursor

## Scope and ownership

- HUB was unavailable per user instruction and was not called.
- Root checkout `C:\Users\Adam\.local-ai-hub` remained read-only; no patch was applied there.
- Work was isolated in candidate checkout overlay `.t18-root-overlay-bounds-cursor-v1`.
- Only two residuals were addressed: reject oversized read-only DB query results; add stable keyset cursor pagination to `TelemetryStore.report()`.
- HTTP route wiring for `error_cursor` is intentionally outside this patch scope; callers can use the store API directly until a separate route change is authorized.

## Evidence

- RED, against copied root sources and exact regressions: 2 failed in 0.75s.
  - `test_read_only_db_query_rejects_results_over_byte_budget`: returned success/count=40 instead of byte-limit error.
  - `test_telemetry_error_cursor_survives_rank_changes_between_pages`: `report()` rejected `error_cursor` with `TypeError`.
- GREEN, after overlay-only edits, exact same selectors: 2 passed in 1.03s.
  - Command: `python -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider .t18-root-overlay-bounds-cursor-v1/tests/test_db_query_bounds_t18.py::test_read_only_db_query_rejects_results_over_byte_budget .t18-root-overlay-bounds-cursor-v1/tests/test_telemetry_report_bounds_t18.py::test_telemetry_error_cursor_survives_rank_changes_between_pages`
- Root-current apply check: `git apply --check <patch>` succeeded; no output/errors. `git apply --stat` reports 4 files, 164 insertions, 18 deletions.

## Root hashes observed after work

The two source hashes match the root preimage pins recorded before overlay edits:

- `src/local_ai_hub/http_server.py`: `6F0B986255DD231F40761538227A66F0A9B97F7659064952593FB83B48130DB3`
- `src/local_ai_hub/telemetry.py`: `79146032D1C904FA57875858A4C4265A8FE6D02BCC62F9CBCEE258D7DAF685EE`
- `tests/test_db_query_bounds_t18.py`: `F809E0221994C1DD0AFFBF3C8E4C930F2320C02BA62BB50E6696CD44F9175B52`
- `tests/test_telemetry_report_bounds_t18.py`: `E65B40D7A739E6514B8D1AE70B70E5A42ED8BC060ED7BEE8D54558188E9807D4`

Root status for these paths after work: the two source files are modified and the two T18 test files are untracked in the existing checkout state. This turn did not write to root.

## Patch

- `t18-root-bounds-cursor.patch`
- SHA-256: `B71A023F2FB86D01C7F1FE188782700E481B8F317C5CAFE39622E60A896E1BD0`
- Patch covers the DB query byte budget, cursor helpers/query/page metadata, and the two focused regression tests.

# T18 telemetry HTTP cursor route patch

## Scope

- Separate patch depends on the T18 `TelemetryStore.report(error_cursor=...)` patch.
- Changes only the `/api/telemetry/report` handler hunk in shared `http_server.py` and adds one focused HTTP regression test.
- Reads blank `error_cursor=` explicitly, forwards provided cursors, and maps cursor validation `ValueError` to terminal HTTP 400.
- No root files written; no HUB calls.

## Proof

- Fail-first, with root-current HTTP source plus isolated T18 telemetry-store cursor fix: exact route selector failed with `KeyError: 'cursor'`.
- Green after route-only overlay edit: `1 passed in 6.82s`.
- Command used `PYTHONPATH=.t18-root-overlay-routecursor-v1\src` and `-o pythonpath=` to prevent candidate `src` shadowing root-current overlay.
- Strict root-current `git apply --check --whitespace=error` passed.
- Patch stat: two files only; one `http_server.py` route hunk and telemetry report test imports + one test.

## Root preimage observed

- `src/local_ai_hub/http_server.py`: `520A77B5F2B8E0B4C4C9FC68A8B7E7718DD3A170C37E197AF1623F4C0853C38D`
- `tests/test_telemetry_report_bounds_t18.py`: `2F72E3B1FA549683C19D6BE8C2B3D2A116AAF01675E88EDD3469E9AC2FBD0B63`
- Root status already showed `http_server.py` modified and telemetry test untracked. Existing state preserved.

## Patch

- `t18-root-telemetry-route-cursor.patch`
- SHA-256: `9d32d367dabb28782d21d021978f9fd27628858482bc1726b61939e3a9274392`
- Changes confined to telemetry report handler around lines 2316-2335; test appended to `test_telemetry_report_bounds_t18.py`.

# T18 separate telemetry HTTP route patch

## Scope

- Patch: `t18-root-telemetry-route-cursor-v2.patch`
- SHA-256: `ca40796fa546eb090767cb1658296d372c0bc228b77b40e5858b9e34a32656bf`
- Two paths only: one `/api/telemetry/report` hunk in `src/local_ai_hub/http_server.py`; one focused cursor regression in `tests/test_http_telemetry_paging.py`.
- Parses blank `error_cursor=` explicitly; forwards cursor; maps cursor validation errors to terminal HTTP 400.
- Separate test file avoids overlapping store test ownership.

## Root preimages

- `src/local_ai_hub/http_server.py`: `520A77B5F2B8E0B4C4C9FC68A8B7E7718DD3A170C37E197AF1623F4C0853C38D`
- `tests/test_http_telemetry_paging.py`: `958FE2B0A5E828519804B34D7568D30407CB6E39DE02C266AC991323AF58219A`


Strict `git apply --check --whitespace=error` passed against current root. No root files written.

## Validation

The combined isolated overlay used current-root source/test copies plus this route hunk. Store, DB byte-limit and HTTP cursor selectors: `3 passed in 1.43s`.

Earlier route patch `t18-root-telemetry-route-cursor.patch` (SHA-256 `9D32D367DABB28782D21D021978F9FD27628858482BC1726B61939E3A9274392`) also passes strict current-root apply-check. V2 supersedes it because route regression now lives in `test_http_telemetry_paging.py`, separate from store test file.

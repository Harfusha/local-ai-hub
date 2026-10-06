# T18 final store + route root pins

## Integration state

- Store cursor implementation and DB response-byte cap already present in root before this receipt; no store patch applied by this turn.
- T20 reports integration of route v1 patch. Do not apply route v2; it duplicates route source hunk and is not needed.
- Root remained read-only from T18 during this turn.

## Root current SHA-256

- `src/local_ai_hub/telemetry.py`: `191DC35FEC06D804261D14BDA91837FBD088FEE82FE8B6A8BB6D266AAE2E10E5`
- `src/local_ai_hub/http_server.py`: `AC0A63E088F8E4FD519496A087F5FD6EC84DFC8317BFFF17C23DB3E78E67356E`
- `tests/test_telemetry_report_bounds_t18.py`: `96B0A023D501FA15675C89F8816CE92452783593D2801EFE6E3D2A4082AE4FC5`
- `tests/test_db_query_bounds_t18.py`: `1336AFEC4AF6104DBF584AE0BF86F1A27DC6E38C3EE84E7DA3E7E0696A2F2D82`
- `tests/test_http_telemetry_paging.py`: `958FE2B0A5E828519804B34D7568D30407CB6E39DE02C266AC991323AF58219A`

These current post pins were observed after root integration. `http_server.py` and `test_telemetry_report_bounds_t18.py` include other root-owned hunks beyond isolated T18 overlay; no attempt made to overwrite them.

## Store proof

- Cursor helper, `TelemetryStore.report(error_cursor=...)`, stable group keyset, and direct rank-change regression are present in current root.
- Focused current-root source copied to an isolated overlay: DB byte-budget selector + store cursor selector + HTTP route cursor selector passed, `3 passed in 1.43s`.
- Store/DB were not retested in root by T18.

## Route proof

- Integrated patch v1: `t18-root-telemetry-route-cursor.patch`
- SHA-256: `9D32D367DABB28782D21D021978F9FD27628858482BC1726B61939E3A9274392`
- Preimage pins at patch preparation: `http_server.py` `520A77B5F2B8E0B4C4C9FC68A8B7E7718DD3A170C37E197AF1623F4C0853C38D`; `test_telemetry_report_bounds_t18.py` `2F72E3B1FA549683C19D6BE8C2B3D2A116AAF01675E88EDD3469E9AC2FBD0B63`.
- T20 reports root selector `tests/test_telemetry_report_bounds_t18.py::test_telemetry_report_http_route_forwards_error_cursor`: `1 passed in 5.23s`, with `ResourceWarning` treated as error.
- Route v2 SHA `CA40796FA546EB090767CB1658296D372C0BC228B77B40E5858B9E34A32656BF` was prepared and passed apply-check earlier, but remains unapplied/superseded. It only moves route regression coverage to `test_http_telemetry_paging.py`.

## Stale patch disposition

Old combined patch `t18-root-bounds-cursor.patch`, SHA `B71A023F2FB86D01C7F1FE188782700E481B8F317C5CAFE39622E60A896E1BD0`, failed strict apply-check on all four paths. No forced application.

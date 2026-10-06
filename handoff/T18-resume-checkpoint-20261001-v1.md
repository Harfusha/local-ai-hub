# T18 resume checkpoint — 2026-10-01

## Worktree recovery

- Codex artifact listed `C:\Users\Adam\.codex\worktrees\1e33\.local-ai-hub`, but directory was absent. `restore_worktree` returned “No archived worktree with this identity is attached to the current task.”
- Existing assigned T18 candidate checkout is present at `C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub`; resumed it without reset/stage/commit. HEAD: `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f` (detached). Existing dirty work preserved.
- HUB ignored. No root writes.

## Fresh candidate acceptance

All `T18_ROOT_*` variables cleared. Exact scoped candidate selector from `T18-status-dashboard-telemetry-acceptance-20261001-v4.md` rerun:

```text
python -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short [same 65-case dashboard/admin/status/telemetry selector recorded in v4]
65 passed in 22.27s
```

Current candidate pins:

- `src/local_ai_hub/telemetry.py`: `607736CE42A16C348F3032FC514C5FDB19C35A15E2FFA77A260E3F88E99EA14D`
- `src/local_ai_hub/http_server.py`: `771D62EA4C5809255E985F40CF46E59A8093AF2F5381813E49A1C74BDFAA93F0`
- `src/local_ai_hub/dashboard.py`: `91AAAD7FD3D881EA6EEE428AABA38F9DCDFB1E32DF10430F629075AD57C21705`
- `src/local_ai_hub/app.py`: `883BCBABB6755C8430746ADA2FDD735CA211A3E201FCDC387ACC3A8EFCAA7958`
- `src/local_ai_hub/agent_events.py`: `57338914915BC0A123040B8544CD026EACBAD4F23A5CA4DAAE35D2EB50A11C07`
- `tests/test_telemetry_error_diagnostics_t18.py`: `B0303169B5AE7728B4A444B724F7F3BDA0A2EACCE1B681DDAE4884C82DE1BCC2`
- `tests/test_telemetry_sqlite_dashboard_t18.py`: `73947FF8F0C09B9075F6C1A6AFDC7314F1BFB2D3124EF7416C6DD7A896586A4C`
- `tests/test_telemetry_report_bounds_t18.py`: `6FA5FDA5E10D5884D6C1EF493F75247A924E743EAB10FEAAC2C169B43D0171FC`

## Fresh current-root pinned acceptance

Root modules were imported first from `C:\Users\Adam\.local-ai-hub\src`, module paths and current SHA-256 pins asserted, tests run through candidate harness.

- Mode/auth/dashboard DOM/SQLite/realtime status selector: `11 passed in 8.80s`.
- Telemetry privacy/error metadata/errno, report cursor+route, DB byte cap, timeline, HTTP paging, and agent-event paging selector: `28 passed, 1 failed in 15.57s`.
- Sole failure: `tests/test_telemetry_privacy.py::test_error_telemetry_persists_classification_without_exception_text` timed out at `assert store.flush(1)`. This assertion precedes SQLite privacy checks; no privacy assertion failed.
- Ran that one selector alone once, same pinned root telemetry source: `1 passed in 0.77s`. Treat batch failure as a writer-drain timing sensitivity under load; report both results.
- T20 reports integrated route selector `tests/test_telemetry_report_bounds_t18.py::test_telemetry_report_http_route_forwards_error_cursor`: `1 passed in 5.23s`, `ResourceWarning` treated as error.

Current root pins, identical before and after tests:

- HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`
- `src/local_ai_hub/http_server.py`: `AC0A63E088F8E4FD519496A087F5FD6EC84DFC8317BFFF17C23DB3E78E67356E`
- `src/local_ai_hub/telemetry.py`: `191DC35FEC06D804261D14BDA91837FBD088FEE82FE8B6A8BB6D266AAE2E10E5`
- `src/local_ai_hub/dashboard.py`: `9FC006FD0F5A3E3EBE2CFA0DA79F8786DFD4CB7BE1AB2CD6599CF7363C51A760`
- `src/local_ai_hub/app.py`: `2B6E826FEF08863EF9BF1528E402F7DE041A6A2B08A3812E8454398BC1750546`
- `src/local_ai_hub/agent_events.py`: `30AB4485F34A67D8212E6151057E06EF806D40F92073036D8F9F4F4546B44822`
- `tests/test_telemetry_report_bounds_t18.py`: `96B0A023D501FA15675C89F8816CE92452783593D2801EFE6E3D2A4082AE4FC5`
- `tests/test_telemetry_error_diagnostics_t18.py`: `325323CD2FFA5F2C34DDC3D54D5BEFFF2A032BBC988291F0E9719128E379D0AD`
- `tests/test_telemetry_sqlite_dashboard_t18.py`: `6F841BAE86741DE4D6A01A7A2BD227CBCF8524EF982E9A6AC2FDED430E0705AC`
- `tests/test_http_telemetry_paging.py`: `958FE2B0A5E828519804B34D7568D30407CB6E39DE02C266AC991323AF58219A`
- `tests/test_db_query_bounds_t18.py`: `1336AFEC4AF6104DBF584AE0BF86F1A27DC6E38C3EE84E7DA3E7E0696A2F2D82`

## Scope boundary

T18 candidate source remained unchanged by this continuation; only this checkpoint was added. Root remained read-only. T20 owns integrated release/full-root acceptance. No live Hub, GPU, or user browser validation performed.

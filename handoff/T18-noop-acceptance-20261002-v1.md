# T18 telemetry/status/dashboard acceptance — verified no-op — 2026-10-02 v1

## Decision

No candidate source/test change or new root-current patch is missing for this T18 scope. Existing safe diagnostic code, dashboard mode authorization, and degraded/stale status behavior pass fresh targeted candidate validation. Root edits and root tests were forbidden and not performed.

## Candidate identity and hashes

Worktree: `C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub`, detached HEAD `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`.

- `src/local_ai_hub/telemetry.py`: `B58636B4FDD994279C5BA2659A80FCF87D4C7233AF3D7337FB7CCB1685D5E338`
- `src/local_ai_hub/http_server.py`: `771D62EA4C5809255E985F40CF46E59A8093AF2F5381813E49A1C74BDFAA93F0`
- `src/local_ai_hub/dashboard.py`: `91AAAD7FD3D881EA6EEE428AABA38F9DCDFB1E32DF10430F629075AD57C21705`
- privacy test `tests/test_telemetry_error_metadata_privacy_t18.py`: `28B39E33D97830F8055354DE1D9465AFACB7659D89A37CAF85EE3BAD9C4AD4D5`
- classification test `tests/test_telemetry_error_classification_t18.py`: `511D88EC45BEAE8423D5AF3C4AFD1059117731BA74C5EE1FB3252E1BCC7B06B6`
- admin auth test `tests/test_http_admin_action_auth_t18.py`: `BB06BAFC7CE5CAFD851E1B96FCE3D30ECAD10D513D5C52010F762CF449475B25`
- operational mode test `tests/test_http_operational_mode_t18.py`: `ADAAE6C4260A6700DB09744764546B10B82CAA7C59242A46A493833946684C72`
- status diagnostics test `tests/test_http_status_diagnostics_t18.py`: `3F61C56ECCBDACE90A1BE69B2BD5A51970B191A0EDAE7BF53A935EB0A7DD6715`
- dashboard browser test `tests/test_dashboard_mode_playwright_t18.py`: `6A5C513A00B32A9E3F475B4421A93BD37D3864875C823BFAF3235052E1AAE257`
- status quality test `tests/test_status_snapshot_quality.py`: `00EC4D2ABD65ABBF07EBF4981D41C2B0893F5FAB9A67CFF005F0CB39B1EF5DE7`

## Privacy-safe diagnostic contract

`_safe_error_code` retains only integer `status_code`, `errno`, or `code` within `[-65535, 65535]`. It feeds the safe error fingerprint. Persisted diagnostic keeps sanitized exception type and allowlisted reason; raw exception text/code does not enter the user-visible safe message. The privacy test checks same 503 fingerprints match, 504 differs, and private prompt/source/token/path values are absent from persisted errors/events.

## Fresh candidate validation

With all `T18_ROOT_*` variables cleared:

```text
python -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short tests/test_telemetry_error_diagnostics_t18.py tests/test_telemetry_error_classification_t18.py tests/test_telemetry_error_metadata_privacy_t18.py tests/test_telemetry_sqlite_dashboard_t18.py tests/test_telemetry_privacy.py::test_error_telemetry_persists_classification_without_exception_text tests/test_http_admin_action_auth_t18.py tests/test_http_operational_mode_t18.py tests/test_http_status_diagnostics_t18.py tests/test_dashboard_mode_playwright_t18.py tests/test_status_snapshot_quality.py::test_slow_status_dependency_degrades_within_deadline_and_keeps_shape tests/test_status_snapshot_quality.py::test_status_distinguishes_offline_from_successful_runtime_probe tests/test_status_snapshot_quality.py::test_slow_accelerator_probe_degrades_within_deadline_and_keeps_shape tests/test_status_snapshot_quality.py::test_realtime_status_bounds_runtime_health_probes tests/test_status_snapshot_quality.py::test_slow_agent_state_summary_uses_dependency_deadline tests/test_dashboard_operational_surfaces.py::test_dashboard_distinguishes_unknown_ollama_probe_from_offline tests/test_dashboard_operational_surfaces.py::test_dashboard_marks_degraded_live_status_and_retries_with_backoff tests/test_dashboard_operational_surfaces.py::test_dashboard_reports_incomplete_vram_unload_after_gaming_pause tests/test_dashboard_operational_surfaces.py::test_operator_surfaces_report_all_transition_failures tests/test_dashboard_operational_surfaces.py::test_live_pollers_skip_overlapping_requests
66 passed in 15.49s
```

Stale dependency reuse:

```text
python -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short tests/test_status_snapshot_quality.py::test_timed_out_agent_state_is_reused_across_status_cache_hits
1 passed in 0.33s
```

## Root-current boundary

Existing manifest `handoff/T18-root-current-manifest-20261002-v1.md` SHA-256 `CA0E26E1E563200012A57D57E0DEF1178EE35A79C8EB1C53C1F09D81FBA54C44` records T18 flush patch SHA `09BBC8E951F5DE8654C40F19E9120AE8C800D3621DDF6F902D411A49DBFE400F`, applied to root per T20 report. T20-reported root post-image SHA: telemetry `59A8F461CCF11C09526624EDEBD4D4FD99FB314935BE893BBFCE052CAF09281B`; regression test `D1FFDFB7BDB48870286B697AC374F4C9E18B9F5ACFBAB627ABD6DFF3394A8A13`. These root receipts were not refreshed or independently checked in this no-root task.

T20 still owns root original privacy test post-fix and overall release acceptance. No root command ran in this task. Other owners' dirty paths remain preserved.

# T18 resume checkpoint — 2026-10-02 v7

## Scope

Resumed acceptance in assigned candidate worktree only: `C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub`, detached HEAD `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`. HUB unused. No broad test run. No source/test code edited in this continuation; pre-existing dirty paths from other owners remain.

## Fresh targeted receipt

With all `T18_ROOT_*` variables cleared:

```text
python -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short tests/test_telemetry_flush_retry_t18.py tests/test_telemetry_privacy.py::test_error_telemetry_persists_classification_without_exception_text tests/test_telemetry_error_metadata_privacy_t18.py tests/test_telemetry_error_classification_t18.py tests/test_telemetry_error_diagnostics_t18.py tests/test_telemetry_sqlite_dashboard_t18.py tests/test_http_admin_action_auth_t18.py tests/test_http_operational_mode_t18.py::test_mode_get_is_loopback_only_auth_exception_and_returns_snapshot tests/test_http_operational_mode_t18.py::test_mode_get_without_api_token_does_not_open_admin_post tests/test_http_operational_mode_t18.py::test_admin_mode_post_requires_authorization tests/test_http_operational_mode_t18.py::test_authorized_mutation_fails_closed_when_mode_dependency_is_unavailable tests/test_http_status_diagnostics_t18.py tests/test_dashboard_mode_playwright_t18.py tests/test_status_snapshot_quality.py::test_slow_status_dependency_degrades_within_deadline_and_keeps_shape tests/test_status_snapshot_quality.py::test_status_distinguishes_offline_from_successful_runtime_probe tests/test_status_snapshot_quality.py::test_slow_accelerator_probe_degrades_within_deadline_and_keeps_shape tests/test_status_snapshot_quality.py::test_realtime_status_bounds_runtime_health_probes tests/test_status_snapshot_quality.py::test_slow_agent_state_summary_uses_dependency_deadline tests/test_status_snapshot_quality.py::test_timed_out_agent_state_is_reused_across_status_cache_hits tests/test_dashboard_operational_surfaces.py::test_dashboard_distinguishes_unknown_ollama_probe_from_offline tests/test_dashboard_operational_surfaces.py::test_dashboard_marks_degraded_live_status_and_retries_with_backoff tests/test_dashboard_operational_surfaces.py::test_dashboard_reports_incomplete_vram_unload_after_gaming_pause tests/test_dashboard_operational_surfaces.py::test_operator_surfaces_report_all_transition_failures tests/test_dashboard_operational_surfaces.py::test_dashboard_exposes_activity_mode_and_reports_http_failures
42 passed in 18.85s
```

Coverage includes privacy-safe telemetry classification/persistence and retry; O5 action auth; loopback mode GET and unauthorized mode POST; mode dependency fail-closed behavior; dashboard DOM errors; status dependency deadlines, stale-cache reuse, and degraded transitions.

## Candidate pins unchanged by tests

- `src/local_ai_hub/telemetry.py`: `B58636B4FDD994279C5BA2659A80FCF87D4C7233AF3D7337FB7CCB1685D5E338`.
- `src/local_ai_hub/http_server.py`: `771D62EA4C5809255E985F40CF46E59A8093AF2F5381813E49A1C74BDFAA93F0`.
- `src/local_ai_hub/dashboard.py`: `91AAAD7FD3D881EA6EEE428AABA38F9DCDFB1E32DF10430F629075AD57C21705`.
- `tests/test_telemetry_privacy.py`: `A33405560C715B20A621A243CBA6B26451FC38DB0CB1EDA43957ED978DAB3917`.
- `tests/test_telemetry_flush_retry_t18.py`: `5D584579BF3927A4D93EAE2EB8EC97DEF3C16720A84EFA48C2276DAB317C83EC`.

No new root or integration patch required for this candidate acceptance. Root-current integration details and T13 mode-source dependency remain recorded in `T18-root-current-acceptance-20261002-v2.md`.

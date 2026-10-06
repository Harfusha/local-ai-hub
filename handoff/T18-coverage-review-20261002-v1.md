# T18 dashboard/status coverage review — 2026-10-02 v1

## Scope and ownership

Read-only review in candidate worktree `C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub`, detached HEAD `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`. No root tests ran. No source, test, or other-owner path changed. HUB was not used.

## Review finding

The documented 65-test candidate selector in `T18-status-dashboard-telemetry-acceptance-20261001-v4.md` covers Playwright error projection, admin/mode/status-diagnostics, and five selected dashboard behavior tests. It omits several focused dashboard/status cases for unknown versus offline probes, degraded live state, transition failure, and slow dependency degradation. Added selectors below close this candidate coverage gap. The later 66-test selector command is not recorded verbatim, so overlap with that run is unknown; these supplemental runs provide fresh receipts regardless.

The dashboard Playwright case already covers degraded/partial/401/503 UI projection. `test_dashboard_operational_surfaces.py` and `test_status_snapshot_quality.py` add service-level degraded-state and retry/deadline behavior. No additional T18 candidate selector gap found in this review scope.

## Supplemental candidate receipts

Run from the candidate worktree, with `T18_ROOT_*` variables cleared:

```text
python -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short tests/test_dashboard_operational_surfaces.py::test_dashboard_distinguishes_unknown_ollama_probe_from_offline tests/test_dashboard_operational_surfaces.py::test_dashboard_marks_degraded_live_status_and_retries_with_backoff tests/test_dashboard_operational_surfaces.py::test_dashboard_reports_incomplete_vram_unload_after_gaming_pause tests/test_dashboard_operational_surfaces.py::test_operator_surfaces_report_all_transition_failures tests/test_dashboard_operational_surfaces.py::test_live_pollers_skip_overlapping_requests
5 passed in 0.61s
```

```text
python -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short tests/test_status_snapshot_quality.py::test_slow_status_dependency_degrades_within_deadline_and_keeps_shape tests/test_status_snapshot_quality.py::test_status_distinguishes_offline_from_successful_runtime_probe tests/test_status_snapshot_quality.py::test_slow_accelerator_probe_degrades_within_deadline_and_keeps_shape tests/test_status_snapshot_quality.py::test_realtime_status_bounds_runtime_health_probes tests/test_status_snapshot_quality.py::test_slow_agent_state_summary_uses_dependency_deadline
6 passed in 0.69s
```

The second selector has five node IDs and six parametrized cases.

## Remaining integration dependency

Candidate T18 coverage is complete for dashboard/status degraded states. T20 still owns root original telemetry privacy test after flush fix and overall root release acceptance. This review does not claim root acceptance.

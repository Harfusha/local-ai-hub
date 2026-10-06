# T18 root-current event page and mode-seam handoff

Date: 2026-10-01
Owner: T18 candidate worktree `C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub`
Root integration/test owner: T20. HUB was unavailable and intentionally skipped.

## Root event-page snapshot (read-only)

Root HEAD observed: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.

Current root working-tree SHA-256:

- `src/local_ai_hub/agent_events.py`: `02A25102B888B23FE99B8C508F59AEDD846BA24FD38A268BCC6893B0877E0A38`
- `src/local_ai_hub/http_server.py`: `15BD92CE83A7FB472AAC4581F1A5FAD42ECF6E303C73C7DBC463E05A4528F57F`
- `tests/test_agent_event_page_t18.py`: `39BE401F6709F46F52FFAE904CF87D7DB5B9D329DF381206E98EB633C2CA0B68`

Static source confirms the route and regression fixture are already in the current root working tree. `AgentStateStore.event_page` supports a `through_seq` snapshot bound and returns canonical event dictionaries. `GET /api/agent-state/events` validates/clamps cursor and limit, forwards the optional upper bound, and applies the serialized response byte budget through `_bound_agent_event_page`. The root fixture covers pagination, gaps, route envelope, live HTTP serialization, stable snapshot paging, exact-byte trimming, limit clamp, oversize metadata, disabled-store response, empty retained stream, and the 10,000-row cap.

The prior patch `handoff/T18-pre-T20-agent-event-page-route.patch` is pre-T20 and stale. Do not apply it. The root already contains the route and fixture at the hashes above; T18 made no root edits and ran no root tests. Root test serialization remains with T20. The current root regression fixture is the immutable read-only artifact for that route.

## Candidate mode seam update

Changed candidate paths:

- `tests/test_http_operational_mode_t18.py`: test fixtures now inject the public `local_ai_hub.operational_mode` module contract via `sys.modules`, including the current `set_operational_mode(state_dir, mode)` signature. The test file no longer references `_operational_mode_api` or `_install_mode_api`.
- `tests/test_status_snapshot_quality.py`: the cache test asserts the health field is boolean; dependency health is independently deadline-sensitive and is not the cache test's subject.

Current candidate SHA-256:

- `tests/test_http_operational_mode_t18.py`: `F4FD42094DEF7915B23A9912037EB4EBF397C8881A264C87D34C25A6E2DDD0D4`
- `tests/test_status_snapshot_quality.py`: `2B8CCDCB4EC6A521AD797D535F8530E1DCDDA90D0A14CD04DC884E47D4314311`

Candidate focused command:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_http_operational_mode_t18.py tests/test_agent_event_page_t18.py -k "not admin_mode_post_starts_unload_after_releasing_guard_and_returns_pending_then_partial"
```

Result: **41 passed, 1 deselected in 3.70s**, exit 0. Candidate full T18 selector, excluding that one legacy POST test: **137 passed, 1 deselected in 28.16s**, exit 0. The excluded test was run by itself and failed: `unload_started.wait(1)` remained false. Candidate HTTP still calls the old positional mode setter and expects its legacy async unload helper; T20's root route uses T13's direct current helper seam. No candidate HTTP production change was made to conceal this integration drift.

Exact full candidate command:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_dashboard_operational_surfaces.py tests/test_status_snapshot_quality.py tests/test_http_status_diagnostics_t18.py tests/test_telemetry_report_bounds_t18.py tests/test_debug_traces.py tests/test_telemetry_timeline_paging_t18.py tests/test_db_query_bounds_t18.py tests/test_agent_event_page_t18.py tests/test_http_admin_action_auth_t18.py tests/test_http_operational_mode_t18.py tests/test_telemetry_privacy.py tests/test_telemetry_error_metadata_privacy_t18.py tests/test_telemetry_error_classification_t18.py tests/test_telemetry_error_diagnostics_t18.py tests/test_http_phase_telemetry.py tests/test_http_tool_accounting_rejections.py tests/test_dashboard_mode_playwright_t18.py -k "not admin_mode_post_starts_unload_after_releasing_guard_and_returns_pending_then_partial"
```

Exact known-drift command:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_http_operational_mode_t18.py::test_admin_mode_post_starts_unload_after_releasing_guard_and_returns_pending_then_partial
```

Result: **1 failed in 1.36s**, exit 1; the legacy unload worker never starts.

## Root integration handoff

Use the current root helper names `load_operational_mode`, `operational_mode_gate_error`, and `set_operational_mode(state_dir, mode)`. Do not add `_operational_mode_api` compatibility aliases. The current root also has `_redact_config_secrets`; prior reports saying it was absent are stale. Do not run root selectors until T20 grants the shared test slot.

No root source/test was edited or executed by this T18 continuation. Candidate pytest used temporary test stores and no user browser or shared port.

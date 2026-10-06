# T18 reconciliation onto pinned master 90e6f295 — 2026-10-06

Scope: C:/Users/Adam/.codex/worktrees/t18-status-dashboard/.local-ai-hub only.
Branch: codex/sync-t18-status-dashboard-20261006.
Pin: 90e6f2957489b272f03cd0f3550149907f24bbf7. No moving-master lookup.
Acceptance: INCOMPLETE / NOT VERIFIED. Committing preserves unfinished work; it is not release acceptance.

## Preservation and execution plan

- Start: accepted committed packet 4274b2ec8b26290b8da61ba8411bcad973343568; no tracked dirty changes at entry.
- Preserve that packet at refs/checkpoints/sync-t18-status-dashboard-before-90e6f295-20261006; pin retained at refs/checkpoints/sync-t18-status-dashboard-pin-90e6f295-20261006.
- Previous original/tracked/preserved/master checkpoint refs remain: a1b04bb3, 81635485, 938a96ae, f5794721. Previous handoff and file manifest remain historical evidence, not fresh acceptance.
- Plan executed: preserve; merge the pin exactly once with --no-commit --no-ff; review overlapping hunks; resolve; run bounded focused suites; commit all relevant source/tests/docs and this note; verify ancestry, unresolved files and tracked/index cleanliness.
- User supplied terminal Hub failure and native-fallback authority. No Hub retry/poll, root checkout edit, master-ref update, fetch/push, stash, hard reset, clean, new worktree/chat, dependency installation or feature work.
- Optional token-economizer setup script remains absent. No installation or User PATH changes. Native validation is side-effecting and owned by this reconciliation; PYTHONPATH=assigned/src, PYTHONDONTWRITEBYTECODE=1, TMP/TEMP and unique pytest basetemp directories under ignored .t18-sync-tmp.
- Original four .t18-* overlay directories and handoff/.tmp_dashboard_patch remain untracked preserved artifacts. Runtime caches/DBs/scratch stay outside Git; no runtime state staged.

## Overlapping hunk decisions

- Nine conflicted paths: docs/HTTP_API.md; app.py, dashboard.py, http_server.py, mcp_server.py; test_dashboard_polling_quality.py, test_debug_traces.py, test_http_tool_accounting_rejections.py, test_status_snapshot_quality.py.
- Dashboard and polling tests: reviewed normalized base/pin/previous differences despite whole-text CRLF/LF conflict. Retained the pinned implementation, not the old extracted-poller overlay: warming/stale status, visibility aborts, adaptive timers, stable cache fingerprint, hardware retry, bounded Reveal and retention notices, 200-event window, older/newer navigation, SSE client cursor/dedup, escaped exact 64-bit trajectory sequences and retention gaps. Local older trajectory Number cursors, direct polling/refresh rewrites and interval trace loop are superseded but recoverable in 4274b2ec/938a96ae. No duplicate 70059e18 patch applied; its dashboard/polling blobs are already in the pin.
- app.py: retained pin nonblocking cache acquisition, warming/stale responses, snapshot_cached/status_age_ms and truthful degraded flags for both status APIs. Retained local bounded dependency reads, unknown/offline distinction and diagnostic metadata. Removed the automatic merge's duplicate read/deadline/headless block. Full-status parallel scheduling remains. Local worker cap 32 (bounded inflight 32) remains; performance acceptance is unverified.
- mcp_server.py: keep pin contract-state preservation and /api/status full routing without forcing success. Keep local telemetry string sanitization and bounded exception envelopes; sanitize restored telemetry state too. Full/telemetry/agent-state requests no longer perform an unnecessary initial live probe. Both helper blocks retained; no duplicate definitions.
- http_server.py: keep pin SQL/body/model-pull bounds, nested debug request redaction, authorization, send/error/journal behavior and ordered SSE handler. Keep local socket-peer plus host/origin validation for redacted mode GET; retain bounded trace/event/telemetry pages and old route extraction. Resolve worktree_release with pin worktree_id forwarding and current paths. T14 /api/context/pack subtree is AST-identical to the pin; untouched design/ownership.
- Telemetry automatic merge retained pin queue acceptance and self-accounting rejection changes plus local stricter metadata/path sanitization and bounded cursor helpers. Tests of privacy and rejected accounting passed in the first focused run. AgentStateStore ordered event behavior remains pinned; only import dedup/spacing differs.
- Trace tests: preserve both local byte-budget/cursor tests and pin overflow/backward/content-page/privacy tests. Reconstruct the conflicted function boundaries rather than mixing assertion bodies. After the observed forward-cursor disagreement, choose pin signed-integer clamp and empty past-end pages, not local implicit reset/replay. Historical reset assertions stay committed and fail explicitly. Accounting/status tests retain both applicable assertions and pin new rejection/concurrency coverage. No test removed merely because it fails.
- HTTP docs retain both master cache/SSE warnings and local bounded detail/report descriptions. Dashboard-specific trace oversize handling claim from the historical packet is not current acceptance: the pinned dashboard has a different content-page contract, recorded below.
- Client, preprocessing, defaults, operational_mode, services and work_orchestrator match pinned content after newline normalization. Gemini preprocessing and CodeGraph runtime removal retained. T16/T17/T10 integrated master work was not duplicated.

## Actual bounded validation

All pytest commands: python -B -m pytest -q -p no:cacheprovider --tb=short, assigned root and source provenance, distinct ignored --basetemp. No full release suite, deployment, live Hub retry, model pull or browser acceptance.

First run, --basetemp=.t18-sync-tmp/pytest-90-status: 236 passed / 9 failed in 38.00s.
Files: test_dashboard_polling_quality.py, test_dashboard_operational_surfaces.py, test_dashboard_custom_modals.py, test_status_snapshot_quality.py, test_t18_status_full_output_contract.py, test_telemetry_error_diagnostics_t18.py, test_telemetry_error_metadata_privacy_t18.py, test_telemetry_privacy_t18.py, test_telemetry_report_bounds_t18.py, test_telemetry_self_accounting.py, test_http_admin_action_auth_t18.py, test_http_status_diagnostics_t18.py, test_http_tool_accounting_rejections.py.

Exact first-run failures (paths below are under tests/):

- test_dashboard_operational_surfaces.py::test_merged_dashboard_preserves_reviewed_html_golden: actual 493213 bytes, historical expectation 479461.
- test_dashboard_operational_surfaces.py::test_dashboard_distinguishes_unknown_ollama_probe_from_offline: pinned dashboard health helper lacks ollama_status.
- test_dashboard_operational_surfaces.py::test_dashboard_marks_degraded_live_status_and_retries_with_backoff: old literal success-false branch absent in pinned pollStatus.
- test_dashboard_operational_surfaces.py::test_trace_inspector_consumes_pages_with_hard_response_budget: old limit=100&max_bytes=8388608 URL absent.
- test_dashboard_operational_surfaces.py::test_status_poller_respects_visibility_unchanged_state_and_jitter: TypeError: poller.refresh is not a function.
- test_dashboard_operational_surfaces.py::test_trajectory_inspector_uses_bounded_cursor_pages: historical trajEventPager DOM ID absent.
- test_dashboard_operational_surfaces.py::test_dashboard_wires_status_refreshes_through_backoff_poller: historical statusPoller.refresh() calls absent.
- test_status_snapshot_quality.py::test_light_status_cache_hit_does_not_requery_dependencies: KeyError: 'cached'; pin uses snapshot_cached/status_age_ms.
- test_t18_status_full_output_contract.py::test_t18_full_status_matches_generic_object_output_contract: success False versus expected True; local fixture only serves live status, while pin correctly requests /api/status and does not force success.

Second run, --basetemp=.t18-sync-tmp/pytest-90-integration: 105 passed / 33 failed in 98.40s.
Files: test_debug_traces.py, test_sse_events_stream.py, test_agent_event_drop_metrics.py, test_http_post_route_registry_t18.py, test_http_post_db_query_t18.py, test_event_page_contract_t18.py, test_mcp_compact_transport.py, test_t16_terminal_rollback_preflight.py, test_transcription_contract.py; selected test_mutation_replay.py::test_send_normalizes_http_error_before_journaling_and_serializing and ::test_journal_outcome_unknown_overrides_terminal. T16 rollback/terminal, selected journal/error, DB and event-page tests passed. Transcription failures do not represent live Whisper quality evidence.

Exact second-run failures (under tests/; parameter groups enumerate separate failing cases):

- test_debug_traces.py::test_trace_detail_clamps_forward_cursor_to_sqlite_integer_range[9223372036854775807], [9223372036854775808], [1267650600228229401496703205376]: expected empty events; local reset returned seq 1. These three failures are superseded by the pin-aligned cursor recheck below.
- test_debug_traces.py::test_trace_detail_supports_bounded_backward_event_pages: TypeError: DebugTraceStore.detail() got an unexpected keyword argument 'before_seq'.
- test_debug_traces.py::test_backward_page_size_trimming_does_not_claim_older_events: same unexpected before_seq.
- test_debug_traces.py::test_forward_page_size_trimming_preserves_cursor_for_omitted_events: actual [1, 2], expected [1].
- test_debug_traces.py::test_full_payload_detail_marks_content_beyond_bounded_preview: unexpected keyword argument 'full_payload'.
- test_debug_traces.py::test_full_payload_content_pages_reconstruct_retained_session_and_event_data: unexpected full_payload.
- test_debug_traces.py::test_large_unicode_content_pages_use_indexed_chunks_at_late_offsets: unexpected full_payload.
- test_debug_traces.py::test_detail_flags_event_payload_truncated_before_response_serialization: unexpected full_payload.
- test_debug_traces.py::test_detail_flags_session_fields_truncated_before_response_serialization: unexpected full_payload.
- test_debug_traces.py::test_debug_trace_route_forwards_bounded_content_page_cursor: actual since_seq/limit/max_bytes; expected full_payload/content_field/content_offset/before_seq forwarding.
- test_sse_events_stream.py::test_sse_stream_replays_all_pages_and_advances_cursor: actual [0, 100, 200, ..., 1000], expected [0, 1000].
- test_sse_events_stream.py::test_sse_stream_surfaces_retention_gap_before_kind_filtered_replay: ValueError: substring not found for event: stream.gap.
- test_agent_event_drop_metrics.py::test_publish_reports_exact_per_stream_ranges_for_queue_overflow: dropped_event_count 5 versus 3.
- test_agent_event_drop_metrics.py::test_queue_overflow_bounds_gap_ranges_and_marks_omitted_streams: stream.gap versus agent_state.gap.
- test_agent_event_drop_metrics.py::test_queue_overflow_preserves_truncation_when_replacing_gap_marker: same kind disagreement.
- test_http_post_route_registry_t18.py::test_do_post_selects_every_golden_branch_without_moving_existing_gates: post_config_update_1 versus post_bundle_import_1.
- test_http_post_route_registry_t18.py::test_named_telemetry_dispatch_stays_after_recovery_and_inside_error_boundary: ordering assertion 5969 < 3859 fails.
- test_mcp_compact_transport.py::test_status_telemetry_compaction_preserves_required_empty_arrays_and_matches_schema: KeyError: 'anyOf'.
- test_mcp_compact_transport.py::test_mcp_telemetry_tools_call_loopback_matches_declared_output_schema: same KeyError.
- test_mcp_compact_transport.py::test_mcp_telemetry_error_text_is_redacted: Error details omitted versus Telemetry report failed; details omitted. Superseded by the envelope correction/recheck below.
- test_mcp_compact_transport.py::test_python_direct_invocation_returns_dict: RecursionError: maximum recursion depth exceeded, lazy CLIENT.get recursion.
- test_mcp_compact_transport.py::test_mcp_delegate_autostarts_owned_daemon_and_preserves_http_payload: cannot import name 'operational_mode_gate_error'; error envelope success False.
- test_mcp_compact_transport.py::test_local_ai_repo_context_forwards_guarded_pack_fields: success False versus True.
- test_mcp_compact_transport.py::test_local_ai_repo_context_low_budget_preserves_authoritative_envelope: scope_dr versus scope_drift warning code.
- test_mcp_compact_transport.py::test_local_ai_repo_context_rejects_malformed_guard_input_before_http: context query cannot be empty versus guarded must be boolean.
- test_mcp_compact_transport.py::test_local_ai_repo_context_enforces_pack_budget_and_identity_types: context query cannot be empty rather than budget error containing 128.
- test_mcp_compact_transport.py::test_local_ai_repo_context_rejects_guard_fields_without_guard_trigger: context query cannot be empty rather than require guarded=true.
- test_mcp_compact_transport.py::test_mcp_artifact_page_rejects_store_slice_larger_than_text_limit: MCP output contract failed: result does not match a declared output variant for action='get', rather than expected text-limit envelope.
- test_mcp_compact_transport.py::test_registered_mcp_context_uses_actual_http_context_pack: empty context lacks AdaptiveContextMarker.
- test_transcription_contract.py::test_whisper_process_failure_never_returns_successful_transcript[nonzero]: KeyError: 'returncode'.
- test_transcription_contract.py::test_whisper_process_failure_never_returns_successful_transcript[timeout]: KeyError: 'retryable'. Source and test match pin; no T17 redesign attempted.

Merge-only telemetry envelope correction: contract-state restoration overwrote the projection's safe standardized error. Preserve that projected error in the sanitized state before restoration; never restore raw text. --basetemp=.t18-sync-tmp/pytest-90-envelope: 4 passed / 1 failed in 7.00s. Selected test_mcp_telemetry_error_text_is_redacted and all test_telemetry_error_metadata_privacy_t18.py passed; test_t18_full_status_matches_generic_object_output_contract still failed exactly as above.

Pin-aligned cursor correction recheck, --basetemp=.t18-sync-tmp/pytest-90-cursor: 7 passed / 4 failed in 4.32s. The three pin test_trace_detail_clamps_forward_cursor_to_sqlite_integer_range parameters passed, as did HTTP clamp/oversize and three byte-budget/event-boundary checks. Exact remaining failures: test_debug_traces.py::test_trace_detail_clamps_forward_cursor_and_reports_retained_reset[9223372036854775807], [9223372036854775808], [1267650600228229401496703205376], and ::test_trace_detail_pages_in_sequence_order_with_stable_cursor; all expect cursor_reset True, actual False. This deliberately preserves current master semantics instead of replaying history on a forward cursor. No broad identical command repeated. Earlier run totals remain receipts, not summed or presented as final-suite counts.

## Unfinished acceptance

- Historical fixture/API mismatches above remain committed, not silently deleted or used to revert newer master safety behavior.
- Independent source review confirms pinned pollStatus still returns true rather than changed/degraded outcome, and Refresh passes an Event where callable isCurrent is expected. Helper tests do not prove those integrations. No new feature/fix expansion attempted.
- Trace content-page frontend/backend compatibility, ordered SSE replay/retention/drop accounting, historical route registry parity and MCP compact transport must be evaluated from the second focused run below; a passing dashboard helper does not prove these surfaces.
- Runtime/live browser, service deployment, telemetry durability beyond queue acceptance, model quality/latency, performance under load and full release acceptance remain NOT VERIFIED.
- Old T19/T21 failures in T18_SYNC_CHECKOUT_HANDOFF_20261006.md are historical, not rerun here. No claim that they disappeared.

## Source delta and preservation receipts

171 changed paths against the pin, including committed historical handoff artifacts and this note/manifest. Exact name/status list: T18_SYNC_PIN90_FILES_20261006.txt. Source paths:

- src/local_ai_hub/agent_events.py: duplicate import removal/spacing; ordered publication/event-page behavior retained.
- src/local_ai_hub/app.py: bounded local probes/unknown state combined with pin nonblocking snapshot/warming/stale semantics.
- src/local_ai_hub/dashboard.py: newline-only Git delta (5971 lines), no normalized content difference from pin. No older polling logic restored.
- src/local_ai_hub/dashboard_status_poller.py: preserved checkpointed extracted helper, not wired over the pin dashboard.
- src/local_ai_hub/debug_traces.py: local bounded page/byte metadata plus pin forward-cursor clamp/no implicit rewind; backward/full-content contracts incomplete.
- src/local_ai_hub/http_route_registry.py: preserved historical selector/extraction table; parity failures remain.
- src/local_ai_hub/http_server.py: bounded pages, redacted mode GET, extracted handlers/route predicates retained with pin safety helpers and T14 subtree.
- src/local_ai_hub/mcp_server.py: sanitized telemetry envelopes combined with pin state/full-status routing.
- src/local_ai_hub/projection.py: preserved telemetry required-empty-section handling.
- src/local_ai_hub/telemetry.py: stricter metadata redaction and bounded cursor/page helpers; pin enqueue/self-accounting behavior retained.

Final source audit after corrections: AST parse passed for all 26 changed Python source/test/tool files; no duplicate top-level functions/class methods reported. T14 /api/context/pack subtree equality passed. Handler._stream_agent_events, _safe_debug_trace_request, _send and _require_authorized are AST-identical to pin; method-difference audit shows only page-bound helpers and do_GET/do_POST differ in HTTP shared functions. Client/preprocessing/defaults/operational-mode/services/work-orchestrator normalized content equality passed. Targeted staged git diff --check against pin passed for source/tests/current note/HTTP docs. No full release validation claimed.

349 original untracked files remain preserved in the five historical artifact groups; tracked runtime DB/cache/scratch search returned none. After the documented superseding envelope/cursor rechecks, 42 distinct known failing cases remain (9 first-run cases plus 33 second-run/replacement cursor cases). This is an inventory of observed unresolved cases, not a rerun aggregate suite result.

Final commit/ancestry/unresolved/index receipts are reported after committing this note. All original checkpoint refs and evidence remain; the root's unowned agent_events/client/http_server writer was neither inspected nor edited.

# T18 root-current handoff

## Baselines and scope

- Candidate HEAD: `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`.
- Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.
- Root HEAD remains `98a9a1a7611af574caf20a88620c4aa3eb2e918a`; T18 made no root source edits.
- Read-only current-root snapshot (2026-10-01): HEAD still `98a9a1a7611af574caf20a88620c4aa3eb2e918a`; T20/other owners have dirty `http_server.py`, `dashboard.py`, `debug_traces.py`, and dashboard/trace tests. Latest sampled root working-tree `http_server.py` SHA-256 is `4CB8DED60199A410390831F633AE7E238EF07EDE6AA1562487D760628790DA35`; `_authorized()` still has the pre-O5 signature, while `_is_loopback_client_address` already exists. No root write or test was done by T18.
- Assigned root selector ran once: `tests/test_debug_traces.py::test_cleanup_deletes_terminal_traces_in_batches_and_protects_live_work` — 1 passed in 0.56s. It covers TTL cleanup/protection, not `retention_days`.
- In the T18 worktree, `test_operator_surfaces_report_all_transition_failures` failed before the UI change and passed after it (1 passed in 0.21s). No root test was run for new UI/auth patches.

## Safe isolated hunk

- T18-owned symbols: `DebugTraceStore.__init__` and `DebugTraceStore.stats` in `src/local_ai_hub/debug_traces.py`.
- Patch: `handoff/T18-root-current-trace-retention.patch` (SHA-256 `CAB3FCEBCEBB6E46B12CA64F7D31BC7EF801592FC54AC1166E578219F71F27D5`). T20 reports this source patch integrated; do not reapply.
- Root-current test-only retention-days patch: `handoff/T18-root-current-trace-retention-days-test.patch` (SHA-256 `0FE2F8CA9F1FD10EB33EDFF520E6173AA33AF870B9D2EEE74B9488A63B1BA64C`), preimage `tests/test_debug_traces.py` SHA-256 `958AB2CFD016669AF5FA499E0DB57261A08AFEE21E0E0BF786CB6EA11A3B65F3`. `git apply --stat` parses it as 16 insertions; no root apply or test. Candidate counterpart passed inside the 38-test status/telemetry/retention selector.

## New operator-status P2

- Root evidence: `applyActivityMode` only reported `runtime_unload`; `accelerator_release` and `job_cancellation` failures could still lead to “Mode set to …”. Backend persists/returns mode success separately from follow-up results.
- Root-current display patch: `handoff/T18-root-current-operator-display.patch` (SHA-256 `C65C257D082B180B908F6DCAC49DB09CA0131BF05E290D353CD7D9F9DCB579CC`); T20 reports root apply-check, application, AST, and diff-check passed.
- Current read-only root snapshot shows `src/local_ai_hub/dashboard.py` SHA-256 `9FC006FD0F5A3E3EBE2CFA0DA79F8786DFD4CB7BE1AB2CD6599CF7363C51A760`, with `tests/test_dashboard_operational_surfaces.py` SHA-256 `46F2816F1CE47665ED7B01F8C87B617C15B222F1AD1923BF736AE577492B31B6`; the actual async transition tests are present. Root trace source SHA-256 is `5B1B45E757CF0C3049F2716A13C94B93783793EFD3265DD395F52EE7D959007A`. T18 made no root change or test in this turn.
- Candidate regression now executes actual `applyActivityMode` with Node `vm` and fake DOM. Runtime unload test and separate accelerator/job/success/401 matrix passed 2/2 in 0.57s.
- Test-only root update: `handoff/T18-root-current-operator-behavior-tests.patch` (SHA-256 `E65D8757CA5FC42B9003B91CC01C73127ABA7DF12D38CAA0C1B7442EEF3908AF`). It replaces HTML/source assertions with actual async `applyActivityMode` cases; root not modified by T18.

## Separate admin-auth gap

- Root `_authorized()` currently permits every client when `security.api_token` is empty; action-token policy is absent. Candidate O5 review found token scope checks passed, but its empty-token fallback needed the actual client address and had no loopback helper.
- Auth-only root-current patch: `handoff/T18-root-current-admin-auth.patch` (SHA-256 `A0335C3FF0B0319F840C794123525625B6DA84536D0669B96EC103D64B9D358B`); review pending. Committed root preimage is `98a9a1a7611af574caf20a88620c4aa3eb2e918a`, with `src/local_ai_hub/http_server.py` SHA-256 `4c10b31778ba89fa694c0029fc95b363af7acffc4c2caceb5e52ce4b9a9bff80`; latest sampled dirty root file SHA is `4CB8DED60199A410390831F633AE7E238EF07EDE6AA1562487D760628790DA35`. T20 must apply-check against that current state. It uses actual `client_address`, keeps configured global/action scopes, denies tokenless local mutation when tokens are configured, and leaves the read-only loopback `/api/mode` GET exception in routing. A mode-control token is denied the remote `status.read` GET scope. No status/cache/dashboard/telemetry changes included.
- Existing broad candidate admin source remains unintegrated; this turn tightened its auth predicate and added configured-token loopback denial, mode-control-vs-status-read scope, and a `do_POST` action-token integration case. The combined dashboard and O5 candidate selector passed 40 tests in 1.24s, including action scope, global token, malformed policy, loopback-vs-spoofed-header checks, and actual mode persistence/audit under the scoped token. Root patch review remains pending with T20; the audit portion requires T03/T13 owner coordination.
- T19 confirms no `tools/hubctl.py` symbol ownership; file is inherited/unverified. T19 lists `_activity_mode_request`, `_activity_mode_error`, and `main`; `main` warns only for unload failure and returns 0. No CLI edits; proposed root scope stays dashboard plus auth-only patch.
- Auth patch remains unapplied and untested pending review. T20 owns root integration/selector sequencing; T18 made no root write in this step.

## Owner release required

- `src/local_ai_hub/http_server.py`: shared T03/T13/T20 file. The auth-only proposal is isolated; obtain T03 review/release before applying. Admin route, status/cache, dashboard, and telemetry changes are excluded from it.
- Root's current `_require_authorized()` has no admin audit hooks; the candidate `do_POST` test asserts the action-token audit event. T20 was asked to combine a T03/T13 audit change before transferring that assertion, or record root audit acceptance as pending.
- `src/local_ai_hub/app.py`: `LocalAIApp.realtime_status` / status snapshot integration is T18 scope, but root-current code is divergent and the candidate diff is not safely separable as a minimal hunk. Rebase with the current `app.py` owner before transfer.
- `src/local_ai_hub/telemetry.py` and overlapping dashboard/accounting tests: root is dirty and hunks conflict. Obtain the relevant T03/T13/T20 owner release before transferring those hunks.

## Candidate evidence update (2026-10-01)

- Local AI Hub was unavailable per operator instruction and was not used. All receipts below are from the isolated T18 candidate only; root remains untouched by T18.
- `python -m pytest -q --tb=short tests/test_status_snapshot_quality.py tests/test_http_status_diagnostics_t18.py tests/test_telemetry_report_bounds_t18.py tests/test_debug_traces.py`: 38 passed in 11.90s, exit 0. The test fixture isolates `agent_state` from preceding status dependencies; `tests/test_debug_traces.py` now closes its SQLite connection.
- `python -m pytest -q --tb=short tests/test_dashboard_operational_surfaces.py::test_dashboard_reports_incomplete_vram_unload_after_gaming_pause tests/test_dashboard_operational_surfaces.py::test_operator_surfaces_report_all_transition_failures tests/test_http_admin_action_auth_t18.py tests/test_http_operational_mode_t18.py`: 40 passed in 1.24s, exit 0. This verifies actual async dashboard transition cases plus mode read/action-token/auth-route contracts in candidate only.
- Full candidate dashboard module: `python -m pytest -q --tb=short tests/test_dashboard_operational_surfaces.py`: 24 passed in 0.97s. Updated the intentional HTML golden and kept retention disclosure assertion on the served page, where the notice is emitted.
- Bounded loopback DB inspection: `python -m pytest -q --tb=short tests/test_db_query_bounds_t18.py`: 3 passed in 0.38s. Dashboard degraded/unknown status and polling visibility/backoff/jitter/timeout: `python -m pytest -q --tb=short tests/test_dashboard_operational_surfaces.py::test_dashboard_distinguishes_unknown_ollama_probe_from_offline tests/test_dashboard_operational_surfaces.py::test_dashboard_marks_degraded_live_status_and_retries_with_backoff tests/test_dashboard_operational_surfaces.py::test_dashboard_exposes_activity_mode_and_reports_http_failures tests/test_dashboard_operational_surfaces.py::test_dashboard_requires_server_confirmation_before_reporting_mode_update tests/test_dashboard_operational_surfaces.py::test_status_poller_respects_visibility_unchanged_state_and_jitter tests/test_dashboard_operational_surfaces.py::test_dashboard_api_fetch_has_bounded_request_timeout tests/test_dashboard_operational_surfaces.py::test_dashboard_wires_status_refreshes_through_backoff_poller`: 7 passed in 0.45s.
- Candidate admin event inspection + DB bounds: `python -m pytest -q --tb=short tests/test_agent_event_page_t18.py tests/test_db_query_bounds_t18.py`: 15 passed in 2.05s, including cursor hold, gap/reset, byte cap, serialized loopback HTTP, read-only query time/row/byte limits.
- Root-current test-only event-page patch: `handoff/T18-root-current-agent-event-page-tests.patch` (SHA-256 `DFC0A8A5E88308AF3AD919CD119624A0A3C71B22B0C89B47E4D5629F3120E902`); new file absent at root HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`. Root current source already has `AgentEventStore.event_page` and `/api/agent-state/events`; apply-check/test pending T20 slot.
- Accounting/MCP telemetry selector: `python -m pytest -q --tb=short tests/test_http_phase_telemetry.py tests/test_http_tool_accounting_rejections.py tests/test_mcp_compact_transport.py -k "response_phase_latency or terminal_client_result or tool_accounting or status_telemetry_compaction or mcp_telemetry"`: 10 passed, 2 failed, 18 deselected. Both failures expect action-specific `local_ai_status` output schema `anyOf`; candidate declares only a generic dict schema. T18 did not edit MCP schema ownership; T20 was notified to check whether T03 contract/schema integration supplies the missing declaration.
- Telemetry timeline paging: added the bounded cursor test from the existing T18 patch to candidate; after using non-path operation labels to honor telemetry privacy, `python -m pytest -q --tb=short tests/test_telemetry_timeline_paging_t18.py`: 5 passed in 2.58s. Current root has `get_timeline_page` and GET/POST routes, but its untracked test fixture still uses URL-like labels that privacy converts to `<path>`.
- Combined candidate telemetry integration: `python -m pytest -q --tb=short tests/test_telemetry_timeline_paging_t18.py tests/test_telemetry_report_bounds_t18.py tests/test_http_phase_telemetry.py tests/test_http_tool_accounting_rejections.py`: 17 passed in 7.97s.
- Root-current timeline test follow-up: `handoff/T18-root-current-telemetry-timeline-test.patch` (SHA-256 `E0DD1DDEA4C9319DF49F571BA2131CA81A88F0AD6AEDA4C0DD6317439DA3EE10`), preimage `tests/test_telemetry_timeline_paging_t18.py` SHA-256 `EC8087A2D8DAC48BE554A036B727352DAD584FB541E4E74E3AF5B6BA87B96316`. It replaces 13 URL-like fixture labels with privacy-safe labels. `git apply --stat` parses it; T20 must apply-check and run the root selector when slot is available.
- Telemetry privacy/error evidence: `python -m pytest -q --tb=short tests/test_telemetry_privacy.py tests/test_telemetry_error_metadata_privacy_t18.py tests/test_telemetry_error_classification_t18.py tests/test_telemetry_error_diagnostics_t18.py`: 9 passed in 5.60s.
- Candidate static checks: `git diff --check` passed on the edited telemetry/HTTP/dashboard/status/trace files; Python AST parsed 7 edited implementation/test files. Git emitted only its configured LF-to-CRLF notice for `telemetry.py`.
- Candidate `http_server.py` now denies tokenless loopback mutations when either the global API token or any action-token policy is configured; loopback unauthenticated read-only `GET /api/mode` remains an explicit route exception. Root-current auth patch now includes that predicate and a regression test; patch review and root integration remain pending.
- These bounded selectors do not establish complete T18 acceptance: root integration, retention semantics across all required states, and any shared-runtime or performance checks remain pending with their owners.

## T20 acceptance selectors (not run)

```text
tests/test_status_snapshot_quality.py
tests/test_http_status_diagnostics_t18.py
tests/test_debug_traces.py
tests/test_http_admin_action_auth_t18.py
tests/test_dashboard_operational_surfaces.py::test_operator_surfaces_report_all_transition_failures
tests/test_http_tool_accounting_rejections.py
tests/test_db_query_bounds_t18.py
```

T18 acceptance remains unverified. T20 controls further root test slots and patch review. T08 and T21 receipts are in their respective owner handoffs.

- Consolidated candidate acceptance run (excluding the known MCP output-schema failures above): python -m pytest -q --tb=short tests/test_dashboard_operational_surfaces.py tests/test_status_snapshot_quality.py tests/test_http_status_diagnostics_t18.py tests/test_telemetry_report_bounds_t18.py tests/test_debug_traces.py tests/test_telemetry_timeline_paging_t18.py tests/test_db_query_bounds_t18.py tests/test_agent_event_page_t18.py tests/test_http_admin_action_auth_t18.py tests/test_http_operational_mode_t18.py tests/test_telemetry_privacy.py tests/test_telemetry_error_metadata_privacy_t18.py tests/test_telemetry_error_classification_t18.py tests/test_telemetry_error_diagnostics_t18.py tests/test_http_phase_telemetry.py tests/test_http_tool_accounting_rejections.py: 137 passed in 24.61s, exit 0. This remains candidate-only evidence; root selectors not run by T18.

## Read-only root patch applicability snapshot (2026-10-01)

Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`. T18 performed no root writes and ran no root tests. `git apply --check --whitespace=error` against the live root returned:
- Pass: `T18-root-current-agent-event-page-tests.patch` (new file; root preimage absent); `T18-root-current-telemetry-timeline-test.patch` (preimage `tests/test_telemetry_timeline_paging_t18.py` SHA-256 `EC8087A2D8DAC48BE554A036B727352DAD584FB541E4E74E3AF5B6BA87B96316`); `T18-root-current-trace-retention-days-test.patch` (`tests/test_debug_traces.py` SHA-256 `958AB2CFD016669AF5FA499E0DB57261A08AFEE21E0E0BF786CB6EA11A3B65F3`).
- Pass: new test-only O5 patch `T18-root-current-admin-auth-tests-only.patch`, SHA-256 `86A9A48331086C266D9D2055E8C4FA1611B885A34BD2B43D9D6D1C4ECCBA9B1E`; adds `tests/test_http_admin_action_auth_t18.py` (currently absent at root). Candidate test SHA-256 `BB06BAFC7CE5CAFD851E1B96FCE3D30ECAD10D513D5C52010F762CF449475B25`. Apply-check only; root test not run. It requires O5 source/audit integration before execution.
- Fail/stale against current root: combined `T18-root-current-admin-auth.patch` (`http_server.py` hunk); operator behavior/display patches (dashboard or dashboard-test hunks); trace retention source patch (`debug_traces.py`); status diagnostics patch (`http_server.py`, test already exists); telemetry paging source patch (`http_server.py`/`telemetry.py`, test already exists); trace cursor, compatible poller, safe test delta, and one-line accounting patch (respective changed/existing hunks). Do not apply these older combined patches blindly; T20 should use current source integration and rebase only an explicitly selected delta.

Live root SHA-256: `src/local_ai_hub/http_server.py` `4CB8DED60199A410390831F633AE7E238EF07EDE6AA1562487D760628790DA35`; `tests/test_dashboard_operational_surfaces.py` `46F2816F1CE47665ED7B01F8C87B617C15B222F1AD1923BF736AE577492B31B6`; `tests/test_http_tool_accounting_rejections.py` `C13CFEBAF3B6632C385C5138CFB719B9D6C8BAD525ACF8257523010543DAEF5B`; `tests/test_http_status_diagnostics_t18.py` `AE835F8F1521BF57AC34616D83117F3E8EC5D7813D0A4464BEE8D4174CAF966C`; `tests/test_db_query_bounds_t18.py` `F809E0221994C1DD0AFFBF3C8E4C930F2320C02BA62BB50E6696CD44F9175B52`.

Additional root-current selector handoff: `tests/test_http_operational_mode_t18.py` is absent at root; its new-file patch `T18-root-current-operational-mode-tests-only.patch` has SHA-256 `4B04C4261D40AFA019F5DD77DA2E24661831F78654E85B0FCD04604147C2CED7` and `git apply --check --whitespace=error` passes. It requires the T18 mode transition source integration already present in the candidate. Together with the passing event-page, O5 auth test-only, telemetry fixture and retention-days patches, the intended post-slot root selector is:

```powershell
python -m pytest -q --tb=short tests/test_dashboard_operational_surfaces.py tests/test_status_snapshot_quality.py tests/test_http_status_diagnostics_t18.py tests/test_telemetry_report_bounds_t18.py tests/test_debug_traces.py tests/test_telemetry_timeline_paging_t18.py tests/test_db_query_bounds_t18.py tests/test_agent_event_page_t18.py tests/test_http_admin_action_auth_t18.py tests/test_http_operational_mode_t18.py tests/test_telemetry_privacy.py tests/test_telemetry_error_metadata_privacy_t18.py tests/test_telemetry_error_classification_t18.py tests/test_telemetry_error_diagnostics_t18.py tests/test_http_phase_telemetry.py tests/test_http_tool_accounting_rejections.py
```

This command is a proposed selector only; T18 has not run it on root. O5 source/audit hooks and explicit T20 root slot remain prerequisites.

## Candidate acceptance map

- Dashboard degraded status and recovery: `tests/test_dashboard_operational_surfaces.py::test_dashboard_distinguishes_unknown_ollama_probe_from_offline`, `::test_dashboard_marks_degraded_live_status_and_retries_with_backoff`, `::test_dashboard_requires_server_confirmation_before_reporting_mode_update`, `::test_dashboard_reports_incomplete_vram_unload_after_gaming_pause`; focused dashboard module receipt 24 passed, with the consolidated 137-pass command above.
- Status snapshot quality/degraded dependencies: `tests/test_status_snapshot_quality.py` covers shared deadlines, timeouts, offline versus successful probes, shape retention and cache behavior; included in the 137-pass consolidated run.
- Bounded admin inspection: telemetry report/error pages, timeline cursors, agent-event cursor/gap/reset/snapshot behavior and exact serialized-byte caps, read-only DB query time/row/byte caps; selector modules are named in the exact command above and included in the 137-pass receipt.
- Actual operator feedback: `test_dashboard_exposes_activity_mode_and_reports_http_failures`, `test_dashboard_requires_server_confirmation_before_reporting_mode_update`, `test_operator_surfaces_report_all_transition_failures`, plus HTTP mode pending/partial unload, deadline, in-process CUDA, defer-while-inference and authorization cases in `tests/test_http_operational_mode_t18.py`; consolidated run includes this module.
- O5 candidate behavior: eight cases in `tests/test_http_admin_action_auth_t18.py` cover scoped action tokens, remote mode-control POST, wrong-scope denial for config writes and remote mode reads, configured/global token behavior, malformed policies, loopback peer checks and redacted config. Candidate selector was 8 passed; root currently lacks this test file and action-token/audit source integration.
- Retention/status: `tests/test_debug_traces.py` covers configured retention days, terminal cleanup, live-work protection, trace page/cursor budgets and surfaced status; consolidated run includes it.

Root acceptance remains incomplete by direct inspection: current root `src/local_ai_hub/http_server.py` has the narrow loopback GET `/api/mode` exception in `_require_authorized` (lines 1171-1191), but no action-token scope resolution or admin authorization/result audit hooks. Root has not run the proposed selector. Candidate evidence and apply-checks do not prove root acceptance.

## DOM acceptance + T20 event-page update (2026-10-01)

- Added `tests/test_dashboard_mode_playwright_t18.py` and `tests/fixtures/dashboard_mode_playwright_t18.cjs`. The test loads the actual `DASHBOARD_HTML` in a headless Playwright page served by an ephemeral `127.0.0.1` fixture; all non-local requests are blocked. It opens the Controls menu and uses the actual token input/button and mode buttons. Assertions cover unauthenticated loopback `GET /api/mode`, degraded status pill (`success:false` status envelope), action-token header on mode POST, partial VRAM/accelerator/job projection, button release, 401 mode preservation, and 503 mode preservation.
- RED/GREEN: initial RED confirmed missing Playwright fixture runner; fixture-route diagnostic then found poller uses `/api/live/status?light=1` and controls are inside closed `details#controlMenu`. After aligning the fixture and using visible DOM controls, the focused browser + agent-event + DB-bound selector was **16 passed in 6.43s**. Full T18 candidate selector including the browser test: **138 passed in 30.78s**, exit 0. Node `v24.19.0`, bundled Playwright package under `.../dependencies/node/node_modules/playwright`, cached Playwright Chromium `147.0.7727.15`; no install/download and no user browser.
- Current root read-only snapshot after T20 writes: `agent_events.py` SHA-256 `02A25102B888B23FE99B8C508F59AEDD846BA24FD38A268BCC6893B0877E0A38`; `http_server.py` SHA-256 `CD2998708AFBEE64A22D8027AA86969E9C17A05967CBED8431BEE7A4F8D55FD5`; root `tests/test_agent_event_page_t18.py` SHA-256 `39BE401F6709F46F52FFAE904CF87D7DB5B9D329DF381206E98EB633C2CA0B68`.
- Root now statically serializes `AgentEvent` rows to dictionaries (`agent_events.py:627`) and the GET event route calls bounded `event_page`, carries `after_seq`/`through_seq`, sets error status and applies `_bound_agent_event_page` (`http_server.py:2176-2204`). No T18 root test/write. T20 owns current root verification.
- The earlier patch is now explicitly historical: `handoff/T18-pre-T20-agent-event-page-route.patch`, SHA-256 `C1D2914106A2593D9598CD20C50DA97390994161C71FE7130B16D132C0DA5A0C`, preimages `7BBA75A0A335A1BEF0370F636D65F36477BF0638261723A1778E4DC06BB8B949` and `15F497AEFDE4E2EDFF4D8B6BA158C87FF70731C7F40762F10BE64445646F927`. Its original apply-check passed; after T20 changed both files, live apply-check fails. Do not apply it.
- T20-provided root receipts: earlier event/auth selector had 17 failed and 24 passed in 8.06s; auth + operational-mode selector later had 21 passed and 2 failed in 8.63s because tests expected absent `_operational_mode_api` and `_redact_config_secrets` seams. T18 did not rerun root tests or add compatibility shims.

Current candidate test/artifact SHA-256:
- `tests/test_dashboard_mode_playwright_t18.py`: `FEB633BF2AEB86E4F8CF3299E7BA846DC468D269ED7D3F3A82D04AF65C97D14C`
- `tests/fixtures/dashboard_mode_playwright_t18.cjs`: `CC63D998923BCE8A736551AC4D9786F32F51048E530394AB9FE7855F90AA2736`
- `tests/test_agent_event_page_t18.py`: `95ADEFBA99FAE852A78AC8B1C9AC18F6FF579C2CDC96404FB6E4BA9A19A0F8C6`

## Latest resumed-goal receipt (2026-10-01)

Supersedes the earlier 137-pass candidate receipt: full T18 selector plus Playwright DOM acceptance is **138 passed in 30.78s**, exit 0. Focused artifact with exact test command, runtime, current root SHAs, static event-route evidence, pre-T20 patch disposition, and T20-reported root receipts: `handoff/T18-current-event-page-dom-evidence.md` (SHA-256 `CD1E8975E2168CB83C6D1671CC9597E44C969650BE267F5BA2D4BBF1D352E23E`). Current root event-page source is statically integrated by T20; root dynamic acceptance remains T20-owned and was not run by T18.

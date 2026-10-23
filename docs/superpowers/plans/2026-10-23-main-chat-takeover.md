# Local AI Hub: main-chat takeover and complete remaining work

> **For agentic workers:** Use superpowers:executing-plans for primary integration and bounded GPT-6 Luna subagents for disjoint implementation. Follow the checkboxes below; main chat owns Git, validation and runtime operations.

**Goal:** Preserve all transferred work in master, absorb the stopped workers, and complete every original audit/release/runtime/UI/data requirement with authentic evidence.

**Architecture:** One primary owns the installed single-owner Hub and canonical task/root. Reuse candidate-bound evidence, fix defects at their responsible boundary, preserve data and strict contracts, and validate bounded independent deltas before final integrated acceptance.

**Tech stack:** Python 3.11+, SQLite, standard-library HTTP, MCP, dashboard JavaScript, pytest, GitHub Actions and Git.

## Concrete working surfaces

- Ownership/evidence: this plan, the two linked original plans and the original external audit-remediation-checkpoint.json. Record each new command artifact and candidate before changing a checkbox.
- Readiness/lifecycle: `tools/hubctl.py`, `tools/doctor.py`, `tools/service.py`, `src/local_ai_hub/http_server.py`; begin with bounded `python tools/hubctl.py status --json` and the existing activation logs. Change only the diagnosed component, with its existing focused test.
- Task restoration: existing broker `local_ai_coord` task_get/task_budget_increase/task_resume/task_checkpoint actions and `tests/test_agent_task_budget_increase.py`, `tests/test_agent_policy.py`, `tests/test_http_user_acl.py`; no direct task-storage edits.
- Browser transport: `src/local_ai_hub/browser_bridge.py`, `src/local_ai_hub/http_server.py`, `tests/test_browser_bridge.py`, `tests/unit/test_browser_failure_envelope.py`, `tests/unit/test_browser_headless_capture.py`. Reuse the existing 8f source regression; run the explicit installed-Chrome gate only under the owned acceptance batch.
- UI: `src/local_ai_hub/dashboard.py`, the handed-off UI tests and `state/validation/live-ui-8f570873`; capture actual desktop/mobile and diagram/trace evidence under a new candidate-bound evidence folder. Never label a fixture/synthetic screenshot as live acceptance.
- Packaging/release: `tools/release_check.py`, `tools/selftest.py`, `tests/test_t19_packaged_sdk_smoke.py` and existing native validation runners. Required final commands are `python tools/release_check.py --allow-installed`, `python -m compileall -q src tools tests`, bounded owned full/affected pytest, and `python tools/selftest.py`; run only missing/currently invalidated checks and retain exact exit/source identity.
- Instructions: `src/local_ai_hub/generator.py`, `AGENTS.md`, `docs/INSTALL_PROMPT.md`, `docs/UPDATE_PROMPT.md`, `docs/HTTP_API.md`; keep policy changes synchronized and validate generator/contracts together.
- Every diagnosed code fix follows a small sequence: exact evidence; meaningful failing regression; minimal source fix; one owned affected validation; review; commit source/docs on master. Do not invent a repair file or test before the actual failing component is known.

## Authority, goal and ownership

The human requested on 2026-10-23: stop the worker chats, preserve and commit all current repository changes regardless of functionality, integrate their work into master, prepare a complete remaining plan, transfer all work to the main chat, then archive the transferred chats. Use GPT-6 Luna subagents.

The effective goal is now: main chat `01a15ec3-cf4b-7fc0-b81a-0ae7446ff8ff` owns all integration and completes the original F01–F24, R01–R16 and 100-item orchestration scope, including exact-candidate tests/package, actual installation/runtime/UI acceptance, preservation of data/config, genuine verification receipts and final closure. Preserve all existing work and failure history. A commit preserves work; it does not certify functionality.

The main chat is the sole Git writer, CPU runner and runtime mutator. GPT-6 Luna subagents receive disjoint bounded scopes; they do not independently commit, activate, restart, change modes, install dependencies or duplicate validation. The main chat reviews and integrates their work. Old worker chats must not resume automatically.

The existing main Codex goal remains active. The exposed goal tools cannot edit its objective: create_goal rejected replacement because the goal is unfinished; update_goal supports status only. This document records the human's expanded objective without resetting accounting or falsely completing the old objective. Update the displayed goal through a supported objective-edit mechanism when available.

Keep Hub task `audit-remediation-20261020`; no new task or counter reset. The previous integration chat `01a15f47-a804-7290-8d3b-f55b82fbb4b0` confirmed STOP, transferred ownership, paused its own unfinished Codex goal and reached idle. Its handoff is retained in the main chat and this plan.

## Preserved baseline at takeover

- Root/worktree: `C:/Users/Adam/.local-ai-hub`, the only registered worktree; branch `master`.
- HEAD before this planning commit: `1e54a5e28fed5eaa5715c0360304b0a415e34db2`; clean tracked/untracked Git status. No pending source changes need a synthetic commit.
- `d4fb8882`: integrated API/command/budget packet; `8f570873`: canonical browser failure `status_code`; `1e54a5e2`: ordinary Hub write clients may increase existing task budgets.
- Direct human authorization for the last change: integration user message `01a168a8-e150-7a22-a4a1-18b027c3b6cc`, "Nic takového tam nemá být - prostě to povol pro všechny". Normal authorization, wrong-token/read-only rejection, explicit root, increase-only maxima, owner/status/counters and atomic audit must remain.
- Current branch inventory: 392 local branches; the only non-archive branch is master. 124 historical archive branches are not ancestors of master. Some have already been adopted by squash/selective integration. They are preserved, not silently deleted or declared merged. They are not outstanding active worker branches. Reconcile genuinely missing changes before any future historical adoption; do not use an ours merge to conceal missing source or resurrect retired tenant/command contracts.
- Main's bounded process inventory found no live Python runner for the former integration cohort, budget adoption, release/package or activation scripts after the handoff. The live service is intentionally left running.
- The old integration chat reported service PID 39868, start 1792759215.1430092, canonical root/.venv http_server, RSS 188276736. This is a handoff observation, not a fresh health claim. Its latest hubctl JSON was online/version 5.0.0 but success=false/degraded=true. Diagnose the exact component before declaring readiness or restarting.
- At handoff Hub task was failed/watchdog: max 100000 tokens / 33000 seconds / 450 external calls; used 0 / 33240.86682920671 / 449. Main subsequently restored this same task through the supported broker as recorded below; the historical handoff is retained.

## Main-owned task restoration: completed

- `task_budget_increase` request `req_e21de487b627` succeeded, audit event `evt_f3534b8eae91499b82d49882d6bf066e`: compute maximum 33000 to 48000 seconds, external maximum 450 to 750; token maximum remains 100000. Used tokens/seconds/calls remained exactly 0 / 33240.86682920671 / 449.
- Post-increase `task_get` `req_0df7206fadb9` confirmed failed status and watchdog owner unchanged before resume.
- Separate `task_resume` request `req_30427f86f878` succeeded; same task active, canonical broker owner codex. No new task, synthetic receipt, direct task-DB mutation or reset.
- Independent read-only budget row after resume confirmed the same maxima and unchanged counters. Actual broker responses are retained as `state/validation/main-takeover-budget-increase.json` and `main-takeover-task-resume.json`; these are observations, not fabricated verification receipts.
- Checkpoint request `req_2f97213be078` succeeded with phase main-chat-takeover-runtime-acceptance, main owner, real evidence IDs and the remaining telemetry/UI/data/release blockers.
- Current bounded readiness observation `req_df70c1e655f6`: hub_online=true but success=false/degraded=true, telemetry.summary probe_timeout at 250ms. No healthy/complete claim. Read-only sqlite_master metadata retrieval on the 37851136-byte telemetry DB took 2.4996s; this is a discriminating latency observation, not yet proof of the specific query/lock cause. GPT-6 Luna is investigating source with no speculative edits, timeout inflation or TTL change.

## Evidence index and limits

### Current telemetry source checkpoint (not activated)

- Latest source supersedes the intermediate grouping candidate below. Sessions now fetch at most 100 headers in the same order and compute the original active/clean/crashed windows, then evaluate all six event metrics with one bounded compound SELECT (100 branches/200 bound parameters maximum). No JSON dependency, metadata join, broad grouping or data truncation was introduced. `session-compound-comparison.json` verified all fields for 100 real sessions in one read-only snapshot: grouped 76.412ms versus compound-plus-headers 28.524ms.
- `_decision_grade` now computes all scalar outcome/receipt/count/failure metrics in one scan; exact mixed negative/unknown/zero values and empty datasets have regression coverage. The window branch no longer computes a raw tool-accounting aggregate that it immediately discarded in favor of the unchanged daily-rollup/boundary calculation. Pricing completeness and signed counters retain their existing logic.
- Main final related cohort `integration-cohort-4feb155ddae9.json`: 126 PASS, exit 0, stable sources. It includes sessions/limit/empty/overlap, queue order/index, decision metrics, cohorts, token accounting, canonical rates, writer accounting, report bounds, contracts and status metadata. Earlier `1133ccc2668b` retained 124 PASS before the final sessions alternative.
- `measure_telemetry_summary_python_compound.json` binds telemetry.py SHA `d8e8d3b60bb9c179879e21aeb22d960b117efa1012493bc060d1451c275348e7`: process 38.505ms/23 SQL; window 217.527ms/26 SQL. Both single diagnostic observations are below 250ms without raising the deadline or cache TTL. They use explicitly stubbed writer counters and do not prove live server health. Next: commit, freeze current candidate, execute the complete serial suite once, then matching package/release and one activation followed by actual runtime/UI/data acceptance.
- Two disjoint Luna changes are present: sessions() uses one bounded CTE aggregation; the queue-age query retains exact newest-ID semantics while using existing idx_events_created. Main corrected an unclosed SQLite connection in the new regression fixture; strict warnings remained enabled. Red run `integration-cohort-43573e89670f.json` is preserved (6 PASS/1 FAIL). Corrected runs `d437c11ced31` (7 PASS) and `8056860b78cc` (31 PASS) exited 0 with stable sources.
- `measure_telemetry_summary_python_after.json` is a separate post-change diagnostic; original observation remains untouched. Current source SHA `17d46ec02e03811fcd4b153e85c4ed23fad196f83894c8ac9c45cd00ecd4df47`: SQL call count fell to 27/31, but process/window total latency increased to 485.200/417.388ms. The sessions aggregate took 465.105/116.730ms; EXPLAIN uses the existing event time index but materializes GROUP BY/ORDER BY temporary B-trees. Fewer queries do not establish a performance fix. Keep this source checkpoint unactivated while correcting the regression.
- Luna accidentally created duplicate planned task `task_9af1f6e89ce3` (`req_057516b2484a`, checkpoint `req_15390b5c1cfc`), contrary to the explicit no-new-task instruction. Main independently read it (`req_a3c066ea4a55`) and closed it through task_fail (`req_c64f1636c8e2`), status failed; no leases existed. Original audit-remediation-20261020 and its counters were preserved.
- Tool routing exception retained: Luna solve `req_2c5cf5449c5a` and main review_diff `req_1f1da42a00e9` returned semantic envelopes; the latter reported job_id=9 and generic review cautions. Backend/model/device execution was not exposed, so no claim of absent inference or a verified independent review is made. Do not repeat semantic Hub calls while the explicit no-inference constraint applies; deterministic source/test evidence controls acceptance.
- Follow-up `session-aggregation-comparison.json`: read-only same-snapshot comparison verified every returned field for all 100 sessions while grouping by unique session ID and moving final ordering to a bounded Python sort. Query-only timings were 114.030ms versus 76.122ms; one SQL temporary ordering B-tree was removed. Main applied this narrower grouping and retained exact session ordering, then ran `integration-cohort-a3a08eef1837.json`: 38 PASS, exit 0, stable sources. Current telemetry.py SHA `6c9a88c92e6343aef7238d0427881f34503bbfeac171ce8ba1f52a6666db3290`.
- Separate `measure_telemetry_summary_python_grouped.json`: process summary 85.130ms/27 SQL, window summary 329.539ms/31 SQL. Process diagnostic improved below 250ms, but window still exceeds the deadline. This remains a read-only diagnostic with stubbed writer counters, not installed/runtime acceptance. No activation performed. Next: resolve remaining window aggregation latency, validate current full candidate/package/release, then perform one authorized activation and actual runtime acceptance.

### Main-owned live UI and telemetry observations

- `state/validation/main-live-ui-1e54a5e2/observations.json` now records actual browser captures of all 11 panels at desktop 1440x1000 and mobile 390x844, with individual AX states, screenshots, geometry and times. Document scroll width did not exceed viewport width in these captures. Two initial loading states were retained and then re-captured only after the loading elements disappeared. The temporary viewport was reset.
- `runtime-binding.json` independently binds listener port 11435 to PID 39868/start 1792759215.1430092 and canonical root/.venv http_server command. All six relevant source-file raw hashes match candidate `268136bae0fae285c03d458d3d622df6ad361b133ab2808553847aa4db0388e2`. Git-normalized content also matches activated commit 1e54a5e2; the raw git/working-copy difference in telemetry.py is only CRLF and is retained explicitly. Observed RSS was 830918656 bytes; this one observation does not prove resource stability.
- `browser-errors.json` contains one actual error at 2026-10-23T12:55:34.708Z: dashboard status refresh failed / Failed to fetch. The UI truthfully showed both Healthy and Needs attention at different times, with incomplete telemetry when the latter was captured. No zero-error, stable-health or complete UI claim is made. Visible diagram flow, trace metrics and detailed interaction/visual review remain open.
- `state/validation/telemetry-readonly-measurements.json`: WAL DB, 100002 events, 2085 rollups and 3834 errors; simple aggregate/count reads took approximately 1–8ms.
- `state/validation/measure_telemetry_summary_sql.json`: source SHA matches actual telemetry.py. All 25 exact process-scope queries completed in 14.763ms total, all 28 window-scope queries in 147.928ms. Diagnostic journal_mode inspection returned OperationalError after 330.57ms and schema_version took 804.592ms. These two inspection statements are not the actual hot connection path; their latency does not establish a WAL/schema cause for the status timeout.
- `state/validation/telemetry-connection-setup.json`: the actual connect_sqlite helper, forced through a read-only connection, completed twice in 3.480ms and 1.117ms. It does not execute journal_mode. `telemetry-cohort-processing.json` separately measured actual cohort cursor iteration/materialization: process 124 events in 4.805ms, window 4714 events in 159.228ms. These independent observations do not establish the live callback's total latency or scheduler contention. Status request `req_7160b124f335` still returned telemetry.summary probe_timeout. No timeout/TTL increase or speculative product fix.
- The 12:55:34Z browser failure correlates with `state/logs/hub.log` at local 14:55:34: GET /api/live/status, OSError while writing response headers. The log omits exception text/errno/winerror. Existing _send already suppresses recognized client disconnects; a missing signature is not proved. Preserve the actual error, do not broaden suppression based on this evidence.
- `state/validation/main-current-preservation.json`: fresh read-only comparisons preserve config.toml, config.runtime.toml, operational_mode.json and both F02 active/quarantined row hashes against activation evidence. This is not full historical archive/data acceptance and is not a broker receipt.
- `state/validation/measure_telemetry_summary_python.json`: main executed Luna's reviewed diagnostic once under a 15s outer timeout. Production summary/decision-grade/session materialization ran against read-only SQLite without the store constructor; writer counters were explicitly stubbed, so this is not live writer/runtime acceptance. Process summary took 397.611ms/127 SQL calls; window(30 days) took 298.522ms/131 calls. Both exceed the live 250ms deadline. The earlier 25/28-query diagnostic omitted nested sessions() queries. Hash `2980bce204a16af9a437bc3aaeedce2339e3bde46283e5eb75139001be7f0e6a` maps to the per-session event aggregate, called up to 100 times. The 350.943ms query at line 1846 is the queue-age query (hash `8237a794abf618d7279ba340b02eebf158be5269de46100301bbe645f3fd5431`), not a cache aggregation. Main's separate read-only EXPLAIN returned `SCAN events`; the existing canonical idx_events_created is present. Two Luna implementations have disjoint method/test scopes: sessions aggregation and queue query access path. Both must preserve exact semantics and pass main-owned regression checks. No fix or restored live health is yet claimed.

- `state/validation/budget-access-coverage/coverage.json`: owner-produced composite, fingerprint `268136bae0fae285c03d458d3d622df6ad361b133ab2808553847aa4db0388e2`, 11843 unique cases = 11730 PASS + 113 SKIP, zero effective FAIL/ERROR. Main read the complete finalizer in bounded slices (SHA256 `7a784fafefe4aded9245cef505f0396da0337d7c44fe0f994f9af1ab8b7a0e26`) and independently read all four affected-family XML files: 80/44/21/64 cases, no failures/errors/skips. The finalizer checks whole-module AST equality outside explicit dedicated budget-authorization changes, exact generator text replacement, unchanged other collection identities and complete current case count. Its retained claim composes a full baseline, bounded AST delta and affected-case reruns; no new full-suite run or broker receipt is claimed. The producer was not rerun.
- Directly adopted native cohorts: `integration-cohort-1c2efaa25533.json` 80 PASS; `248807fb3940` 44 PASS; `947db0a3f1e4` 21 PASS; `81a3ca31c88b` 64 PASS. Each exit 0 and sources_unchanged=true. Preserve red run `7337d5d39978` and timeout `7ca13b68cfac`; neither becomes PASS.
- Browser source epoch `state/validation/browser-failure-coverage/coverage.json`: fingerprint `7f193775f8e429aafcb3beea1a6467703079d002c51c61ab3fd85a9f87f1e557`, composite 11724 PASS/113 SKIP. Main read the 98-line finalizer at SHA256 `09c59f85fbe7e88477104295f35635eaff6a607c325cbb73d60702d57a536c49`. It binds exact substitutions, collection and 125 authentic rerun cases (124 PASS/1 SKIP); it does not prove production acceptance.
- `state/validation/final-release-1e54a5e2/run.json`: main read actual release_check --allow-installed, compileall and selftest records: exit 0, unchanged sources. `fresh-package-1e54a5e2/receipt.json` and `native-observation.json` retain sdist to wheel to fresh-venv SDK success, production_release_approved=false. Main independently verified both package hashes, all five command-log hashes/exit-0 records, and all 1308 declared source-file hashes with zero current mismatches. See `state/validation/main-package-artifact-adoption.json`. This verifies retained artifact/manifest integrity without rerunning producer commands; it does not grant runtime/release acceptance.
- `state/validation/activation-1e54a5e2/run.json`: official stop/start already performed. Handoff reports config/mode hashes, both F02 rows and all budget columns preserved. Do not repeat activation merely to take ownership.
- Offline backup: `D:/LocalAIHubRecovery/audit-remediation-20261023-d4fb8882`, 36 files, 33576814846 bytes, verified copy hashes; backup is preserved. Do not delete WAL/SHM/journal files or quarantine data as routine cleanup.
- `state/validation/runtime-8f570873`: historical doctor/hubctl success. `mcp-wire-8f570873/run.json`: genuine stdio initialize/list seven tools; main adopted actual exit-0 handshake output. These are not automatically current 1e54 runtime acceptance.
- `state/validation/live-ui-8f570873`: handoff reports 11 real desktop panel screenshots/states. Mobile, visible diagram flow and trace performance remain unproved. The earlier browser timeout has unknown outcome; inspect its actual producer before any repeat.
- Original audit/checkpoint root: `C:/Users/Adam/.codex/visualizations/2026/10/20/01a1584b-7f42-7240-9b36-22be709b1257/`. Original checkpoint `audit-remediation-checkpoint.json` and older plan ledgers are historical until reconciled. Preserve their observations and failure history.

## Execution order and acceptance

### A. Preserve and complete the ownership transfer

- [x] Obtain STOP acknowledgment, final checkpoint, idle status and released Git/CPU/runtime ownership from the old integrator.
- [x] Verify master, clean starting state and no other registered worktree; retain all historical refs.
- [x] Preserve the complete takeover plan and links from both original plans in the takeover planning commit. Include all current non-ignored repository changes, regardless of functional readiness. Runtime data, credentials, caches and backups remain outside the source commit.
- [x] Old integrator archived after takeover planning commit `4dc0c31f` was verified in clean master and the main chat assumed all remaining work. API/command/UI/RAG/planning/crash chats already archived remain archived. Archival records a transfer, not completion of the unfinished release.
- [ ] Adopt a scoped writer lease/checkpoint under the same task using supported coordination. Never release a foreign lease blindly or derive an owner from credentials.

### B. Diagnose current runtime; restore the original task safely

- [ ] Read current status/readiness/component failures, installed editable/module/process provenance, startup logs and resource usage without inference or restart. Bind to HEAD/source hashes and the actual live PID/start identity. Explain success=false/degraded=true before claiming healthy.
- [ ] If a repair is needed, assign one narrow source slice to a GPT-6 Luna subagent, retain a regression and integrate on master. Main alone runs the combined owned validation.
- [x] Invoke supported broker task_budget_increase exactly once on the activated policy for the original task, with explicit root and human audit reason: accepted maxima 48000 seconds/750 calls; no direct task-DB mutation.
- [x] Verify accepted maxima, unchanged counters, preserved failed/watchdog state before the separate successful task_resume, authentic audit event and the subsequent active task/checkpoint under main ownership. See exact requests above. Runtime readiness remains separately open.
- [ ] If a request outcome is unknown/in_progress, inspect the original execution/receipt; never repeat a possible mutation. Preserve any new denial and diagnose it rather than bypassing the gate.

### C. Reconcile every original audit item

F01–F24 remain the exact original findings in `2026-10-20-audit-remediation.md` and `current-audit-dispositions.json`; existing implementation claims are evidence pointers, not fresh release acceptance. Reconcile each individually:

- [ ] F01 context/task ownership: explicit binding, no implicit cross-root/session adoption.
- [ ] F02 historical memory/data disposition: exact quarantined mem_cf5858e8e065 and active replacement mem_db308e7f307d rows; preserve corrected audit interpretation.
- [ ] F03 atomic budget increments.
- [ ] F04 fail-closed durable budget errors.
- [ ] F05 serialized configuration updates.
- [ ] F06 absolute request-head deadline.
- [ ] F07 bounded response bytes and total metadata deadline.
- [ ] F08 correct coverage denominator and bounds.
- [ ] F09 exact dashboard configuration types; numeric-bool defect distinguished from malformed objects already rejected.
- [ ] F10 canonical identities without coercion/truncation and strict flags.
- [ ] F11 identify the exhausted budget channel.
- [ ] F12 diagnostic artifact availability and recovery truthfulness; logs remain opt-in.
- [ ] F13 bounded context delivery and nested completeness/identity.
- [ ] F14 canonical diagram/source metadata precedence.
- [ ] F15 full parallel-batch preflight and supported forwarding.
- [ ] F16 duplicate-ID rejection and aggregation of every result.
- [ ] F17 reference fallback preserves reference semantics and completeness.
- [ ] F18 async finalization fenced by attempt/state/lease/expiry.
- [ ] F19 explicit boolean success required.
- [ ] F20 DB-close failure cannot skip local cleanup.
- [ ] F21 dependency audit completeness/provenance; scan remains explicitly incomplete/non-clean where applicable.
- [ ] F22 package-manifest root confinement, size and reparse checks.
- [ ] F23 resident model inventory unknown/none/loaded/stale truthfulness in actual UI.
- [ ] F24 canonical memory scope/kind filters. Separately verify the later query-is-required UI incident and its integrated source packet.

Retain all recommendation boundaries; no silent scope reduction:

- [ ] R01 installed token/loopback boundary and capabilities; incorporate only the explicitly authorized budget exception.
- [ ] R02 bounded CUDA/process lifecycle; distinguish hardware/model-quality proof from CPU/source tests; no unauthorized inference/pulls.
- [ ] R03 telemetry drain versus persisted accounting; exact current observations.
- [ ] R04 shutdown, cancellation and subprocess-tree cleanup; current lifecycle evidence.
- [ ] R05 actual Windows hosted CI result, or explicit human disposition if remote execution is unavailable; source YAML is not a CI run. Do not push merely to manufacture a result.
- [ ] R06 branch baseline/ratchet; retain all thresholds and current coverage evidence.
- [ ] R07 bounded cohesive extraction already implemented; map original requested extent and record any explicit disposition, without calling an incomplete full monolith split complete.
- [ ] R08 current schemas/help/contracts and actual seven-tool MCP transport; historical eight-tool manifests are not current inventory.
- [ ] R09 generated architecture answers against authentic source-symbol goldset; signed savings require current baseline, and retrieval tests are not answer-quality proof.
- [ ] R10 semantic fidelity evaluation; four historical contract evals are not semantic truth.
- [ ] R11 actual visible diagram ingestion/review flow, project root confinement, independent failures and owner-global docsets; metadata-only tests insufficient.
- [ ] R12 current pinned toolchain/dependency scan/SBOM with exact 13 previously accepted exceptions, raw_scan_clean=false where applicable; no new finding silently accepted, no incomplete SBOM declared complete. Resolve missing Ruff honestly.
- [ ] R13 reconcile both original plans and external checkpoint to exact commits/evidence, preserve history and this takeover.
- [ ] R14 complete integrated candidate tests/package/install/live release acceptance and genuine receipts.
- [ ] R15 trace visibility plus actual bytes/cadence/main-thread metrics; historical 81 requests/0 detail requests prove only their observation window.
- [ ] R16 workspace review/root validity/cleanup classification. Historical 163-workspace review deletes nothing; no cleanup without provenance and applicable authorization.

### D. Preserve current and historical data/config

- [ ] Establish fresh active DB plus four archive identity/row/hash baseline before any maintenance; exclude sidecars from the archive-content comparison, while preserving the complete consistent SQLite backup set as needed.
- [ ] Reconcile independent file identities, no junction/symlink/hardlink surprises, current records including new writes, both F02 rows and config/mode hashes. Creation-time historical contents remain NOT VERIFIED where no authentic creation proof exists.
- [ ] Compare after any authorized operation and verify HTTP/readiness functionality. Retain original damaged image and recovery records. No overwrite from a stale backup, no record-loss masking, no deletion of foreign dirty files, quarantine or configuration.

### E. Complete integrated UI and runtime acceptance

- [ ] Verify current HTTP endpoint behavior, auth failures, readiness/status/resources, exact installed/module/PID provenance and real MCP stdio handshake/list/calls, all bound to current candidate. Preserve seven-tool surface and intentional public-command removal; internal CommandBroker remains.
- [ ] Review all 11 dashboard screens at desktop 1440 and mobile 390 using actual current service; persist candidate/PID/time, DOM/screenshots, viewport, console/network failures. Test query-required regression, navigation, forms, status/error/degraded presentation and accessibility where required by original UI plan.
- [ ] Execute R11 diagram flow and R15 performance observations, preserving explicit limitations instead of inventing success. Inspect uncertain earlier browser operations before repeating.
- [ ] Record bounded CPU/RAM/process-tree behavior and shutdown/reconnect/cancellation as required. Do not change Gaming/active mode or start GPU/inference/pulls merely for validation.

### F. Final current-candidate validation and release

- [ ] Freeze one exact current source snapshot and collection. Review composite finalizers and their affected-case coverage/AST proofs; retain original failures/timeouts/skips. If delta coverage is insufficient, run one complete owned validation using the established fixed bounds; no timeout inflation, deleted assertions, skip/xfail or lowered coverage/security gates.
- [ ] Match every skip to its explicit reason and separate unmet runtime acceptance. Native evidence is never a broker receipt; exact node identity, counts, exit status and source stability must remain authentic.
- [ ] Run only required outstanding release_check/compile/selftest/lint/package steps for the final candidate, reusing sufficient fresh evidence. Bind sdist/wheel manifests and actual installed smoke to those exact bytes; a test environment is not production acceptance.
- [ ] Attach genuine command_execution_record.v2 artifacts/receipts under the exact root/task/owner, verify required criteria through the supported broker and call verify_completion only when the original contract is satisfied.
- [ ] Commit final source/docs on master, verify clean tree and ancestry of every current worker packet, update both original plans/checkpoint with each F/R result and unresolved external disposition. Local integration does not imply remote push/publication.
- [ ] Audit all original 100 orchestration items against the canonical plan; no inference from a green summary. Preserve accepted limitations with explicit authority and evidence.
- [ ] Mark the main goal complete only after every requirement is proved or explicitly resolved by the human; archive only transferred/finished worker chats. Do not archive the main chat while it owns unfinished work.

## Operating rules for subsequent work

No duplicate chats/tasks, reset/stash/clean, fabricated XML/receipts/PASS, constant tenant identities, compatibility shims for retired contracts, weakened auth/path/root/capability gates, unrequested mode changes or blind restart. Preserve supported source/runtime distinction. Use existing evidence first, bounded exact slices, one writer and disjoint GPT-6 Luna implementation scopes. Update this checklist as authoritative evidence changes; do not report old candidate counts as current after a source change.

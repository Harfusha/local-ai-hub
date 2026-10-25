# Post-Gemini Review and Deployment Plan

> **For agentic workers:** Use superpowers:executing-plans for sequential implementation and acceptance. The main chat owns Git, validation and deployment.

**Goal:** Independently verify and finish the original Local AI Hub scope after Gemini, integrate all needed work on master, and deploy the verified candidate.

**Architecture:** Keep the current single-owner installation and existing implementation. Review changed behavior and original requirements before fixing concrete defects; bind source, package and live evidence to the final candidate.

**Tech Stack:** Python 3.11+, SQLite, HTTP/MCP, Windows, pytest, Chrome.

**Spec:** Original 2026-10-20 audit-remediation plan (F01–F24/R01–R16), 2026-10-13 100-item master plan and their referenced specifications.

## Constraints

- Main chat remains sole integration writer and validation/deployment owner.
- Preserve operator-authorized clean reset: never restore old databases, history, counters or receipts. Preserve configuration, mode and new records.
- No stash/reset/clean, blind historical merges or deletion of archival refs.
- Keep original timeouts, assertions, security/data contracts and coverage thresholds; investigate changed tests instead of accepting weaker gates.
- Keep native evidence, full-suite evidence, package evidence, live runtime and real browser acceptance distinct.
- Do not resume former worker chats or duplicate existing Agent OS tasks.

## Verified starting point

- Root C:/Users/Adam/.local-ai-hub, master 4272be0d9aba15145d5dbbca9510b8f68afe136f; clean working tree and one registered worktree.
- Nine Gemini commits follow 75b9a1b8; four production modules and twelve test modules changed, plus acceptance documentation.
- Gemini full epoch declares 12,205 unique nodes: 12,090 PASS/115 SKIP/zero FAIL/ERROR. Its unchanged finalizer is promising evidence; independently verify the actual inputs, selected phases, artifacts and resumed-run lineage.
- The adopter hardcodes release_acceptance=true and a terminal exit assertion. Those fields do not establish runtime/UI/package acceptance.
- The initial status declared COMPLETE while original items #7/#43–45 were pending operator clarification; current browser claims refer to older captures and fixtures. On 2026-10-25 the operator explicitly decided to keep those internal features retired. This resolves that scope question without restoring the public command tool.
- Gemini increased MCP reads from 8s to 30s and loopback HTTP from 5s to 15s. Review and restore original bounds with meaningful isolation/regression evidence.
- Hub coordination/search transport failures were terminal before write; bounded native fallback is recorded. A later compact health request was transiently unavailable; do not retry in a loop.

## Work sequence

- [ ] Audit every Gemini production/test change, including HTTP unknown-route body handling, task-worker shutdown, parser circuit-breaker skips and global subprocess/time mocks. Prove concrete failures before fixes.
- [ ] Independently adopt full-suite manifests/XML/source/config/helper bindings and actual resume lineage. Preserve all authentic failures and distinguish raw JUnit reports from unique nodes.
- [ ] Inventory local/remote/archive refs and untracked/ignored deliverables; classify nonancestor work by actual content and existing adoption records. Integrate genuine missing units without reintroducing retired behavior.
- [ ] Correct overstated acceptance documentation and evidence producers; retain historical outputs unchanged.
- [ ] Resolve test weakening and actual defects with regression tests at original bounds; run one combined relevant cohort and lint, then commit bounded fixes. First unit: real unknown-POST socket test failed on the Gemini implementation; early 404 restored without accepting the advertised body. Combined six-file cohort passed 115 tests with 21 original parser-unavailable skips at the original 8s MCP/5s HTTP bounds. Parser availability remains an explicit follow-up, not proven parser acceptance.
- [ ] Reconcile every F01–F24, R01–R16 and enhancement 1–100 against authoritative current evidence; track unresolved retired-feature decision explicitly.
- [ ] Freeze final source and validate matching full suite, branch ratchet, release checks, compilation, selftest, dependencies/security and wheel/sdist bytes. Do not rerun a current valid epoch without a concrete reason.
- [ ] Verify isolated wheel install and smoke, including the distinct full canonical seven-tool contract.
- [ ] Capture fresh post-reset data/config baseline, activate final candidate through official tooling, and verify provenance/PID/readiness/HTTP/MCP/doctor/status/resources and preservation.
- [ ] Verify actual current Chrome eleven-panel desktop/mobile behavior, R15 measurements and R16 non-mutating workspace proposal; fixtures and source checks remain separate evidence.
- [ ] Commit final truthful acceptance records, verify master/working tree/ref dispositions, and close the existing goal only when the original scope is proven or explicitly superseded.

## Initial evidence pointers

External evidence root: C:/Users/Adam/.codex/visualizations/2026/10/21/01a15ec3-cf4b-7fc0-b81a-0ae7446ff8ff.

- current-fullsuite-20261024T191809Z/run.json and coverage-v3.json
- current-fullsuite-29f548ea-adoption.json and adopt_current_fullsuite_29f548ea.py
- release-verification-29f548ea.json and wheel-smoke-29f548ea.json
- served-dashboard-acceptance-29f548ea.json
- live-ui-20261023T223333Z/panel-metrics-20261024/summary.json
- owned-check-post-gemini-rejected-body-red-20261025T092213Z (authentic regression failure)
- owned-check-post-gemini-http-and-contracts-20261025T092235Z (115 PASS/21 dependency skips; stable source/config)

The original takeover chronology and checkpoint remain available; current verified evidence takes precedence over historical claims.

## Additional operator priorities and Agent OS contract (2026-10-25)

Agent OS task: `post-gemini-audit-20261025`, created through `local_ai_coord`; the existing Codex goal remains active with its counters preserved. User-supplied analysis: C:/Users/Adam/Desktop/Multigravity/profiles/Adam/home/.gemini/antigravity/brain/b6413c56-4e5f-4dd0-9904-c0fe2af5d377/issues-and-plan.md.

The analysis is a source of hypotheses, not proof: `except Exception` excludes KeyboardInterrupt/SystemExit; sleeping yields CPU; file-lock retries observe other processes and cannot be replaced by an unnotified process-local Event. Current persisted operational mode is Active, revision 6. Never force a different mode to fit the report.

### Unreleased inventory, verify before preparing 5.1.0

- [x] Managed package/global CLI registration: inspect setup/CLI installation and test outside-checkout resolution; isolated install remains distinct from current canonical install.
- [x] Windows batch resolution and denied-Task-Scheduler logon fallback: `tests/test_setup.py::test_run_resolves_windows_batch_executables`, `tests/test_service_startup.py::test_denied_scheduler_keeps_user_logon_startup`; inspect actual startup ownership separately.
- [x] Lazy offline tokenizer: `src/local_ai_hub/code_tokens.py::offline_encoding`, `tests/unit/test_calibrated_tokenizer.py`; test actual cold CLI import/help without downloads.
- [x] Generic AMD Radeon integrated detection: `src/local_ai_hub/hardware.py`, `tests/test_integrated_acceleration.py::test_amd_shared_memory_names_use_integrated_profile`; no claim about physically absent AMD hardware.
- [x] Pointer-sized Windows Job handles and actual limits: commands/process utility declarations and `tests/test_integrated_acceleration.py`; distinguish mocked API contracts from real Windows child enforcement.
- [x] AST outline confinement: deterministic/services dispatch and `tests/test_new_capabilities_and_hardening.py::test_ast_outline_rejects_paths_outside_root`; include actual symlink/junction evidence or explicit unavailable capability.
- [x] Benchmark responses: `benchmark.py` already calls `model_quality.evaluate_case` on actual response text. Run success/wrong-response/error/no-evidence tests; fixtures do not establish live model quality.
- [x] Shadowed/unused definitions and annotations: inspect the actual CI/static gates and execute them on current bytes; raw exception/line counts are not defects.

### Immediate implementation boundaries

- [x] Supervisor: interrupt long health/backoff/cooldown waits without adding idle polling or locks in the signal handler; preserve child identity and cleanup. Authentic run-loop RED recorded in `owned-check-parser-and-supervisor-regression-red-20261025T093415Z`.
- [x] Client: wake cancellation-bearing GET warming/recovery delays, preserve canonical cancellation flags, deadlines and single transport attempt; two authentic REDs in `owned-check-client-red-parser-supervisor-check-20261025T094025Z`.
- [x] Operational-mode OS file-lock/replace contention: classify all three retries; retain cross-process fencing and bounded deadlines rather than cosmetic Event substitution.
- [x] Parser availability: actual isolated Python parse succeeded while availability returned false (`owned-check-post-gemini-parser-availability-probe-20261025T092636Z`). Probe availability inside the guarded worker, keeping native imports out of the Windows 3.13+ parent and failures explicit.
- [x] Critical exception boundaries: eliminate scope-dropping/duplicate-write TypeError fallbacks in service consistency decisions; distinguish expected evidence persistence failures from unexpected defects without logging command payloads or manufacturing receipts.

R05/R09/R10/R11/R14 and current browser/data/package acceptance remain open until their original requirements have matching evidence. Medium/low-priority 5.2+ decomposition and speculative backlog items remain separately identified; do not redesign monoliths merely from file length.

### CI workflow defect and interrupted validation epoch

GitHub run 39350824277 rejected the workflow before creating jobs: the `runner` context is unavailable in job-level `env`. Current source retained both invalid COVERAGE_FILE expressions. Authentic actionlint 1.7.12 reproduced both errors, then passed after moving these paths to the supported `github.workspace` context. Step-level runner.temp expressions remain valid. This repairs workflow syntax; actual hosted Windows 3.11/3.14 execution remains OPEN.

The first fresh epoch, `current-fullsuite-20261025T101840Z` (362482e3, candidate cf0a594bb314da141afe384e5ea53528e67276a79b5bbde1e81f236253be8db7), completed shard 0 with 378 PASS / 1 FAIL / 1 SKIP. The owner then cancelled the driver before the next shard for the confirmed workflow defect; `owner-cancellation.json` records zero survivors. The raw run remains unchanged and is not a full-suite PASS.

Its real failure exposed a test double in test_t10_acceptance.py that omitted the parser's keyword-only source_key parameter. The double now accepts and forwards that identity; syntax-error/fallback assertions remain unchanged. The combined actual-parser/index regression cohort passes 176 tests, no skips/failures/errors; exact logs are retained in parser-index-syntax-contract-green.xml and owned-check-parser-index-syntax-contract-green-20261025T102211Z.

### Real model evidence remains bounded and incomplete

Installed inventory confirmed qwen2.5-coder:7b and qwen3.5:9b without downloads. The local 7B review of the CI/fixture fix produced no actionable findings but unstructured output; the Hub correctly marked it usable=false, semantic_truth_verified=false (req_6a6c960ab6d3). It is advisory, not semantic acceptance.

The three-case source-grounded architecture-answer rubric was persisted before inference. A 7B reasoning override was rejected below the configured quality floor (req_1cb16c0ea6ea). The corrected 9B request was rejected at model preparation with post_unload_vram_unavailable (req_879c7b318897). No generated architecture answers exist for these requests; R09/R10 remain OPEN. Preserve resource admission and quality limits; do not lower them, repeat identical calls, pull models or claim a fixture result closes this gate. Request/response artifacts are external under architecture-gold-c5577c4d-*.

### Current targeted evidence (not final release acceptance)

Commits a9490cd6, 6b6125a5, 1ea45f80 and ccc616eb contain the independently tested fixes. Operational-mode retries remain bounded cross-process lock contention, not replaceable by an unnotified Event.

- owned-check-interruptible-scope-corrected-20261025T095058Z: 74 PASS, no skips/failures/errors.
- owned-check-interruption-and-consistency-integration-20261025T095741Z: 110 PASS, no skips/failures/errors.
- owned-check-unreleased-eight-targeted-20261025T095156Z: 203 PASS, 2 unavailable-tokenizer-data skips.
- owned-check-unreleased-eval-and-link-proof-20261025T095412Z: 7 PASS, 43 deselected, including a real Windows junction escape.
- owned-check-post-gemini-source-hygiene-final-20261025T095644Z: src/tools and changed tests pass static analysis.
- owned-check-windows-owned-job-tree-proof-20261025T100309Z: 2 PASS with actual owned Windows children/grandchildren.
- Managed/global outside-checkout CLI probes: owned-check-unreleased-cli-outside-checkout-20261025T095604Z and owned-check-unreleased-global-cli-20261025T100236Z, both exit 0 without PYTHONPATH.

Each owned check records actual exit, logs and stable source/config identity. Native records are not broker receipts. Cohorts overlap; counts are not additive. Former parser-unavailable skips now exercise the actual parser. Two cached-tokenizer accuracy cases remain unavailable, not verified. HKCU Run fallback exists; reboot/logon execution remains unobserved. Failed runs remain preserved. Package version remains 5.0.0; Unreleased inventory prepares 5.1.0 without claiming publication or final release acceptance.

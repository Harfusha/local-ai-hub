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
- Current status declares COMPLETE while original items #7/#43–45 remain pending operator clarification; current browser claim refers to older captures and fixtures.
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

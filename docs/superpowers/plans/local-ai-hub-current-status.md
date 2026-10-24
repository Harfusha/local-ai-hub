# Local AI Hub: current acceptance state

Updated: 2026-10-24. Owner: main chat `01a15ec3-cf4b-7fc0-b81a-0ae7446ff8ff`.
Status: IN PROGRESS. Complete release acceptance is unproved; the existing Codex goal stays active.

## Current source and installation

- Branch: `master`; last activated/package payload from `b143d0014a842cba8c70dfe8ddc3f911247dea77`. Current checkout adds F08 MCP projection, F11 budget diagnostics and F12 string-path artifact-directory corrections plus audit regressions. These changes have not received fresh installed-runtime acceptance; the old wheel/sdist are not a release of the whole current checkout.
- Canonical checkout: `C:/Users/Adam/.local-ai-hub`. Main owns Git, commands and runtime. Archived former workers remain archived; bounded Luna subagents implement disjoint work only.
- The operator intentionally deleted old runtime state and recovery data. Do not restore history, old task counters or databases. Preserve configuration and new post-reset records.
- Current wheel SHA: `1f5859278e59346b30bcb1edc279e03c435686ccb4a83e4e3a838dc7d9e30d88`; sdist SHA: `83d3b0593f9eb4ffdba1b357344bc9c067bab10df39731c30b6ea60b5ea8b98f`.
- Fresh hash-enforced wheel install, pip check and installed MCP smoke passed. Reduced smoke profile exposes five tools; canonical seven-tool runtime acceptance is a separate scope.
- One official activation completed. Observed loopback listener PID 49980, canonical root `.venv` command. Served dashboard matched exact current editable bytes including the actual CSP nonce. This is the recorded activation identity, not a continuously refreshed health claim.

## Verified evidence and limits

- Complete-suite baseline: 11,849 unique nodes, 11,734 PASS / 115 SKIP / 0 FAIL / 0 ERROR, candidate `b7b00601e04968b69b1806e6f2ff36a784e018618354d78d25e4e8983dab7210`. Later source deltas are separate; no claim that this was a full run of b143d001 bytes.
- Later genuine regressions include 15 SDK explicit-root tests and 37 diagram/dashboard tests. Current release check, compileall and selftest passed with stable sources and unchanged configuration.
- F03/F04 now have actual separate-process durable verification: 25-PASS combined budget cohort, including two concurrent child processes and exhausted-row read/write fault cases; zero failures/errors/skips, no timeout/config drift. Policy source is unchanged. This closes those source/test findings, not full release acceptance.
- F05-F09 source/test acceptance adds 255 unique PASS (254-case cohort plus later 180-case settings run with 179 overlaps), zero failures/errors/skips. Actual loopback deadlines/body caps, authenticated follow-up, config writer faults and all exposed setting types are covered. F08 had genuine 2-FAIL red and now marks inconsistent match counts unavailable; its production delivery remains a final-candidate gate.
- F11/F12 source/test acceptance: 110-PASS related cohort, zero failures/errors/skips, stable source/configuration and no timeout. Real red proved missing budget counters and a new string-path artifact-directory crash. Current guards preserve exhaustion admission/flags and report the exhausted channel first; real paged artifact recovery is byte-exact. Earlier fixture/preview-assumption failures remain retained separately. Native evidence is not installed-runtime or broker-receipt acceptance.
- F01/F15/F16 source/test acceptance: 94-PASS related cohort, zero failures/errors/skips; real simultaneous MCP sessions use actual authenticated isolated HTTP dispatch, close and initialize new connections after a fixture task completes through verifying. Simultaneous read commands never perform implicit task lookup. Entire batch option catalog, preflight rejection and reverse completion aggregation are covered. F02 gains real two-root default repository-memory checks, while its current imported-data audit remains open. No production state or model was used by these fixtures.
- Actual diagram dialog opened/closed on desktop 1440x1000 and mobile 390x844. Installed-model/no-download notice precedes Run. No upload, capture or inference was submitted. One bounded nontruncated opening interval contained only a GET. Ordinary-dialog reset is covered by executed Node regression, not additional live browser proof.
- Earlier eleven-panel/detail traffic measurements remain bound to their earlier dashboard source; no controlled before/after performance or current model-quality result is claimed.
- Thirteen new control-database online backups were made before activation. All file identities/configuration hashes and integrity checks matched. Initial retention comparison FAILED and remains retained. Later semantic comparison found no missing canonical keys: source index 12,029 to 12,037; RAG chunks 34,486 to 34,570; five task documents preserved. Both FTS families matched canonical keys and producer-format text hashes exactly; trigram differences matched one changed task document. There were 9 changed source texts and 115 changed chunk texts during live activity. This establishes current semantic consistency, not historical SQL cause, immutable content preservation or a complete data-preservation PASS.
- Exact thirteen operator-accepted optional advisory exceptions remain separately recorded; unaccepted findings must not be ignored. Historical advisory timestamps, incomplete native SBOM scope and raw_scan_clean=false must remain visible.
- Native command/evidence artifacts are not broker verification receipts. The intentionally removed old task cannot be reconstructed with fabricated counters or receipts.

## Next actions, in order

1. Reconcile remaining F02/F10/F13/F14/F17-F24 / R01–R16 and all original 100 items against exact current source and authentic evidence. F01/F03-F09/F11/F12/F15/F16 are closed at their source/test boundary; full release acceptance is separate.
2. Finish remaining source fixes, then freeze the final candidate and regenerate matching integrated validation/package evidence. Retain semantic data comparisons and their original failed observations; mutable FTS rowids are not semantic preservation identities.
3. Complete missing current runtime/MCP/health/resource and integrated-candidate gates; diagnose intermittent status failures without larger deadlines or weaker assertions.
4. Resolve remaining Windows 3.11/3.14 hosted CI, branch-ratchet, semantic goldset/fidelity, SBOM and task-verification boundaries with authentic producers or explicit operator disposition. Do not invoke inference, download models, push solely to manufacture CI, or restore deleted state.
5. Close the existing goal only after every original requirement is proved or explicitly superseded by the operator.

Evidence root: `C:/Users/Adam/.codex/visualizations/2026/10/21/01a15ec3-cf4b-7fc0-b81a-0ae7446ff8ff`.
Chronological observations and exact command identities: [takeover history and execution plan](2026-10-23-main-chat-takeover.md).
Original requirements: [audit plan](2026-10-20-audit-remediation.md), [100-item plan](2026-10-13-100-items-master-orchestration-plan.md).

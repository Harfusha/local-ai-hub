# Local AI Hub: main-chat takeover and complete remaining work

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
- Hub task last verified failed/watchdog: max 100000 tokens / 33000 seconds / 450 external calls; used 0 / 33240.86682920671 / 449. No live increase or resume has yet occurred.

## Evidence index and limits

- `state/validation/budget-access-coverage/coverage.json`: owner-produced composite, fingerprint `268136bae0fae285c03d458d3d622df6ad361b133ab2808553847aa4db0388e2`, 11843 unique cases = 11730 PASS + 113 SKIP, zero effective FAIL/ERROR. Review `adopt_budget_access_coverage.py` before adopting its broad claim. It composes a full baseline, bounded AST delta and authentic affected-case reruns; it is not a fresh uninterrupted full suite or broker receipt.
- Directly adopted native cohorts: `integration-cohort-1c2efaa25533.json` 80 PASS; `248807fb3940` 44 PASS; `947db0a3f1e4` 21 PASS; `81a3ca31c88b` 64 PASS. Each exit 0 and sources_unchanged=true. Preserve red run `7337d5d39978` and timeout `7ca13b68cfac`; neither becomes PASS.
- Browser source epoch `state/validation/browser-failure-coverage/coverage.json`: fingerprint `7f193775f8e429aafcb3beea1a6467703079d002c51c61ab3fd85a9f87f1e557`, composite 11724 PASS/113 SKIP. Main read the 98-line finalizer at SHA256 `09c59f85fbe7e88477104295f35635eaff6a607c325cbb73d60702d57a536c49`. It binds exact substitutions, collection and 125 authentic rerun cases (124 PASS/1 SKIP); it does not prove production acceptance.
- `state/validation/final-release-1e54a5e2/run.json`: handoff reports release_check --allow-installed, compileall and selftest exit 0, unchanged sources. `fresh-package-1e54a5e2/receipt.json` and `native-observation.json`: handoff reports real sdist to wheel to fresh-venv SDK success, production_release_approved=false. Adopt exact manifests/hashes independently before final closure.
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
- [ ] Once readiness permits, invoke the supported authenticated broker task_budget_increase exactly once for the original task, with explicit root and human audit reason, maxima 48000 seconds/750 calls or justified higher increase-only values. Do not mutate task DB directly.
- [ ] Verify accepted maxima, unchanged used counters, owner/status and authentic audit event. Increase while failed must preserve failed state; then task_resume is a separate supported action. Verify its state and checkpoint the transferred owner.
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

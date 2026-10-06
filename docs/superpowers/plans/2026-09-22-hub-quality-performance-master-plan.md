# Local AI Hub quality and performance master plan — recovery reconstruction

**Recovery status:** reconstructed in T20 recovery worktree on 2026-10-04 because this checkout did not contain the source plan. This is a history-derived acceptance matrix, not a byte-for-byte restoration of the original plan. All root receipts below refer to prior recorded checkouts and are not proof of the current root state. Current root status and integrated completion remain **UNKNOWN / BLOCKED** until owners provide fresh, attributable receipts.

**Recovery checkout:** `C:\Users\Adam\.codex\worktrees\t20-plan-recovery\.local-ai-hub`
**Checkout HEAD:** `8c945bdeb5f92270613e53b307b6f646a4f0e21b`
**Preflight:** clean plan status; plan path absent. No source files or tests changed in this recovery.

## Acceptance matrix reconstructed from T20 history

| Task | Status | Owner / files | Recorded evidence and blocker | Dependency / next acceptance gate |
|---|---|---|---|---|
| T01 API surface inventory | BLOCKED | T01; candidate checkout, T27 dispatcher ownership | Candidate had 139 dirty paths. T27 owner/lease unconfirmed; no edits or attributable acceptance receipt. | Confirm candidate ownership and T27 lease; inventory against a pinned root revision. |
| T02 quality baselines | PARTIAL; slot release pending | T02; runner v3 candidate | Candidate suite 10 passed; checkpoint selector 1 passed. CPU smoke: 100 files, 10k chunks, 10 light / 3 paired, concurrency 1/4/16/32; 46.77s, p50 987.085ms, p95 5899.735ms, readiness `per_case`. Full 24-cell matrix and real-input quality remain open. User authorized writing T02 and releasing its test slot; confirmation not yet received. | T02 confirms slot release; finish full 24-cell and real-input quality criteria on owned candidate. |
| T03 contracts, gates, transport | PARTIAL; narrow port authorized | T03; `async_jobs.py` and two T13 tests only | T03 reported root already has `path_hints`; requested narrow port of `async_jobs.py` and two T13 tests despite differing base blobs. User approved this exact port and combined tests. No combined receipt yet. | Preserve T03 changes; port only authorized paths; run combined focused tests once and report hashes. |
| T04 client transport and path hints | REVIEW REQUIRED | T04 candidate `t04-integration`; `client.py`, two T04 tests | Candidate HEAD `3658d5056354849ddf17883ed04f807f16cc44c1`. Two selectors: 3 passed, 1 failed in 9.7s. `test_registered_repo_search_forwards_hints_over_real_root_http` leaked `secret/blocked.py` into paths. Candidate hashes unchanged; slot released. | Fix isolation boundary in T04 candidate; no root acceptance until focused candidate receipt passes. |
| T05 identity and shared memory | NO CURRENT RECEIPT | T05 | No fresh attributable acceptance evidence in recovered history. | T05 supplies owned checkout, scoped criteria, and receipts. |
| T06 safe mutations / daemons | BLOCKED; recovery request sent | T06; `commands.py::run`, command-spawn and journal durability | Assigned `57e3` snapshot missing; `t06-write-set-resume` attach was rejected as another task's worktree. No owned checkout, current preimage, dirty attribution, or characterization-test space. User authorized contacting T06 for a minimal root-current patch and receipt. | T06 confirms owned current checkout/preimage and exact patch; require focused mutation and journal durability receipt. Until then no root patch. |
| T07 retries and idempotence | UNKNOWN | T07; replay tests and mutation paths | Candidate replay command was submitted once; broker returned `success:false` without run state or output. Owner treated slot as consumed and checked stored receipt. A separate prior root replay receipt was 75 passed in 6.01s on HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`, with scoped hashes unchanged; this does not resolve the candidate command's unknown result or establish current integration. | Recover exact candidate artifact receipt or run only after explicit new slot and pinned preimages. |
| T08 Agent OS atomicity / recovery | REVIEW REQUIRED | T08; restart and recovery selectors | v4 root selectors: 11 passed; restart set 7 passed, 1 failed because server-managed `repo_root`. v5 fixture patch integrated to root; exact selector result UNKNOWN/truncated. Do not retry same selector. | Owner provides stored v5 receipt or requests a new bounded slot after pinning current preimage. |
| T09 verification receipts | DEPENDENCY / IN PROGRESS | T09; receipt evaluator | T21 integration depends on `evaluate_completion_receipts`. No fresh evaluator integration receipt recorded here. | T09 publishes evaluator contract and receipt format; T21 verifies against it. |
| T10 repository AST retrieval | BLOCKED | T10 | Assigned artifact missing; replacement create returned “Not a git repository”. | Restore owned Git checkout before source or acceptance work. |
| T11 RAG retrieval and ingestion | NO CURRENT RECEIPT | T11; RAG store, embedding isolation, ingestion | Prior recovery notes describe retrieval and ingestion hardening, but this T20 history contains no current acceptance receipt. | T11 supplies owned revision and focused retrieval / ingestion receipts. |
| T12 model routing | NO CURRENT RECEIPT | T12 | No fresh attributable acceptance evidence in recovered history. | T12 supplies route matrix and focused receipts on owned checkout. |
| T13 operational mode / async jobs | PARTIAL | T13; async jobs and operational mode | T13 reported 53 passing tests. Two tests were authorized for narrow port into T03; combined T03 receipt remains pending. | Preserve T13 baseline; record exact selector list and post-port combined result. |
| T14 context budget / tool policy | REVIEW REQUIRED; root selector failed | T14; `mcp_server.py`, `tests/test_context_pack_budget_e2e.py` | Candidate batch 24 passed in 7.84s. Root test-only change integrated; scoped diff-check passed. Root selector `tests/test_context_pack_budget_e2e.py::test_mcp_adaptive_context_pack_crosses_http_with_bounded_provenance`: 1 failed in 4.22s at line 100; diagnostic detail unavailable. Owner diagnosed async `/api/telemetry/tool-accounting` as a second POST; candidate regression counts only `/api/context/pack`. No root retry. | T14 candidate-only diagnosis, then exact patch/preimage and a new explicit root slot. |
| T15 command broker performance | NO CURRENT RECEIPT | T15; `commands.py` | No current acceptance receipt or integration status in recovered history. | T15 supplies exact command, workload, owner, and receipt. |
| T16 orchestration and handoff | REVIEW REQUIRED | T16; `client.py`, `work_orchestrator.py`, `tests/test_agent_tasks.py` | Root recovery receipt 4 passed, 1 failed; `test_stdio_status_call_cold_starts_isolated_hub_and_cleans_up` reported `payload success=false`, output unavailable. Separate integrated memory-checkpoint selector was requested, not granted in recorded history. | T16 diagnoses failed receipt; any new root selector needs exact preimage and explicit serialized slot. |
| T17 browser and vision | BLOCKED | T17; `services.vision` | Vision ownership conflicts with historical T28 assignment; no edit. Browser, Whisper/WER, and live-vision quality remain unproven. | T17/T28 reconcile ownership and use an owned checkout before changes. |
| T18 status dashboard and telemetry | REVIEW REQUIRED | T18; status/telemetry admin paths | Candidate v3 selector: 8 passed, 1 failed; auth/trace ordering discrepancy. Assigned `1e33` missing; parent candidate ownership unconfirmed. | Restore owned candidate, resolve trace-order discrepancy, and record exact hashes and receipt. |
| T19 install, SDK docs, release rollout | BLOCKED; source frozen | T19; packaging/docs | Candidate-only install/package/rollback tests: 20 passed, 1 skipped (Windows symlink privilege, WinError 1314). Docs parity failed; v2 patch unapplied. Clean-host readiness is not established. Root HEAD had 451 dirty entries; candidate 314. | Require frozen source SHA and sdist SHA, disposable VM/new account, package-index-only ACL, and explicit T20 serialized slot. No GO yet. |
| T20 release acceptance | BLOCKED | T20; this reconstructed plan only | Source plan absent in recovery checkout. Prior root-wide `git diff --check` returned `success:false` with diagnostics truncated at budget 400: **UNKNOWN/TRUNCATED**. Prior scoped checks for T08/T14/T16 and plan passed. | Recover owner receipts, reconcile against a pinned root snapshot, run only approved bounded gates, and close every blocker before release. |
| T21 completion adapter | BLOCKED pending task resume | T21; `verification_rules.py`, T21-owned completion handler, minimal T03 route hook | User approved adapter plus T21-only handler using T09 `evaluate_completion_receipts`, task ID, criteria, persisted receipts, owner, repo revision, mutation generation. User also approved a minimal T03 HTTP route hook. T21 task reported its own goal `blocked`; user said they would send “Pokračuj” in T21. No resumed implementation receipt yet. | T09 evaluator available; T21 resumes; keep T16, T06/T15 and `/api/context/pack` outside scope. |

## Additional audit and follow-up rows

| Row | Status | Owner / files | Recorded evidence and blocker | Acceptance gate |
|---|---|---|---|---|
| T23 compiled-context ETag | INVESTIGATION OPEN | T23; `CompiledContext.etag` callsites | ETag is distinct from the separate `element_id` claim. No proof in recovered history that `json.dumps(el.to_dict())` generates element IDs. | Pin the actual callsite and owner before assigning a change; do not duplicate T31. |
| T26 preprocessing argv and trust | PARTIAL; correction applied to plan | T26; preprocessing and `repo_tools.py` | Existing implementation already uses `shell=False`; accepts validation commands as strings (shlex split) or argv arrays; timeout 15s. Existing-root selector `tests/test_preprocessing_overhaul.py::test_idle_diagnostics_launches_quoted_unicode_command_as_argv`: 1 passed in 0.32s. Windows parsing (`shlex.split(posix=False)` plus manual quote stripping), project-controlled inferred scripts vs “Hub does not execute project code” docs, and diagnostics auto-enable remain open. This is not T26 integration proof. | Cover `.cmd`/`.bat` and quoting; define trust/opt-in; align docs; capture owned integration receipt. |
| T27 `Handler.do_POST` route decomposition | OPEN; preserve existing row | T27; `Handler.do_POST` | Existing T27 row is retained by reference; owner/lease remains unconfirmed. No duplicate task ID created. | Confirm owner/lease and callsite scope; focused route receipt. |
| T28 vision service | OWNERSHIP CONFLICT | T28; `services.vision` | Historical T17 ownership conflicts; no edit or current receipt. | Resolve T17/T28 boundary before implementation. |
| T29 command execution path | OPEN | T29; `commands.run` | No distinct current callsite evidence or owner receipt. T06 owns safe mutation / daemon concerns; avoid overlap. | Confirm disjoint scope with T06 and pin concrete callsite before acceptance work. |
| T30 exception audit | BLOCKED / UNVERIFIED | T30; Python exception handlers | A historical scan reported 361 exact `except Exception: pass` matches across 47 files, 112 Python files, zero parse errors, in a dirty shared root. Current audit was blocked by missing terminal Hub result; do not treat historical scan as current or complete. | One authorized, attributable audit snapshot; classify each finding and record exact files. |
| T31 hash investigation | INVESTIGATION OPEN | T31; hash/identity callsite to be pinned | No verified callsite distinct from T23 ETag or `element_id` claim. Do not invent or duplicate task. | Identify one concrete generator/callsite and prove relationship before assigning implementation. |
| TODO scan | PARTIAL | T20 audit; targeted `deterministic.py` scan | No exact actionable TODO comment found in targeted scan. Scanner pattern `TODO_RE` at line 64 and generated template near line 3867 are code, not TODO findings. Repo-wide absence is not proven. | Bounded repo-wide scan with exact command and retained result; classify actionable comments only. |
| T08 v5 crash/restart | UNKNOWN | T08; current root selector | Broker response was `success:false`, truncated, without exec ID/output/count. Candidate receipt may not substitute for root. Same command must not be retried. | Recover stored artifact or seek a new explicit slot with pinned inputs. |
| T02 slot release | PENDING CONFIRMATION | T02 | User directly authorized T20 to contact T02 and release its slot. Fresh lease query found no T02-owned slot; only lease was T15/T29 in another root. PID 12396 ended naturally; fresh process snapshot reports `ACTIVE_PYTEST_PROCESS_COUNT=0`. Nothing T02-owned required release. No process was terminated; T02 ran no tests or changes. | Record T02 confirmation and any live test process status. |
| T06 current-preimage patch | PENDING OWNER RESPONSE | T06 | User authorized contact for minimal root-current patch and receipt. Request sent; previous assigned checkout was unavailable. | Record exact checkout/preimage, patch, scoped check and focused receipt, or retain BLOCKED. |

## Release gate

Release remains **NO-GO**. History-derived receipts do not establish current root acceptance. Do not merge, publish, install, or claim completion until task owners resolve ownership blockers, unknown results, failed selectors, clean-host requirements, and the root-current acceptance matrix on a pinned source revision.

## Coordination update — 2026-10-04

**Provenance:** history-only receipts from this coordination turn; not root-current verification. The original source plan remains missing from the recovery checkout. Previously reported shared root remains dirty with 379 changed paths. T14 ownership remains with T14. These updates supersede older per-task status where they differ; do not treat old or new candidate receipts as release acceptance.

| Task | Latest coordination receipt | Current acceptance status |
|---|---|---|
| T01, T02, T05, T06, T07, T10, T16, T18, T21 | Replacement `create_worktree` failed with `Not a git repository`. | Blocked; no task-owned acceptance checkout. |
| T03 | Registered `e809` exists; requested `t03-contracts-resume` is absent. No edits; prior packet unverified. | Open; preserve T03 scope. |
| T04 | Registered checkout missing. Prior path-hint tests: 3 passed, 1 failed; `secret/blocked.py` leaked. No root edits. | Open; isolation failure unresolved. |
| T08 | No registered worktree. Crash selector remains UNKNOWN. | Open; no retry evidence. |
| T09 | Candidate regression test: 1 passed; owner/cleanup tests: 8 passed. Broker test blocked because candidate lacks `CommandBroker.run_project_command`; root packet received apply-check only. | Open; candidate and root integration incomplete. |
| T11 | No concrete receipt. | Open. |
| T12 | Candidate: 56 passed, plus prior receipts of 24 and 2 passes. Runtime profiles/VRAM and scheduler acceptance remain open. | Partial; runtime acceptance absent. |
| T13 | Worktree missing. Earlier 56 passes; `/api/mode` route and dashboard badge not implemented. | Open; missing behavior and checkout. |
| T14 | Candidate worktree dirty. Candidate: 95 passed, 3 deselected. Route tests: 7 passed, 1 failed (`Agent2` context-pack failure). | Open; retain T14 ownership and failure. |
| T15 | Owner packet only; no new tests or benchmark. Overlap with T06. | Open; resolve boundary with T06. |
| T17 | No registered artifacts; no new changes. | Open. |
| T19 | No active worktree. Historical suite: 20 passed, 1 skipped; prompt-parity root selector: 1 passed. Neither was freshly verified. | Open; old receipts only. |
| T20 | Reconstructed plan SHA before this addendum: `DE69ED32FCD138995622033D7FE000B33ED7AB45A246E4CD47F5CDA45081A3D4`. | Review / incomplete; plan is not root-current. Prior no-index diff check was not a PASS. |
| T21 | Artifact missing. Prior packet: 14 passed in 3.55s; apply-check only. Root integration blocked. | Open; no root integration receipt. |

**Release:** NO-GO. No current-root validation was performed for this addendum. Do not infer completion from candidate tests or patch apply-checks.
## Release/master acceptance register — 2026-10-04

**Purpose and provenance:** owned T20 handoff addendum; preserves the prior reconstructed history above. This register summarizes only receipts reported in the coordination thread. Receipts are candidate- or history-scoped unless stated; none establishes current-root acceptance. The original source plan is still missing from this recovery checkout. The shared root was reported dirty at 379 paths. No task below is marked done. Release remains **NO-GO**.

| Task | Status / owner | Exact recorded evidence | Blocker / acceptance needed |
|---|---|---|---|
| T01 API inventory | BLOCKED / T01 | Replacement worktree creation failed: `Not a git repository`. Earlier candidate had 139 dirty paths; T27 owner/lease was unconfirmed. | Recover registered owned checkout; attribute dirty paths; pin revision and deliver inventory receipt. |
| T02 quality baselines | PARTIAL / T02 | Candidate runner v3: 10 passed; checkpoint selector: 1 passed. Smoke: 100 files, 10k chunks, 10 light/3 paired, concurrency 1/4/16/32; 46.77s, p50 987.085ms, p95 5899.735ms, readiness `per_case`. Later lease query found no T02 slot; PID 12396 ended naturally; active pytest count 0. No T02 tests or changes in latest coordination. | Full 24-cell matrix and real-input quality open. Candidate/worktree unavailable; old smoke is not release acceptance. |
| T03 contracts, gates, transport | OPEN / T03 | Registered `e809` exists; requested `t03-contracts-resume` absent. No edits; prior packet unverified. Root `path_hints` behavior was previously reported present. | Recover requested owned checkout; verify packet preimage before narrow `async_jobs.py` + two T13 test port; combined receipt missing. Preserve user-approved narrow scope. |
| T04 transport/path hints | OPEN / T04 | Registered checkout missing. Prior candidate selectors: 3 passed, 1 failed; `test_registered_repo_search_forwards_hints_over_real_root_http` exposed `secret/blocked.py`. No root edits. | Fix candidate isolation leak; obtain owned checkout and passing focused receipt. |
| T05 identity/shared memory | BLOCKED / T05 | Replacement worktree creation failed: `Not a git repository`; no concrete current acceptance receipt. | Recover owned checkout and provide scoped receipts. |
| T06 safe mutation/daemons | BLOCKED / T06 | Replacement worktree creation failed: `Not a git repository`. Earlier `57e3` snapshot missing; `t06-write-set-resume` attach rejected. Shared root was reported dirty (379 paths), including `commands.py`; no patch/test. | Recover task-owned checkout and current preimage; then address command-spawn and journal durability with focused receipt. No root patch from shared dirty state. |
| T07 retries/idempotence | BLOCKED / T07 | Replacement worktree creation failed: `Not a git repository`. Candidate replay command had broker `success:false` with no output/run state; result remains UNKNOWN. A separate older root selector was 75 passed in 6.01s on HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`; it does not resolve candidate result or current integration. | Recover registered checkout and unknown artifact; no retry without fresh explicit slot and pinned inputs. |
| T08 atomicity/recovery | BLOCKED / T08 | No registered worktree. Crash/restart selector remains UNKNOWN; older v4 set was 7 passed, 1 failed on server-managed `repo_root`; v5 root result was truncated/unknown. | Recover owner checkout and exact receipt; no repeat of consumed unknown selector. |
| T09 verification receipts | PARTIAL / T09 | Candidate regression test 1 passed; 8 owner/cleanup tests passed. Broker test blocked because candidate lacks `CommandBroker.run_project_command`. Root packet has `git apply --check` only. | Implement/locate missing broker API in owned candidate; root integration and full acceptance receipt remain open. |
| T10 AST retrieval | BLOCKED / T10 | Replacement worktree creation failed: `Not a git repository`; assigned artifact unavailable. | Restore registered Git checkout before changes or acceptance. |
| T11 RAG retrieval/ingestion | OPEN / T11 | No concrete receipt in this coordination turn. | Provide revision-pinned retrieval and ingestion receipts. |
| T12 model routing | PARTIAL / T12 | Candidate 56 passed, plus prior receipts of 24 and 2 passed. | Runtime profiles/VRAM and scheduler acceptance remain open; obtain those receipts in owned checkout. |
| T13 operational mode/async jobs | PARTIAL / T13 | Worktree missing; earlier 56 passes reported. `/api/mode` route and dashboard badge remain unimplemented. | Recover owned checkout; implement missing behavior and obtain focused HTTP/UI receipts. |
| T14 context budget/tool policy | OPEN / T14 | Candidate worktree dirty; 95 passed, 3 deselected. Route tests 7 passed, 1 failed (`Agent2` context-pack failure). Prior root selector had also failed 1/4.22s at line 100. | Keep T14 ownership. Diagnose failure in owned candidate; any root acceptance needs pinned preimage and explicit serialized slot. |
| T15 command broker performance | OPEN / T15 | Owner packet only; no new tests or benchmark. Overlap with T06 noted. | Resolve boundary with T06; establish owned baseline and benchmark receipt. |
| T16 orchestration/handoff | BLOCKED / T16 | Replacement worktree creation failed: `Not a git repository`. Older root recovery receipt: 4 passed, 1 failed; `test_stdio_status_call_cold_starts_isolated_hub_and_cleans_up` reported `payload success=false`, details unavailable. | Recover owned checkout; diagnose old failure. No completion without fresh attributable receipt. |
| T17 browser/vision | BLOCKED / T17 | No registered artifacts; no new changes. Historical ownership conflicts with T28 `services.vision`. | Recover checkout and resolve T17/T28 ownership before edits. Browser, transcription/WER, and live-vision quality remain unproven. |
| T18 status/telemetry | BLOCKED / T18 | Replacement worktree creation failed: `Not a git repository`. Earlier candidate selector: 8 passed, 1 failed on auth/trace order; assigned `1e33` snapshot was missing. | Recover registered checkout; resolve auth/trace ordering and provide exact receipt. |
| T19 install/SDK docs/release | BLOCKED / T19 | No active worktree. Historical candidate package/install/rollback suite: 20 passed, 1 skipped (Windows symlink privilege); old prompt-parity root selector: 1 passed. Neither freshly verified. | Recover owned worktree; freeze source and sdist hashes; clean-host gate remains outstanding. |
| T20 release acceptance | INCOMPLETE / T20 | Source plan absent in recovery checkout; reconstructed plan SHA before this addendum was `0D881DFE52ED230DCC8EBAF146B5B0AAF34F1233850052C64163E6AB565AC4F0`. `git diff --no-index --check -- NUL <plan>` returned 1 because file differs from NUL; no whitespace diagnostics, so not a conventional PASS. | Reconcile every task against pinned root and obtain all required receipts. Current register is a handoff, not release proof. |
| T21 completion adapter | BLOCKED / T21 | Replacement worktree creation failed: `Not a git repository`. Prior packet: 14 passed in 3.55s; `git apply --check` only. Root integration blocked. | Resume task in owned checkout. Preserve approved scope: `verification_rules.py`, T21-only completion handler through T09 `evaluate_completion_receipts`, and minimal T03 HTTP route hook; exclude T16, T06/T15 and `/api/context/pack`. |

## Open architecture and code-smell backlog

| Item | Status / owner | Exact recorded evidence | Blocker / acceptance needed |
|---|---|---|---|
| `Handler.do_POST` decomposition (T27) | OPEN / T27 | Existing T27 route row retained; owner/lease unconfirmed and no current route receipt. | Confirm registered owner and lease; define bounded route seams and focused HTTP acceptance. |
| `services.vision` boundary (T28) | BLOCKED / T28 with T17 conflict | No registered T17 artifacts or new T28 receipt; prior ownership conflict recorded. | Resolve one owner; then verify API/runtime behavior in its owned checkout. |
| `commands.run` decomposition (T29) | OPEN / T29; overlap with T06/T15 | No distinct current callsite receipt. T06 owns safe mutations/daemon durability; T15 has owner packet only. | Pin callsite and non-overlapping responsibilities before change; define focused command/broker acceptance. |
| `agent_context` hash optimization (T31 investigation) | OPEN / T31 | No verified generator/callsite. Historical `CompiledContext.etag` is distinct from `element_id`; `json.dumps(el.to_dict())` was not proven to generate element IDs. | Identify exact `agent_context` hash computation and consumers before optimization. Avoid duplicating T23 ETag work. |
| Broad exception audit (T30) | UNVERIFIED / T30 | Historical dirty-root scan reported 361 exact `except Exception: pass` matches across 47 files, 112 Python files, zero parse errors. Current audit lacks a terminal attributable receipt. | Refresh only from an owned pinned snapshot; classify findings and retain per-file evidence. Historical count is not current acceptance. |
| Preprocess subprocess argv/trust (T26) | PARTIAL / T26 | Existing implementation was previously verified with `shell=False`; selector `tests/test_preprocessing_overhaul.py::test_idle_diagnostics_launches_quoted_unicode_command_as_argv` had 1 pass in 0.32s. | Remaining concern is correct quoting/escaping and argv semantics, including Windows `.cmd`/`.bat`, plus trust/opt-in for repo-derived commands and docs. Do not reopen `shell=True` as an unfixed issue without new evidence. |

**Release gate:** all T01–T21 remain open, blocked, partial, or incomplete. No task is accepted or done by this register. Release stays **NO-GO** until owners close blockers with current, attributable acceptance receipts.
## Release blockers vs post-release refactors — 2026-10-04

This scope clarification supplements the preceding history and does not rewrite receipts. Worktree availability below reflects only reported task artifacts; unknown means unverified. No source integration is authorized by this register.

| Scope item | Quick-release blocker | Post-release refactor / owner | Worktree availability | Acceptance evidence required |
|---|---|---|---|---|
| T14 `/api/context/pack` route fix | Open: candidate receipt and root `apply --check` do not equal root integration. Candidate route-focused batch reported 24 passed. | T14 owns only this current route fix. Wider budget/tool-policy suite and unrelated route extraction stay separate. | T14 candidate `0c2e` exists in prior receipts; latest attempt to attach `t14-context-pack-recovery` was refused as owned by another task. Current availability unverified. | Exact route packet reported as `handoff/T14-root-current-context-budget-fix-20261004.patch`, packet SHA shown in final as abbreviated `7E7FF8E4…D204AEDB`; root preimage `04FF58CA…DE659B0F`, projected postimage `FAC349BB…719CDC63`; root apply-check only. Obtain full hash from owner packet and root-current integration receipt before calling accepted. |
| T27 `Handler.do_POST` router extraction | Not a quick-release gate unless a concrete route defect is tied to release criteria. | Separate future refactor; T27. Must not rewrite or broaden T14 `/api/context/pack` route fix. | T27 owner/lease and worktree unconfirmed. | Independent route contract tests, ownership lease, bounded diff, and receipt after T14 route slice is pinned. |
| T17/T28 `services.vision` | No demonstrated quick-release defect receipt. | Post-release refactor only after T28 confirms ownership; T17 implements only after that confirmation. | T17 has no registered artifacts; T28 ownership/worktree not confirmed. | Written owner boundary first; then owned-checkout API/runtime and vision-quality receipts. |
| T06 `commands.run` / broker safety | Quick-release blocker: command-spawn safety and journal durability remain unverified. | T06 owns refactor and broker safety; coordinate T15 boundary before touching shared command code. | T06 replacement creation failed `Not a git repository`; earlier assigned snapshot missing/foreign attach rejected. | Exact root-current preimage in T06-owned checkout, focused command-spawn and journal-durability tests, postimage and scoped diff receipt. No shared dirty-root patch. |
| T31 `element_id` hash equivalence/performance | Not a release blocker until a concrete correctness or performance regression is proven. | Post-release investigation/test; T31. Keep separate from T23 `CompiledContext.etag`. | T31 worktree availability and actual generator/callsite unconfirmed. | Identify `element_id` generator; prove old/new equivalence with fixtures; benchmark representative inputs and retain measured result. Prior `json.dumps(el.to_dict())` claim remains unproven. |
| T10 broad-exception narrow/log audit | Quick-release blocker only for a confirmed unsafe swallowed exception on a release path. | T10 owns narrow audit and logging follow-up. Historical T30 scan remains a separate, unverified broad count. | T10 replacement creation previously failed `Not a git repository`; no current owned audit checkout. | Pinned-source exact search receipt; classify release-path handlers; add/verify logging only in owned scope. Historical `361` match count is not current evidence. |
| T26 preprocessing argv/subprocess | Quick-release blocker is wrong argument execution, quoting, or trust behavior; `shell=True` is not the current defect claim. | T26 owns argv/escaping and repo-command trust audit. | T26 current registered worktree availability not established by recovered receipts. | Existing source had `shell=False`; historical selector `test_idle_diagnostics_launches_quoted_unicode_command_as_argv`: 1 passed in 0.32s. Still verify escaping/argv fidelity, especially Windows `.cmd`/`.bat`, explicit trust/opt-in and docs. Get a fresh owner receipt before release acceptance. |
| TODO scan | Block only if an actionable release TODO is proven. | T20 bounded inventory; no implementation refactor assigned yet. | T20 recovery document checkout available; original source plan absent. | Historical “no actionable TODOs found” is an unverified claim pending exact search command, revision, and retained output. Do not call repo-wide TODO scan complete. |

T14's test-only packet was also reported as `handoff/T14-root-current-test-only-20261004.patch`, SHA abbreviated `980F077E…D714AF6`; it changes a test and is not the route-source fix. T14 final messages expose abbreviated hashes only. T09 final-message lookup was unavailable on the durable host, so its partial patch packet path/hash cannot be reproduced here; retain its 1-pass and root-apply-check-only status without inventing identifiers.

**Acceptance rule:** current candidate receipts, `apply --check`, historical search counts, and abbreviated packet hashes do not prove root integration. Keep each item open until its owner supplies a pinned, attributable acceptance receipt.
## Latest coordination status — 2026-10-04

Append-only update from the latest owner reports. No thread rereads, source edits, or tests in this step. These states supersede earlier availability notes where they conflict.

| Task | Latest state | Owner / exact blocker | Acceptance |
|---|---|---|---|
| T01, T03, T04, T05, T07, T08, T10, T11, T13, T16, T17, T18, T19, T21 | BLOCKED | Attach denied: `This worktree is owned by another task.` | No task-owned checkout; no acceptance. |
| T02 | BLOCKED / cause unconfirmed | Checkout absent. Historical flake: 2/25 failures, without logs, attempt IDs, or exact revisions; later 25/25 does not prove cause. | Do not call fixed; fresh owned reproduction/evidence required. |
| T06 | BLOCKED | `t06-command-run-fix` attach denied: `This worktree is owned by another task.` No tests run. | No patch or acceptance. |
| T09 | PARTIAL / OPEN | Route packet: 1 passed; root `apply --check` only. Packet path/hash unavailable from accessible final receipt. | Candidate result and apply-check do not prove root integration. Keep open. |
| T12 | PARTIAL / OPEN | No unique selector in latest receipt. | Prior aggregate counts are not unique current acceptance; runtime profiles/VRAM and scheduler still open. |
| T14 | REVIEW / OPEN | Route packet: 24 passed; applied only against candidate index. Root not verified. Packet name previously reported as `handoff/T14-root-current-context-budget-fix-20261004.patch`, SHA abbreviated `7E7FF8E4…D204AEDB`. Wider T14 remains open; retain T14 ownership. | No root acceptance until pinned root preimage and root receipt. |
| T15 | OPEN | No new tests or benchmark. Existing packet `handoff/T15-T29-root-current-packet-2026-10-04.md`, SHA-256 `DEEFE6F07AC31343EF622C33FF4F8855E80F8958F68CA5E6B6E9DE709031E8F0`; `commands.py::run` unchanged; T06 overlap remains. | Packet is a blocker handoff, not benchmark acceptance. |
| T20 | REVIEW / INCOMPLETE | This plan and all addenda are recovery-worktree documents, not root changes. Original source plan remains absent from recovery checkout. | No root acceptance. |

### Code-smell scope reaffirmed

- **T14:** owns only the current `/api/context/pack` route fix. Its route packet is candidate-index-only. Wider tests remain open. `Handler.do_POST` extraction is a separate future refactor and must not replace or broaden this route fix.
- **T27:** owns future `Handler.do_POST` router extraction. Owner/worktree remain unconfirmed. Keep separate from quick-release route defects.
- **T17/T28:** vision refactor waits for explicit T28 ownership confirmation. T17 has no owned worktree; no refactor acceptance.
- **T06/T15:** T06 owns `commands.run` refactor and broker safety; attach is denied and no tests ran. T15 has no new benchmark. Resolve their boundary before shared code changes.
- **T31:** element-ID hash equivalence and performance test remain investigation work. Generator/callsite and worktree are unconfirmed; keep distinct from T23 ETag.
- **T10:** broad-exception narrow/log audit is blocked by foreign worktree ownership. Historical T30 match count is not current evidence. Exact pinned search and per-handler classification required.
- **T26:** audit argv escaping and Windows command behavior. Existing source was previously reported as `shell=False`; treating `shell=True` as the current defect is stale. Verify argument fidelity, `.cmd` behavior, trust/opt-in, and docs in an owned checkout.
- **T20 TODO scan:** “no actionable TODOs found” remains a historical claim awaiting exact search command, revision, and output.

No item is done. **Release NO-GO.**

## 2026-10-05 release triage addendum

This addendum records fresh coordinator evidence. It does not alter the shared root, promote candidate receipts to root acceptance, or close any T01-T21 task.

### Root snapshot reconciliation

- Current root: branch `master`, HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf` (`local_ai_command` request `req_a3eee4c4f17d`).
- Current root repository revision fingerprint: `31057f4435a198c90486cacfca9332b1a9255a219f87209fbe673932e947e4d2`.
- Exact Git porcelain count: 182 tracked + 270 untracked = 452 paths (`req_ea257e00559d`). Original baseline was 182 tracked + 192 untracked; preserve all current paths. The earlier 379 count belongs to an older snapshot/fingerprint, not the current root.
- No root files were edited in this continuation.

### Current adoption evidence

| Task | Current status | Evidence | Decision |
|---|---|---|---|
| T02 | blocked / partial | Root repeat-selector receipt: 3 passed in 0.14 s, but at older fingerprint `82456130…`; assigned `4b5d` checkout is not a Git repo. | Diagnostic only; no rerun or completion. |
| T04 | open / release blocker | Historical path-hint selector 3 passed, 1 failed; `test_registered_repo_search_forwards_hints_over_real_root_http` leaked `secret/blocked.py`. Owned worktree unavailable. | Fix privacy leak and prove focused test before release. |
| T09 | blocked / partial | Candidate persisted-receipt selector 1 passed in 5.30 s. Root lease is UNKNOWN; packet bytes are not available in this task. | Do not integrate yet. |
| T14 | open / candidate only | Its four packet preimage hashes differ from current root. Candidate matrix 24 passed; blocker handoff SHA `6D492EACB768B3625ADDA678E3981DDB6BE3A67FFB3ED1F98BB920610FDC57E3`. | Preserve T14 ownership; no transplant without exact root-current hunk review. |
| T17 | partial / diagnostic | Root phase selector 5 passed in 0.14 s at the prior root fingerprint; no broader acceptance. | Do not treat as release acceptance. |
| T20 | blocked | Assigned worktree missing; recorded `ec50` path is not a Git repo. Plan remains unmodified in T20 task checkout. | This addendum is coordinator-owned recovery documentation only. |
| T21 | blocked / packet inaccessible | Current root HEAD matches pinned base; all five current file SHA-256 values exactly match the historical T21 root preimages. Historical candidate selector 14 passed in 3.55 s and root `git apply --check` passed, but patch SHA `97E325D27FFC32BC5350BAFD6B4602E6F95BF4BA1BB5793DD323AB01CCD25926` is not attached here and patch bytes/lease are unavailable. | No integration. Matching preimages alone do not authorize or reconstruct the patch. |

### Release decision

**NO-GO remains.** Release blockers: T04 search-scope privacy leak; T06 mutation/rollback/crash-recovery receipts; T14 current `/api/context/pack` root verification; T18 current dashboard/API receipts; clean install/start and release checks. Root-wide tests remain paused until each exact owner packet and allowed selector are recorded.

### Post-release work (not release gates unless evidence shows otherwise)

- T27 `Handler.do_POST` router extraction; services vision and commands-run structural refactors.
- `agent_context` element-hash optimization; retain only after equivalence plus repeated performance evidence.
- Broad-exception narrowing/logging and preprocess subprocess argument/Windows behavior audit; existing `shell=False` report makes the old `shell=True` claim stale until reverified.
- TODO scan is not accepted: exact command, revision, and output still missing.

No item is marked done. Candidate plan only; not integrated into root.

## Release gate update — 2026-10-05

This additive checkpoint records the latest T20 owner report. It does not rewrite earlier history, claim root-plan integration, or authorize final release checks.

| Gate | Latest evidence | Owner | Status / release effect |
|---|---|---|---|
| T03 factory/contract test | One factory test passed (`1 passed`); exact command, duration, revision, and receipt ID were not included in the supplied checkpoint. | T03 | PARTIAL. Full acceptance remains **NO-GO**; retain core contract gate until its exact receipt and remaining acceptance are recorded. |
| T09 persisted completion receipt | Root selector fails at `preflight.complete`, test line 112. Exact selector, command, receipt ID, and revision were not included in the supplied checkpoint. | T09 | FAIL / RELEASE BLOCKER. Persisted-receipt completion is not accepted. |
| T08 atomicity/recovery | Owner is active in its correct registered worktree, addressing receipt metadata. No fix or validation result yet. | T08 | IN PROGRESS / RELEASE BLOCKER pending metadata fix and focused receipt. |
| T14 privacy assertion | Assertion remains pending; no result or receipt supplied. | T14 (route owner) | OPEN / RELEASE BLOCKER for privacy-sensitive context delivery. Preserve T14 ownership of `/api/context/pack`. |

No final release checks were run. Release remains **NO-GO** until T09 failure is fixed, T08 metadata work passes its focused gate, T14 privacy assertion passes, and T03 full acceptance is backed by exact attributable receipts. Post-release refactors and benchmarks remain deferred.

## Current orchestrator reconciliation — 2026-10-05

This addendum records the latest available task-owned evidence. It does not modify source or claim integration. Root remains protected: `C:\Users\Adam\.local-ai-hub`, master `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`, 485 dirty paths (187 tracked, 298 untracked) at the bounded status snapshot. The objective's stated preserved baseline is 182 tracked + 192 untracked; current counts differ by +5 tracked/+106 untracked. No cleanup or attribution was attempted; preserve all current root changes. Do not treat dirty-path counts as task completion.

| Task | State | Owner-owned files / current result | Exact validation / blocker |
|---|---|---|---|
| T01 | blocked | No attributable edits. Own archive restore failed: snapshot missing. | No test. Need T01-owned Git checkout; no alternate checkout. |
| T02 | blocked | No attributable edits. Own artifact list empty; `4b5d` is not a Git repository. | No test. Need task-owned checkout. |
| T03 | review | Candidate only: `tests/test_mcp_live_30_client_acceptance.py`, two `handoff/test_t03_*` fixtures. Root SSE source and test already exactly match the T03 packet postimage; T03 made no root edit. | 1-client: `1 passed in 12.37s`; 10-client: `1 passed in 12.48s`; fixture selectors: `1 passed in 2.86s`, `1 passed in 3.82s`. Exact commands and receipt hashes are in `handoff/T03-root-current-small-client-acceptance-20261005.json` (SHA-256 `96282ed3407169f6e2e3f2b81ff841dc0f674c1ea6bbd59614747150080e981a`). Current 30-client result `outcome_unknown`, not rerun. |
| T04 | blocked | No attributable edits; registered checkout missing. | No test. Earlier path-hint test exposed `secret/blocked.py`; privacy fix still required. |
| T05 | blocked | No attributable edits; own artifact list empty. | No test. Need owned checkout and identity/shared-memory receipts. |
| T06 | blocked | No attributable edits; only archived `57e3`, restore failed because snapshot missing. | No test. Mutation/rollback acceptance and producer receipt open. |
| T07 | blocked | No attributable edits; registered worktree `ENOENT`, not archived. | No test. Need exact owned checkout. |
| T08 | review | No source/test edits; 40 inherited tracked edits preserved byte-for-byte; task handoff artifacts only. | `python -B -u run_end_to_end.py` → 110 PASS / 50.67 s. Agent OS completion receipt unavailable under gaming-mode block. |
| T09 | review | Owned delta reported in `http_server.py` plus `tests/test_t09_http_task_completion_persisted_receipts.py`; other dirty paths inherited. | Candidate: 29 passed / 43.23 s (exact command in T09 handoff). Root selector reported 1 passed / 9.19 s, not freshly rerun here. T06 producer receipt absent; lease UNKNOWN; no integration. |
| T10 | blocked | No attributable edits; registered `t10-p2` missing and not archived. | No test. Path-hint isolation and 100k retrieval benchmark remain open. |
| T11 | review | Candidate RAG packet exists; current live CrossEncoder stdout/exit code absent. | Candidate suites: 192 passed, 3 optional skips; embedding smoke 1 passed; MCP selectors 4 passed; retrieval benchmark 1 passed. Root RAG selector: 37 failed, 119 passed, 1 skipped, 2 deselected; do not call accepted. Exact commands/receipts in T11 handoff. |
| T12 | blocked | No source edits; only three handoff documents; remaining source/test dirt inherited or mixed. | No test. Hub returned `operational_mode_blocked` (`terminal=false`, `retryable=true`); own active checkout exists but task rules disallow native fallback. |
| T13 | blocked | No attributable edits; only own registered `t13-lifecycle` artifact, path `ENOENT`, not archived. | No test. Need restore/re-register exact T13 worktree. |
| T14 | blocked | No new edits or tests. Preserve ownership of `/api/context/pack`; owner declined expanded audit from orchestrator message and requires direct user instruction in its task chat. | No new validation. Worktree exists but has 27 tracked and 1,740 untracked paths; attribution unresolved. User audit acceptance remains open. |
| T15 | review | `commands.py` unchanged; its dirty hunk is inherited T06. T15 owner packet only. | Focused selectors: 4 passed, 2 passed, 3 passed / 3 POSIX-only skipped. Benchmark blocked by T06 clean handoff and T20 slot. Exact commands in T15 packet. |
| T16 | blocked | No attributable edits; own artifact list empty; `aad5` missing; candidate belongs to another task. | No test. Need managed ownership transfer or exact task-owned worktree. |
| T17 | blocked | No attributable edits; own artifact list empty; foreign candidate not used. | No test. Need task-owned checkout. |
| T18 | blocked | No attributable edits; registered `1e33` missing, `682c` has no Git metadata. | No test. Dashboard/API release receipts remain absent. |
| T19 | blocked | No attributable edits; own archived `55ed` snapshot missing. | No test. Clean frozen-source install/sdist and prompt parity remain open. |
| T20 | blocked | T20 accepted the added `/api/context/pack` acceptance in its chat, but its `ec50` checkout is unavailable. This recovery document remains coordinator-owned, not a T20 source checkout. | No final release checks. Need recover T20-owned checkout and reconcile every receipt. Release NO-GO. |
| T21 | blocked | No attributable edits; own artifact list empty; `4294` has no Git checkout. | No test. Project/worktree config acceptance remains open. |

### Added `/api/context/pack` acceptance (T14 owns implementation)

- **No full scan for a narrowing hint.** Path/directory hints, excludes, or force-includes first consult the root-scoped index/inventory. A missing/unusable inventory may trigger only a bounded fallback; return its degraded state and exact visited-file count. Hints must reduce work, not initiate `iter_files` across the repository.
- **One trusted request plan.** Build one immutable server-side `ContextPlan` from normalized query, root/workspace, tenant/task identity, focus, changed paths, path hints/filters, server-loaded project-config snapshot/revision, memory revision when applicable, and distinct context/envelope budgets. Pass it through candidate selection, retrieval, and Agent OS context compilation; do not re-read project config/revisions in downstream phases. Client-supplied config or revision is never authoritative.
- **Bounded cascade.** Start with deterministic/indexed sources (including file cards where available); score evidence coverage, then call Serena/RAG only for an explicit measured gap. Apply one end-to-end deadline across retrieval, not additive per-backend waits. Cancellation/future timeouts must not cause unbounded queued work or repeated backend fan-out. On a weak result, report insufficient evidence and the missing source rather than adding arbitrary snippets.
- **Task-aware safe ranking.** `focus`, `changed_paths`, path/directory hints, configured retrieval weights, backend agreement, and query relevance must affect a single candidate/evidence ranking. In review tasks, changed files and relevant tests should be discoverable. Every path is root-contained and rechecked against exclude/force-include policy; tenant, task, and root cache identities remain isolated.
- **One evidence order, one rendering source.** Deduplicate and rank evidence once, then render both model-visible text and metadata/provenance from that exact sequence. IDs, paths, line ranges, revisions/freshness, scores and ordering must agree; stale or cross-root evidence is rejected, not presented as fact.
- **Token-safe snippets and budgets.** Reserve budget first for instructions, provenance and warnings; then add complete snippets/AST blocks using a documented token estimate. If a final snippet must be shortened, stop at a line/AST boundary and ensure attached evidence describes the emitted text. Keep the context-text budget distinct from the complete HTTP/MCP envelope limit, and preserve protected status/error/evidence fields under both.
- **Quality and latency receipts.** Keep contract tests, and add deterministic fixture-repository tasks with expected paths/symbols, precision@k/recall@k, changed-file/test coverage, provenance/freshness and tenant-isolation assertions. Add a live cold/warm benchmark against the implementation (not constant-size/constant-latency fixtures): report exact revision/command/environment, p50/p95, phase timings, visited files, cache hits, response bytes/tokens, plus 1/4/16-client load and slow/unavailable Serena/RAG. Record before/after values; estimates are not measurements.
- **Privacy.** Telemetry may retain bounded phase durations, visited/result counts, cache/backend states, degradation IDs, and token/byte counts only; never prompt, source/snippet text, model output, secrets, or full project paths.

Audit observations in the 2026-10-05 user report are hypotheses until verified against the current owner checkout. T14 owns implementation and acceptance for `/api/context/pack`; other owners must not edit those files. Candidate-only results do not prove root integration or live quality. No fixed-latency fixture or candidate-only receipt proves current-root quality.

No task is marked `done`. Current release remains **NO-GO**; the new context-pack acceptance is not implemented or verified.

## Owner packet refresh — 2026-10-05

| Task | New owner evidence | Integration decision |
|---|---|---|
| T09 | Immutable packet `handoff/t09-owner-packet-task-completion-20261005.md`, SHA-256 `F0AC7801D1533ACDABE4A92558135CE0FFACF5CB50D1B61DD3D4823D48F2027A`; patch SHA-256 `C17D37E1CFCCF6D10C223208D7376826FA1283F862A1ACFAFEA66AFD379C3E57`. Owner identifies only `http_server.py` completion guard and its persisted-receipts test; reports root postimage already integrated, no T03 SSE or T14 context-pack overlap. Candidate focused test `1 passed / 5.65s`; root selector reported `1 passed / 9.19s`; 29-test candidate suite reported passed. | Do not apply patch again. Packet reports integration, but this orchestrator has not independently rehashed its root postimages this turn. T09 remains partial: T06 producer receipt absent, lease UNKNOWN, T05 identity dependency open. |
| T03 | Final small-client packet SHA-256 `96282ed3407169f6e2e3f2b81ff841dc0f674c1ea6bbd59614747150080e981a`; 1/10-client receipts pass, while current 30-client receipt remains `outcome_unknown`. Root already matches SSE postimages. | Review only; no patch to apply. No 30-client or full T03 acceptance claim. |

T11 is preparing a read-only owner packet; its live reranker stays unresolved and root RAG failure remains a release blocker. No new test run or source integration in this refresh.

### T09 root-current hash contradiction

After the T09 packet was received, an exact read-only root hash check found `src/local_ai_hub/http_server.py` at `a8949253e023e42d4db432640caf4fbfa3544e1cf1565dfbe969c401f36125ca`, not the packet's claimed integrated postimage `22F3771584CEFD8C40E7B6E66967C7BC807778B12BA1A338C89B6CD3646478CF`. The root persisted-receipts test file does match the packet postimage `BE8A60161B40802F8C0AFAED439B42CC69C5F63D461BE782ED79563E483C4C8A`. This disproves full-file integration proof; it does not by itself prove whether the T09 guard hunk is absent or merely surrounded by different bytes. Original T09 patch must not be reapplied. T09 owner asked to check/rebase only the guard against the current root while preserving T03 SSE and T14 context-pack ownership. **T09 integration remains unverified; release NO-GO.**

**Owner follow-up:** T09 reports the exact actor-vs-task-owner guard is present in current root `Handler.do_POST` lines 3688–3701, before project completion. Owner did not recompute the full-file hash, create a new hunk receipt, or rerun tests. Therefore no source patch is needed based on current evidence, but exact root-current hunk provenance and a fresh focused root receipt remain unverified. Keep T09 `review/partial`, not `done`; do not apply the historical patch.

### T11 root-reconciliation packet

Manifest: `C:\Users\Adam\.codex\worktrees\f678\.local-ai-hub\handoff\t11-owner-packet-20261005\manifest.json`, SHA-256 `83234A2CA308A29ECCE78C03B2BE350A67304377F539B4A10EDB355812364238`. T11 says its candidate changes were already inherited at task start; no root edit, no patch, no test/live-model rerun. Candidate/root SHA results:

| Path | Candidate SHA-256 | Root SHA-256 | Result |
|---|---|---|---|
| `src/local_ai_hub/rag.py` | `BDC94FFE14252A7CB18460E1E1B5C513134F66C451FA1CD3DF90B21FCCB09EE7` | `E1F67AA741945BFF05704BBDA385D9DCF90F42C1CA2880A1FE3C9F2B1BB59CA1` | mismatch |
| `src/local_ai_hub/embeddings.py` | `2360FB9E4E9DDA72DC633A5E4F33ECBAB2EC3E8A26DC728F61114ACC2496D170` | `B80C15DEBB62724BB20113E86324B8268C685A1076D5508A22BBF4246FEA07E0` | mismatch |
| `src/local_ai_hub/reranker.py` | `EE8B660C9FA261EA34FB63587F8EAAF6119B83B544A4053D22669EF8D9C5C562` | same | match |
| `tests/test_rag_fragment_cache.py` | `A7BD3335691AA7C291D4F42A600A2C7D790475F5770D534D9033FF6620A22002` | `71706EABACABD2AA9B8FE20DAA173069E63837E942DFFC6B055F0C85254B2590` | mismatch |
| `tests/test_rag_hybrid.py` | `CA14B2DF15B2E7DB1C7268B9CD5A4C1C57C2E9074BCEDDDEC15F6D26E729AAA8` | `833B366DE3C1141B69C946D365933CB86BCAC9A05D83C9F4FCEFD621460E7CA8` | mismatch |
| `tests/test_rag_quality_contract.py` | `EF90FC86269D89FFDB6E5CC508BF54917D4A6ED2243447E85DE372B94D5CF3E9` | `CCDC179B6AC957566668AC6694063DB2A1C5945099168C364888AD781CF9CC7B` | mismatch |
| `tests/test_t11_rag_ingestion_contract.py` | `A5C2C6B7BD5C6E1C7383DEAFDB6070FCC212DF335DEFDA9C21ED3B9398CAC7B8` | `05F7F27BABC8A6714E661B6B35B3E2E0D97C52A97854D62F79315B5673BB88ED` | mismatch |
| `tests/test_t11_rag_seed_integrity.py` | `943AED3FC4CC11FCEC48A99500D1967E869B0276F6AF600736254CA375AB0E02` | same | match |
| `tests/test_t11_project_policy_consumers.py` | `98FB176272F7C8F2C41CEF885B5CDA0E6A41E32DCB0D511BA12F16311FE4AEC6` | `D79C4748E277B5EAE20BE56921765709A7180EB54CD7874041A483B16D3FF6A4` | mismatch |
| `tests/test_rag_read_bounds.py` | `AE19C08BC2AA9CA45D0B7F26DCFF23DD8ABDB3A1D843F54A7830045A8A568AA2` | `9D9F3EE9DAAD5306570D9A7C2674DA1A4CF3342541A1A2B43ABB1F798EC0D002` | mismatch; candidate file was untracked |

Integration remains **NO**: eight of ten file hashes differ, no hunk-level ownership clearance exists for those deltas, and the historical whole patch is explicitly unusable. `reranker.py` and `test_t11_rag_seed_integrity.py` match but are not independently integrable as a partial change. Candidate receipts do not override the recorded root RAG result `37 failed, 119 passed, 1 skipped, 2 deselected`; live CrossEncoder remains `UNRESOLVED`.

**T11 owner clarification:** manifest contains root SHA for all ten paths. Additional collision: candidate ingestion test may overwrite root gaming-mode isolation. Thus no candidate hunk is cleared for transplant; no source or test integration authorized by this packet.

### Coordinator restart checkpoint — 2026-10-05

Existing T01–T21 chats were rechecked; no duplicate chats/tasks were created. Nineteen non-T14 owners received a scoped resume request in their existing chat. `list_threads` then showed T02, T03, T04, T08, T09, T11, T12, T15, T16, and T18 active. This is a point-in-time scheduler state, not completion evidence. T14 remains its `/api/context/pack` owner and declined acceptance expansion from an orchestrator-originated message; no T14 code or files were touched.

Fresh owner responses identify checkout blockers:

| Task | Current blocker from owner response | Safe next step |
|---|---|---|
| T01 | Exact `1938` checkout and archived snapshot unavailable; no attributable changes or fresh tests. | Restore/register exact T01 checkout, then resume owned inventory tests. |
| T05 | No T05-attached worktree; candidate checkout belongs elsewhere. | Restore/attach exact T05 worktree only. |
| T06 | `57e3` snapshot missing; `t06-write-set-resume` belongs to another task. T15 was notified before any `commands.py` overlap. | Managed recovery/transfer of T06-owned checkout, then coordinate exact hunks with T15. |
| T07 | Exact `t07-idempotence` attach returns `ENOENT`; historical replay result remains UNKNOWN. | Restore exact T07 checkout; no candidate substitution. |
| T10 | Owner reports registered `t10-p2` only and prior target path `ENOENT`; no new changes/tests. | Recover exact T10-owned Git checkout. |
| T13 | Registered `t13-lifecycle` path returns `ENOENT`; no current test receipt. | Restore/re-register exact T13 checkout. |
| T17 | No T17-attached worktree; prior contract receipts are historical; live browser/vision/audio quality unproven. | Attach exact T17 worktree before further checks. |
| T19 | Archived `55ed` snapshot missing; install/update prompt parity not verified. | Restore exact T19 snapshot. |
| T20 | `ec50` is not a Git checkout; archived snapshot missing. | Restore exact T20 owner worktree; this recovery plan remains coordinator-owned. |
| T21 | `4294` directory is empty; no Git checkout or tests. | Restore/attach exact T21 worktree; do not substitute another path. |

T03/T08/T09/T11/T12/T15/T16/T18 resume requests were accepted or are currently active; await one bounded result per active group. Any returned historical receipts remain historical until tied to exact revision and ownership. Root remains untouched in this checkpoint. The new adaptive `/api/context/pack` design remains unimplemented/unverified; release remains **NO-GO**.

The focused adaptive-context Hub request returned `operational_mode_blocked`, `mode=gaming`, `terminal=false`, `retryable=true`. No test or source fallback was run from that response. Do not retry identical Hub operation or mark acceptance based on this checkpoint.

### Fresh owner receipts — restart batch

- **T03 moved to review.** Owner handoff SHA-256 `d0f33dbd2813cc58f6b3404f8892d28885d21c43b69385c14c83863430507987`, candidate HEAD prefix `d68ee694`. Candidate selectors passed: `test_mcp_client_factory_forwards_tenant_and_config` (1 passed, 1.64s) and `test_concurrent_process_clients_have_one_supervisor_spawn_authority` (1 passed, 3.82s). Owner also reports isolated 1- and 10-client runs passed with one daemon and verified cleanup. Root SSE source/test already match expected postimages; no patch applied. Release remains NO-GO: 30-client receipt is `outcome_unknown`, prior 30-client result lacks root revision identity, full root/T13 heavy operational-mode acceptance is absent.
- **T02 remains blocked/inconclusive.** Owner found conflicting historical counts (2/25 vs 1/25), missing failing node/log/order/process cleanup evidence, later 25/25 pass, and no proven cause. Queue/cancel race is separate known defect, relation unproven. No source edit/test this continuation; exact owned worktree missing. Do not weaken assertions or claim flake root cause.
- **T16 remains blocked.** Exact `aad5` worktree absent and artifact list empty; prior candidate path belongs elsewhere. No edits/tests. Recovery requires managed restoration/transfer of the T16-owned checkout.

These are owner-reported candidate results, not root integration evidence. All three remain short of `done`; preserve release NO-GO.

### Additional owner responses — restart batch

- **T04 scope mismatch.** Latest reply analyzed T02's historical flake, not T04 client/transport acceptance. It is not counted as T04 evidence. Owner was asked to resume original T04 scope or report its exact checkout blocker; no T04 completion claim.
- **T04 checkout confirmed missing.** Correct owner reports registered `t04-d410-integration-candidate` path absent; `393c` is not a Git repo. Current replay/request-ID delta and tests cannot be verified. Historical user-provided root receipt has two owner-ID GET selectors passing, but it is not current T04-worktree evidence. Root and T14 remain untouched.
- **T02 checkout confirmed missing.** Correct owner reports `4b5d` is not a Git repo and T02 artifact list is empty. No combined test rerun. Historical `2/25` versus current prompt `1/25` mismatch, missing failing logs/node/order/process data, and independent queue/cancel race leave original flake cause unconfirmed.
- **T12 partial candidate receipts.** Owner reports 24 policy-parity tests and 32 routing/config/benchmark tests passed in candidate `4816`; packet `T12-generated-policy-sync-20261004.patch` SHA-256 `5F2E0207E8332F1C2976E7872E1FBDB53A6F52AA1F5A244474998B14B8CC5BBF`. Current postimage hashes were not reverified; no new tests/files this continuation. Do not integrate from the packet alone.
- **T15 blocked.** No `commands.py` lease, performance measurement, or before/after receipt. T06 owns overlapping run/spawn/rollback/lifecycle code, while its checkout is missing. Do not edit shared commands paths until T06 checkout and scoped lease are available.
- **T18 partial owner report, not current proof.** Owner reports telemetry privacy patch source hash `D6EDCE0B…1249E6B9` to `05802B70…D6AD762B` and one historical selector pass, but local handoff is older and marks patch unused/untested. No owned Git checkout or fresh dashboard/status acceptance. Keep T18 blocked/review; do not port from abbreviated hashes.

No packets integrated by these reports. Release remains **NO-GO** pending exact checkout ownership, current hashes and required fresh receipts.

### T11 final candidate addendum — 2026-10-05

T11 produced one concrete candidate test fix: four CRLF-sensitive assertions in `tests/test_rag_read_bounds.py` now normalize line endings. Owner reports targeted test result **9 passed in 3.36s**. Addendum SHA-256 `84F08484FA1F7982986ECBCF310B2DC561E9869C858D851744C8732254E7EE70`; test preimage SHA `AE19C08B…568AA2`, candidate postimage `699D0D3B…70BE3A`. This candidate file was untracked and must not overwrite root gaming-mode fixture. Source owner deltas in `rag.py`/`embeddings.py` still conflict with root and have no hunk clearance; `reranker.py` is already identical. Root's recorded RAG failure remains separate; live reranker unresolved. No integration authorized, root and `/api/context/pack` unchanged. T11 is not done.

### Managed worktree ownership reconciliation — 2026-10-05

Parent artifact registry lists task-named worktree paths, but task owners cannot assume ownership from a matching directory name. A one-time managed attach attempt was denied with `This worktree is owned by another task.` for T01 (`t01-coverage-main-verify`), T02 (`t02-quality-baseline-resume`), T04 (`t04-integration`), T05 (`t05-identity-recovery`), T06 (`t06-safe-commands`), T08 (`t08-agent-os`), T17 (`t17-multimodal-resume`), T18 (`t18-status-dashboard`), and T21 (`t21-project-config`). These owners stopped before reading HEAD, dirty state, or files; no edits/tests occurred. T16's prior attach to `t16-orchestration-resume` was also rejected as foreign. T13's task artifact list does not contain either parent-listed `t13-*` worktree, so it correctly declined attachment. No retry or forced transfer performed.

This confirms a managed-ownership/attachment blocker, not merely missing directory names. Safe unblock requires the actual worktree owner to transfer/register the exact checkout to its task, followed by owner verification of HEAD and inherited dirt. Do not use parent-visible paths as source authority. Root remains untouched; release remains **NO-GO**. T11 is still checking its own artifact/handoff relationship; no attachment or source transfer is yet confirmed.

### T11 scope correction — 2026-10-05

T11 confirmed its assigned `f678` checkout is its own. It briefly tested two T21 `project_config.py` hunks (75 tests passed on that temporary state), then reverted both to pre-hash `FFD425B1…1419B0B`; those results do not validate final T11 source and no T21 change is transferred. Final T11-owned delta remains only CRLF normalization in `tests/test_rag_read_bounds.py`, hash `699D0D3B…AA70BE3A`, with targeted receipt **9 passed**. Live reranker still has no final output/exit code; parent-reported root RAG `37 failed` is historical, not freshly checked. T11 remains incomplete; no integration authorized.

**T11 immutable closeout:** Manifest `handoff/manifest.json` SHA-256 `83234A2CA308A29ECCE78C03B2BE350A67304377F539B4A10EDB355812364238`. Receipt `read-bounds-followup.json` SHA-256 `84F08484FA1F7982986ECBCF310B2DC561E9869C858D851744C8732254E7EE70`. Exact candidate command `python -m pytest -q --tb=short tests/test_rag_read_bounds.py` reported **9 passed, 3.36s**. Final `tests/test_rag_read_bounds.py` SHA-256 `699D0D3B7C19C5176A70126E75F3E897C238CDBE2894B3D906E7432254E7EE70`. Candidate source hashes: `rag.py` `BDC94FFE14252A7CB18460E1E1B5C513134F66C451FA1CD3DF90B21FCCB09EE7`; `embeddings.py` `2360FB9E4E9DDA72DC633A5E4F33ECBAB2EC3E8A26DC728F61114ACC2496D170`; `reranker.py` `EE8B660C9FA261EA34FB63587F8EAAF6119B83B544A4053D22669EF8D9C5C562`. Remaining candidate test hashes and root/candidate comparisons reside in that immutable manifest. CrossEncoder PID `17692` is no longer running; only partial `[100%]` output exists, no final summary/exit code. Root `37 failed` report has no stored command or receipt. Therefore live RAG acceptance remains UNKNOWN, source hunks remain non-integrable, and T11 is **PARTIAL**, not done.

# Worktree reconciliation and remaining work

Current phase: merge existing changes before further product development.

User decision (2026-10-06): manually merge master into existing worktrees,
preserve dirty changes, commit reconciled code/tests/docs even if unfinished,
then integrate each result into master sequentially. A commit is preservation
and integration evidence, not proof that the task acceptance criteria pass.
Runtime state and caches remain outside version control.

## Integration log

| Scope | State | Owner / checkout | Evidence / remaining work |
| --- | --- | --- | --- |
| Root T03 path-hint regression | integrated, acceptance partial | orchestrator; master | `fbc965f5`; `python -m pytest -q tests/test_mcp_contract_dispatch.py -k test_mcp_repo_search_passes_path_hints_to_client_keyword --tb=short`: 1 passed, 17 deselected. Broader T03 changes still require reconciliation. |
| T01 inventory | integrated; unfinished | Popper the 2nd; t01-coverage-main-verify | `b9466d30` merged into master. Worker reported 821 passed, 11 failed; two context follow-up tests passed, nine failures remain. Final inventory regeneration and release acceptance follow source consolidation. |
| T02 quality baseline | integrated; unfinished | Gibbs the 2nd; t02-quality-baseline-resume | Branch `codex/sync-t02-master-20261006`, head `673d1a0b`, merged into master. Checkpoint `codex/sync-t02-checkpoint-20261006` retains original dirty content. Targeted command in `handoff/T02-sync-integration-20261006.md`: 18 passed, 78 deselected. Runner still uses removed checkpoint/resume CLI flags; real-input baseline and historical intermittent test failure remain unresolved. Nine original untracked artifacts retained unchanged. |
| T06 safe-command checkout | integrated; unfinished | Wegener the 2nd; t06-safe-commands | `dac22b98` merged into master; 166 changed paths against worker's pinned master. Final targeted checks: 48 passed, 5 failed; 27 Python files compiled in memory. Remaining POSIX rollback ctime issue, transaction/attempt fixtures, patch/import acceptance and generic provenance are in `handoff/T06-sync-master-integration-20261006.md`. Original tracked newline bytes are unverified; LF/CRLF variants and exact handoff bytes preserved. |
| T05 identity / memory | integrated; unfinished | Maxwell the 2nd; t05-identity-recovery | Final worker `b47246f7`, merged at `fc950005`. All ordinary dirty/untracked material committed; runtime exclusions enumerated in `artifacts/sync-t05-20261006/ordinary-preservation-manifest.json`. Worker reported 122 passed, 14 failed, 1 skipped. Root fresh two-test transport check: 1 passed, 1 failed, 15 deselected; worktree-scoped delete did not raise expected HTTP 403. Preserve assertion and repair isolation after consolidation. |
| T03 contracts | integrated; unfinished | Einstein the 2nd; t03-contracts-resume | `32c5079b` merged into master. Original/dirty refs `codex/checkpoint-t03-original-20261006` and `codex/checkpoint-t03-dirty-20261006` preserve the old state. Focused follow-up: 169 passed, 3 failed. Schema parity, gaming/maintenance dispatch and earlier memory-scope HTTP 404 remain unresolved. Additional original untracked handoffs are being committed separately. |
| T04 transport / startup | integrated; unfinished | Raman the 2nd; t04-integration and t04-lock-recovery | Both `8634b913` and `31de8a7a` merged; final merge `5e8424c4` retains both colliding integration documents. Worker checks: 113 passed, 5 failed, 1 skipped; follow-up 98 passed, 6 failed. Schema/fixture and removed-sidecar acceptance remain unresolved. |
| T26 preprocessing argv | synchronized and integrated; acceptance partial | orchestrator; t26-preprocess-argv-5361 | Original dirty content committed at `e2f7e296`, retained by `codex/checkpoint-t26-dirty-20261006`. The dirty addition was an exact duplicate of the existing test; deduplicated at `9e7df358`. Merge into master has identical final tree and preserves both commits. No new T26 test run in this phase. |
| T10 exceptions/search checkout | synchronized and integrated; acceptance partial | orchestrator; t10-exceptions-search | Dirty ignore-directory change preserved in `6224ec20` and `codex/checkpoint-t10-exceptions-20261006`. Seven conflict hunks manually resolved: retain `.codegraphcontext`, project policy-aware scanning, scoped accelerator candidates, bounded Python fallback, and counters from current master. Final staged tree exactly matched master; historical T10 changes are preserved in merged ancestry. `git diff --check` passed; no new functional test run. Other T10 worktrees still pending. |
| T11 recovery-v2 checkout | synchronized and integrated; unfinished | orchestrator; t11-rag-recovery-v2 | `a1169d6c`: all ten original untracked handoff/test files committed after master merge. Archived patches and project-config source copy retained as handoff evidence, not applied to runtime source. Overlay tests and original PARTIAL acceptance remain to verify after consolidated integration. Other T11 dirty worktrees still pending. |
| Clean checkouts / inactive branch refs | synchronized to intermediate master | orchestrator | 17 clean checkouts fast-forwarded to `9b794d7f`; original history remains in master ancestry. Inactive task refs fast-forwarded with ancestry check and compare-and-swap. Checkpoint refs remain pinned; a brief accidental advancement of two T04 original checkpoint refs was immediately restored to `3658d505` before continuing. Final synchronization will repeat after all merges. |
| T15 recovery location | missing checkout; investigate | orchestrator | `C:/Users/Adam/.codex/worktrees/t15-recovery` parent still exists, but `.local-ai-hub` is missing and the checkout is no longer registered. This run issued no removal/archive command for it. Recover original handoff content from available archive/refs before closing this item. |
| Remaining worktrees | pending reconciliation | orchestrator assigns one checkout per worker | Inventory identified 66 registered checkouts. Original tracked/untracked changes and stashes remain preserved; completion requires per-checkout merge and final ancestry/status checks. |

Additional integration on 2026-10-06:

- T02: `d2427a73` commits all nine previously retained ordinary untracked
  artifacts after master synchronization; integrated. No new test run.
- T07: `f6f90b34` commits original patch/receipt plus integration note;
  integrated source is identical to master. Worker checks: 98 passed, 1 failed
  (strict CodeGraph absence fixture rejects permanent `.codegraphcontext`
  ignore). Pytest temporary-directory scope deviation recorded in handoff.
- T09 (`t09-root-current`) and T12 (`4816`) are assigned parallel manual
  merges of their prepared checkpoints. T03/T05 are committing remaining
  ordinary untracked material; T08 is reconciling its dirty Agent OS state.
- Commits preserve unfinished work, not acceptance. Do not tag a release
  until consolidated tests and outstanding safety findings are resolved.

Further preservation:

- T03 `3fb39f83` integrated: all original ordinary untracked handoffs committed.
  Manifest preserves 885 runtime-excluded files in the original checkout.
- T20 plan checkpoint `67fe2dd7`, merge `7e6f2715`, integrated. Original
  unfinished 347-line plan is explicitly historical; the consolidated master
  plan remains under the authoritative section. Later plan deduplication
  must preserve all still-open acceptance items.
- Root T05 test command: `python -B -m pytest -q -p no:cacheprovider
  tests/test_agent_state_transport.py -k
  'test_http_verification_route_rejects_passed_receipt_without_evidence or
  test_http_memory_delete_requires_verified_worktree_scope' --tb=short`.
  Result: **1 passed, 1 failed, 15 deselected in 9.10s**.
- `fefe`: all seven original ordinary handoffs committed at `ddd3594d`.
  Master merge is currently being resolved; code-index/deterministic hunks
  preserve conservative graph completeness and master lazy indexing.
  Broker/process-control/test conflicts remain; not integrated or accepted.

- T09 `31c6214d` integrated: production source identical to consolidated
  master; original receipt test and 24 handoff files preserved. Worker reports
  final 98 passed, broader 121 passed / 4 failed. Runtime manifest records
  781 excluded files. Cleanup tests created fixture worktrees; scope deviation
  explicitly recorded in `handoff/t09-sync-integration-20261006.md`.
- Live context benchmark: original two untracked files checkpoint-committed
  at `deaa4005` on `codex/sync-live-context-benchmark-20261006`, pinned by
  `codex/checkpoint-live-context-benchmark-dirty-20261006`. Source reconciliation
  against the newer master benchmark is still pending; not integrated.
- Active independent merge owners: T08 Socrates; T12 Kant (`4816`);
  T13 Nietzsche (`t13-operational-mode`); T14 Schrodinger
  (`t14-context-budget-recovery`); historical `fefe` Ohm. The orchestrator
  handed the partially resolved `fefe` merge to Ohm and no longer edits it.
- All 45 historical stash snapshots remain untouched. Inspection confirms
  missing T11 handoff files remain recoverable in stash `4b54e7af`'s third
  parent. Their restoration/integration and missing-checkout inventory remain
  pending; do not drop any stash until content coverage is verified.

T11 missing-checkout recovery: all eleven ordinary handoff files from the
third parent of stash `4b54e7af` restored into master after checking none of
their paths existed. This stash contains no tracked source delta versus its
first parent. The 179023-byte owner patch is preserved as historical evidence,
not applied blindly. Historical receipts do not prove fresh acceptance.
The stash remains intact. Missing checkout registration/provenance still
requires reconciliation; source integration coverage of the archived patch
must be checked before cleanup.

Recovered T11 patch coverage check: `git apply --reverse --check
--whitespace=nowarn handoff/t11-master-b947d76f-owned.patch` returned exit 1
with mismatches in all eight owned paths. This is not proof that changes are
missing: current master can contain newer overlapping changes. A hunk-level
comparison remains required; no archived source was blindly applied.

Additional original untracked content checkpointed, not yet integrated:

| Checkout | Preservation commit | Content |
| --- | --- | --- |
| t16-orchestration-resume | `22f116cd` | Two original patches, work_fencing source, junction recovery test |
| t14-render-order | `ed6b2dbe` | Original render-order regression test |
| t14-snippet-isolated | `ee8ba503` | Original isolated snippet-budget test |
| t13-operational-mode-resume-20261004 | `b0ade36a` | Original operational_mode source and test |
| t17-vision-refactor | `fad072f3` | Original vision decomposition preimage map |
| t06-write-set-resume | `1145d19d` | Original durability regression note and patch |

These commits preserve unfinished work without product edits. Each still
needs its manually reconciled master merge and later acceptance; no claim of
functional completion follows from preservation.

T14 context-budget reconciliation: `fcdc58a7` integrated. Complete original
checkpoint `dd07cfe0` retains source/tests/handoffs before merge. Incremental
production changes are limited to MCP context projection and response-budget
citation retention. Worker: 98 passed / 7 failed; final affected rerun
26 passed / 2 failed. In-memory AST and scoped whitespace passed. Outstanding
128-token error truncation, rollback status fields, older scope/path fixtures
and strict CodeGraph substring assertion remain in
`handoff/T14-SYNC-INTEGRATION-20261006.md`. Long citation/identity truncation
also needs acceptance review before release; no broad completion claim.
T14 render-order checkout now assigned to Anscombe independently.

Fresh integrated-root budget regression:
`python -B -m pytest -q -p no:cacheprovider tests/test_mcp_response_budget.py
tests/test_response_budget.py --tb=short`: **23 passed, 3 failed in 2.77s**.
Two command rollback tests received `operational_mode_blocked` with gaming
mode instead of reaching their fake transport; investigate test/runtime
state isolation without changing the user's live mode. The third test
confirms a protected error string is truncated at the 128-token budget.
No test expectation weakened and no repeat of this command was launched.

## Further reconciliations

- T13 `b30a6dde` integrated: older source/tests/handoffs committed, newer
  master operational admission and safety retained. Three async safety hunks
  and a fail-closed auto-repair guard retained. Worker checks: 104 passed /
  37 failed; syntax passed for 118 files. Live mode unchanged.
- T12 `8ab07a6c` integrated: runtime routing, bounded inventory/unload,
  scheduler cancellation and benchmark changes reconciled. Worker checks:
  138 passed / 2 failed, 45 passed / 1 failed, benchmark 10 passed with six
  executions blocked by the external-state guard. Runtime acceptance,
  deadline and identity fixture gaps remain in the owner integration note.
- T14 render-order `53198c04` integrated. Production source matches pinned
  master; original test/history preserved. Eight focused tests and scoped
  whitespace passed. Inherited context-budget acceptance remains open.
- T06 write-set `1c311c65` integrated. Older helper/protocol hunks are
  superseded by current master scoped cache invalidation, incident capture,
  provenance and uncertainty guards; original source checkpoint remains.
  Original rollback regression retained, not weakened. Targeted execution:
  two failures / 77 deselected (missing `failure_kind`); later cache assertions
  not reached. Exact command in its handoff note.
- T08 `3bbc4f1c` integrated at `2ee2a0a0`. Four source/test overlaps resolved
  manually: keep T05 durable promotion publication and sanitization, T08
  auto-link/other atomic mutations, explicit caller-ID replay lookup, and
  T05 trusted HTTP mutation identity. Both conflicting global-memory tests
  retained separately; older cross-tenant expectations need review, not a
  weaker runtime policy. Source checkpoints retain all original protocols.
  Worker syntax: 43 files passed. Worker targeted batch 18 passed / 7 failed;
  two fixture follow-ups passed. Fresh root integration check is pending.
- Active owners now: T10 path hints Lorentz; T21 config Chandrasekhar;
  T19 docs Ptolemy; T14 isolated snippet Peirce; historical fefe Ohm.

Fresh root T08 check:
`python -B -m pytest -q -p no:cacheprovider
tests/test_agent_task_memory_adoption.py tests/test_agent_t08_live_order.py
tests/test_t08_sync_transport_remaining.py --tb=short --maxfail=6`:
**28 passed, 1 failed in 20.68s**. The remaining verified-worktree delete
regression did not raise the expected HTTP 403. Keep the denial expectation;
repair authorization after historical consolidation. Passing memory-adoption
and ordering tests are targeted integration evidence, not full release proof.

Additional integrations:

- T10 path hints `69c11dae` integrated: constructor call ownership, parser
  initialization locking, Java/C++ extractors and literal wildcard escaping
  retained with master path/config/security constraints. Worker 225 passed /
  6 failed / 10 skipped, then corrected merge-scope selector 5 passed. Aggregate
  was not rerun; native parser and inherited T14/verification gaps remain.
- Historical fefe `7f8f4105` integrated at `896fbedb`. Two broker guard
  overlaps combined conservatively: uncertainty/cancellation, unsafe command
  class, and explicit replay safety all restrict repair. Worker broad checks
  151 passed / 46 failed / 10 skipped, final safety 8 passed / 1 failed.
  Cleanup/drain/callback/daemon/rollback acceptance remains unfinished.
- Post-fefe root repair check: `python -B -m pytest -q -p no:cacheprovider
  tests/test_auto_fix_repair_loop.py --tb=short --maxfail=3`: 4 passed / 3 failed,
  stopped at three failures in 8.76s. It exposed actual merged call-site bugs:
  `_attempt_key` now requires tenant and timeout, but private transaction and
  patch rollback paths omitted them; `_key` silently used default scope.
- Root integration correction retains tenant/timeout at all four stale
  identity calls. New signature regression was run RED: 2 failed in 0.42s.
  Then `python -B -m pytest -q -p no:cacheprovider
  tests/test_sync_command_identity_calls.py tests/test_auto_fix_repair_loop.py
  -k 'transaction_identity_calls_bind_current_required_scope or
  test_command_run_auto_fix_flag or
  test_repair_loop_rejects_patch_outside_write_set_before_writing'
  --tb=short --maxfail=3`: **3 passed, 1 failed, 19 deselected in 14.46s**.
  Both identity signature regressions and write-set rejection passed; auto-fix
  still returns unsuccessful. Do not describe all transaction behavior as fixed.
- T14 snippet `46087216` integrated: original isolated regression retained;
  production source matches worker pin. Worker 15 tests passed; inherited
  identity/budget and full release acceptance remain open.
- T18 candidate original eight ordinary untracked tests/patches/handoffs
  checkpoint-committed at `357099ba`; source reconciliation remains pending.

Current parallel owners: T21 project config; T19 docs rollout; historical
55ed docs/SDK contracts; T16 orchestration resume; T14 path-scan checkout.

T21 `4714124b` integrated at `182e1c46`. Original project config/preprocessing
policy hooks, generation-aware RAG invalidation and hint normalization retained
with master inheritance and verification safety. Worker: 143 passed / 25 failed;
old search/metrics/verification/RAG contracts remain unfinished.

Integration invariant correction: T21 removed `.codegraphcontext` from scan
defaults. This contradicts the permanent external-data exclusion and could
reintroduce expensive scans, even though CodeGraph runtime remains removed.
New regression ran RED (one failure); the narrow ignore restoration ran GREEN
with identity regressions: `python -B -m pytest -q -p no:cacheprovider
tests/test_sync_codegraph_scan_ignore.py tests/test_sync_command_identity_calls.py
--tb=short`: **3 passed in 0.60s**. Commit `6d32a3c5`. No backend restored.
Do not satisfy the stale CodeGraph absence assertion by deleting the ignore.

Current parallel owners after T21 handoff: T18 candidate Halley; T19 docs
Ptolemy; historical 55ed Meitner; T16 resume Dewey; T14 path-scan Archimedes.

## Rules for the remainder

- Preserve each original HEAD and dirty tracked content in a checkpoint ref
  before conflict resolution; preserve untracked content as well.
- Resolve conflicts by behavior and ownership, not blanket ours/theirs.
- Keep T14 responsible for the current `/api/context/pack` behavior.
- Record remaining failures and unfinished behavior in this log or the
  checkout's integration note; do not mark task acceptance done from a merge.
- Merge finished branch results into master sequentially and resolve overlaps
  across tasks there. Repeat synchronization to the final master afterward.
- Run final release gates after the integrated source is assembled.

## Checkpoints prepared before manual merges

## Additional integrations, 2026-10-06

These integrations preserve unfinished work. None is release acceptance or a
claim that the corresponding task is done. Historical checkpoints and stashes
remain preserved. Generated runtime/cache data is not committed.

| Checkout | Integrated result | Actual verification and remaining work |
| --- | --- | --- |
| t13-clean-candidate | `f4c03877` | Manual reconciliation of four conflicts; retained capacity/reservation and async tests, plus current language-hint test. `python -B -m pytest -q -p no:cacheprovider tests/test_conversations.py tests/test_mcp_agent_routing.py -k 'start_reserved or conversation_start_at_capacity or reserves_new_conversation or async_job or explicit_language_hint' --tb=short --maxfail=4`: 10 passed, 4 failed, 62 deselected. Async control/wait/submit contracts remain unfinished; no expectations weakened. Details: `handoff/T13-CLEAN-CANDIDATE-SYNC-20261006.md`. |
| t19-docs-rollout | `2c7ff77a`, merged as `11a10718` | Production `src/` unchanged against pinned master; ordinary untracked documentation and receipts preserved. Worker checks: 108 passed, 4 failed; inventory 14 passed, 1 failed, followed by restored OPTIONS metadata regression 1 passed. Final inventory: 660 rows, no drift. Stale policy assertions and clean-host/runtime acceptance remain open. Details: `handoff/T19-SYNC-20261006-INTEGRATION.md`. |
| t16-resume-20260926 | `b9b6fa36`, merged as `1d46e653` | Reviewed containment and symlink/reparse-point protection in `_safe_work_target`; retained current master fencing. Worker checks: initial 77 passed, 6 failed, 2 skipped; junction follow-up 1 passed; recovery 17 passed, 1 skipped; AST checks 4 passed. Five policy/legacy lease failures remain. Details: `docs/T16_SYNC_INTEGRATION_20261006.md`. |

### Preservation rule

T16 orchestration-recovery `75b8917f` is integrated as `f99619a4`.
Reviewed production delta: import layout and blank-line-only differences;
current fencing, private transaction and safe rollback behavior retained.
Original checkpoint `49ced58f` preserves all 87 ordinary untracked files and
the historical dirty work. Fresh root command `python -B -m pytest -q -p
no:cacheprovider tests/test_work_fencing.py --tb=short --maxfail=3`: 12 passed,
1 skipped in 4.33 seconds (Windows symlink privilege unavailable).
Owner's rollback/command-policy/legacy lease-fixture failures remain open.
Details: `handoff/T16-recovery-sync-20261006-integration.md`.

Current Git ancestry inventory after these integrations: 60 registered
worktrees, 55 HEADs reachable from master, five unique HEADs pending integration.
Those five are owned by active workers: hub-audit-repairs, T13 lifecycle,
T17 multimodal resume, T18 status dashboard and T17 browser flow. Reachability
does not mean final fast-forward synchronization, clean runtime state or release
acceptance. Remaining historical stashes still require coverage reconciliation;
no stash was dropped, checkpoint ref deleted or worktree removed in this run.

### Concurrent root edits discovered after integration

The subsequent dirty inventory found new, unattributed tracked modifications in
`src/local_ai_hub/agent_events.py` and `src/local_ai_hub/client.py`, besides the
preserved runtime database. These edits were not made by the orchestrator's
integration patches and are not staged, reverted or overwritten. Owner/handoff
requested. Earlier targeted receipts do not certify this newly modified source.
Reviewed concerns: Windows backup ACL application now catches/ignores all
exceptions and substitutes USERNAME for whoami; durable backup confidentiality
must remain fail-closed. Pubsub payload/sequence changes and SDK fixed-action
payload ordering need the owner's regression receipts. Root is not clean;
avoid merges across these two paths until attribution/reconciliation is ready.

Subsequently `http_server.py` also changed outside orchestrator ownership:
an explicit worktree-memory-delete 403 guard was added. Preserve it uncommitted
pending owner handoff. Observed SHA256s for attribution (not acceptance):
agent_events.py `226235956A405F6133947C62ECEC76BFE4857B1AF8912B4BC17C4AF98F4441D5`,
client.py `C65E72B3B72097470C2E9B4365C9EDDCFA6C457B53FBB56734DA03D82A36C98C`,
http_server.py `9CD9B11276C3AFDE684460C92B591369B53D92E824B39C17814D06203DD3A06E`.

Hub-audit-repairs packet `0e4c62c2` integrated as `5283a418`; its production
delta only affects async_jobs.py, with no write to the three concurrent dirty
paths. Historical async dispatch deadlines clear on cancellation/recovery/expiry,
and due-time selection is inclusive. Fresh root command `python -B -m pytest
-q -p no:cacheprovider tests/test_async_jobs.py --tb=short --maxfail=3`:
29 passed in 11.31 seconds. Owner benchmark units and guards passed, but queue
diagnostic label sanitization and whole paired benchmark acceptance remain open.
Details: `docs/integration-hub-audit-repairs-20261006.md`. The same existing
worker now owns the independent 45-stash coverage audit; no stash is applied,
dropped or claimed covered without evidence.

Untracked inventory of already-integrated checkouts primarily contains retained
test state: T04 artifacts/t04-sync-pytest-20261006, T08 handoff test-temp,
T16 resume .merge-checks, T17 vision .t17-merge-tmp and 4816 scratch checkout.
These are preserved, not automatically staged or deleted. T15 historical JSON
receipts remain enumerated separately. The registered temporary checkout
lah_wt_worktree_e64978b4714c still has one tracked and one untracked change,
with owner unresolved; it must not be silently classified as reconciled merely
because its HEAD is reachable from master.

T15 command-config `fdbf3ec3` is integrated as `fcbb1d6f`. Active runtime is
identical to owner's pinned master; 44 original source/test/tool/handoff files
are preserved, including benchmark source-pin and fixture tools. Fresh root:
`python -B -m pytest -q -p no:cacheprovider
tests/test_command_cache_singleflight_contract.py tests/test_project_command_broker.py
--tb=short --maxfail=3`: 29 passed in 5.77 seconds. Owner's three remaining
coalesced-cache/affected-test result contract failures are still open. Twenty-one
historical runtime receipt JSONs remain preserved on disk and enumerated in
`docs/integration/T15-COMMAND-CONFIG-SYNC-20261006.md`; not current evidence.

069d `06204d01` is centrally reconciled against `fcbb1d6f`; original checkpoint
`57ee7a49` preserves 187 tracked plus 295 ordinary untracked source, test,
tool and historical handoff files. Manual conflicts retain current optional
Serena/standalone CodeGraph guidance, synthesis scope caveat, duplicate-safe
historical actor-idempotency test names and structural allowlisting of mandatory
CodeGraph ignore markers. Repository memory tenant filtering remains applied
once in the common scope clause (only redundant application removed); trusted
promotion scope check remains. Ordered receipt/memory publication retained.

Fresh root checks: `python -B -m pytest -q -p no:cacheprovider
tests/test_t10_like_suffix_escape.py tests/test_telemetry_privacy.py
tests/test_agent_receipt_completion_t09.py tests/test_agent_task_memory_adoption.py
tests/test_sync_codegraph_scan_ignore.py --tb=short --maxfail=4`: 40 passed in
23.78 seconds. `python -B -m pytest -q -p no:cacheprovider tests/test_agent_tasks.py
-k 'idempotency' --tb=short --maxfail=3`: 6 passed, 38 deselected in 1.00 second.
Owner's memory promotion fixture and legacy AGENTS text failures remain open;
no source/runtime/provider/release completion inferred. Details:
`handoff/SYNC-069D-20261006.md`.

T17 vision-refactor packet `04bbeb19` is integrated as `0aebfbd9`.
Reviewed preservation of process safety, cancellation/preflight checks, bounded
prompt/output, evidence-grounded DOM facts and current T14 retrieval. Fresh
root command `python -B -m pytest -q -p no:cacheprovider
tests/test_vision_contracts.py tests/test_vision_service.py
tests/test_http_vision_routes.py --tb=short --maxfail=5`: 139 passed, 4 failed
in 30.42 seconds. Remaining: old bbox interpretation/error expectation,
PNG fixture lacks IHDR, parsed tuple fixture lacks image dimensions, golden
response differs on empty artifact IDs/observation_sources. Owner's nine
process/transcription failures remain open. Source process_utils is unchanged
against owner's pinned master; no process-safety weakening. Exact receipts and
historical original handoff: `handoff/t17-vision-refactor-sync-20261006.md`.
This is preserved unfinished integration, not vision/runtime/release acceptance.

| Additional checkout | Root integration | Verification and unfinished acceptance |
| --- | --- | --- |
| t13-operational-mode-resume-20261004 | `f5794721` | Current locked/revisioned mode protocol retained; historical incompatible source/test files preserved verbatim in committed integration archive and checkpoint. Early inference/preprocess/background gates ported to current protocol. Exact check: `python -B -m pytest -q -p no:cacheprovider tests/test_sync_opmode_resume.py tests/test_operational_mode.py tests/test_tiered_ollama_runtime.py --tb=short --maxfail=4`: 39 passed in 8.70 s. Live VRAM release and unload end-to-end deadlines remain unverified. See `docs/integration/T13-OPMODE-RESUME-SYNC-20261006.md`. |
| t18-candidate-2b33602 | `70059e18`, root merge `5538bd11` | Retained current ordered state, error redaction, auth and T14 behavior. Fresh root `python -B -m pytest -q -p no:cacheprovider tests/test_telemetry_privacy_t18.py tests/test_telemetry_self_accounting.py tests/test_status_snapshot_quality.py --tb=short --maxfail=4`: 29 passed in 3.06 s. Owner UI/status 164 passed, but trace paging backend, SSE expectations and remote-mode contracts remain unfinished. See `docs/T18_SYNC_INTEGRATION_20261006.md`. |
| t16-e2e-recovery-20261004 | `387ecbdf`, root merge `1fa8c6f1` | Retained strict receipt provenance, server-derived memory identity, stable startup lock inode and worktree owner-ID forwarding. Fresh root `python -B -m pytest -q -p no:cacheprovider tests/test_client_start_lock_owner.py tests/test_worktree_release_ownership.py --tb=short --maxfail=3`: 7 passed in 4.68 s. Owner broader checks 110 passed, 20 failed, 1 skipped; receipt/policy fixtures, lease DB, MCP schemas and search fallback remain unfinished. See `docs/T16_E2E_SYNC_INTEGRATION_20261006.md`. |

Ready packets still pending integration review: T10 resume `e4c14ded` (owner
78 passed, 5 skipped; nine JSON artifacts retained outside commit require
classification), historical 55ed `b99482f8` (owner 129 passed, 2 failed;
inventory 51 passed, 668 rows, zero drift). These are not root-integrated or
release accepted. Independent workers own broad 069d, T17 vision refactor,
T15 command config, T18 status dashboard and T16 orchestration recovery.

Historical 55ed packet `b99482f8` is now centrally reconciled against root
`3a43536a`. Four conflicts resolved: preserve both doctor/release test sets,
retain explicit terminal/non-retryable native fallback rule plus bounded-read
guidance, regenerate API coverage from combined source. `python
tools/surface_inventory.py --write-doc` and `python tools/surface_inventory.py
--check`: 705 rows, no drift, coverage matches. Fresh root command `python -B
-m pytest -q -p no:cacheprovider tests/test_doctor_support.py
tests/test_operation_contracts.py tests/test_release_contract.py --tb=short
--maxfail=4`: 65 passed, 4 failed in 13.85 seconds. Release assertions forbid
ALTER TABLE despite retained safe lease migration, and ban all CodeGraph text
despite explicit standalone-outside-Hub guidance. Expectations remain unchanged;
these contracts are unfinished, not release accepted. Earlier mistyped test
filename collected no tests and is not counted as validation.

T10's nine originally untracked historical benchmark JSON/schema files were
classified as archived evidence, not runtime databases, and committed in their
existing checkout as `0ad7e821` (original result `e4c14ded` remains ancestor).
They are preserved exactly, not counted as current performance proof. Root
integration is now reconciled against `04ff61eb`, including packet `0ad7e821`.
Seven central conflicts resolved by behavior: retain T14 candidate controls
and string/dict hints, T10 backend selection/confidence/deadline diagnostics,
benchmark source-origin guard and T10 origin checks, both backend-removal
assertion sets, current external-tool guidance and bounded-read instructions.
Two formerly checked T19 rollout items are reopened for the final combined
source; historical receipts remain in merge parents and handoffs.

Fresh root command: `python -B -m pytest -q -p no:cacheprovider
tests/test_t10_transitive_dependencies.py tests/test_t10_incremental_callgraph_edges.py
tests/test_t10_snapshot_cache_capacity.py tests/test_context_delivery.py
tests/test_preprocess_operational_mode.py tests/test_codegraph_package_policy.py
--tb=short --maxfail=5`: 72 passed, 1 failed, 5 skipped in 37.09 seconds.
Failure: CodeGraph substring audit rejects generator's standalone removal
guidance, not a restored backend. Five language parser checks skip because
parsers are unavailable. No expectations weakened, full runtime/benchmark
acceptance not established. Historical JSON evidence is not current performance.

Post-reconciliation T10 checks: AST parsing of seven production files plus
tools/benchmark_surfaces.py passed (8 files). `python tools/surface_inventory.py
--write-doc` followed by `python tools/surface_inventory.py --check`: 705 rows,
no drift, coverage matches. Source/test/benchmark conflict-resolution diff check
passed. Root runtime database remains preserved outside the commit.

Root validation left an untracked `agent_state.sqlite` runtime database. It is
preserved in place and intentionally not staged or deleted; it is not ordinary
source/handoff work. Tracked source/index is clean after the integration record
commit, but the checkout must not be described as wholly untracked-clean.

T17 historical acceptance checkout is synchronized and integrated as
`3efc1735`, retaining tracked checkpoint `5b16828e` and previously untracked
Gemini audit specification committed as `67656de3`. Manual transcription test
conflicts retain both historical error contracts and current process helper,
timeout and cleanup assertions. Check: `python -B -m pytest -q -p no:cacheprovider
tests/test_t17_auxiliary_formats.py tests/test_vision_contracts.py
tests/test_transcription_contract.py --tb=short --maxfail=4`: 96 passed, 3 failed
in 7.21 seconds. Parsed tuple fixture returns no finding; nonzero transcription
lacks returncode; timeout transcription lacks retryable. These preserved
unfinished contracts are not accepted as done. Details:
`docs/integration/T17-ACCEPTANCE-SYNC-20261006.md`.

Live-context benchmark reconciliation is integrated as `6a57d65d`.
The historical live/offline benchmark and current benchmark were different
implementations sharing one filename. Both are retained, with the historical
implementation in `tools/benchmark_context_pack_live_quality.py`; its tests
import that module. `python -B -m pytest -q -p no:cacheprovider
tests/test_context_pack_live_benchmark.py --tb=short --maxfail=3`: 15 passed in
1.55 seconds. This is helper validation, not live model/release acceptance.
Details: `handoff/LIVE-CONTEXT-BENCHMARK-SYNC-20261006.md`.

T14 path-scan returned committed merge `13713fc4`, checkpoint `3b35d5d4`,
pinned master `896fbedb`; root integration is `340b56a6`. Reviewed root-scoped
normalization, exclusion precedence, bounded candidate consumption, preservation
of current project configuration and no broad scan for targeted empty packs.
Worker reports 83 passing targeted checks with its documented temp/Git ceiling
environment. Fresh root command `python -B -m pytest -q -p no:cacheprovider
tests/test_context_delivery.py tests/test_context_path_hints_skip_unbounded_scan.py
tests/test_repo_tools_path_hints.py tests/test_t10_repo_search_path_hints.py
tests/test_project_path_hints.py --tb=short --maxfail=3`: 82 passed, 1 failed in
29.59 seconds. Failure: `test_context_pack_expands_only_bounded_hint_directory_with_exclusions`,
missing `evidence` key. Two unchanged affected-test failures and the obsolete
CodeGraph-string audit remain from owner checks. Candidate consumption is
bounded, but the initial `indexed_paths(root)` call and physical filesystem
traversal cost still need end-to-end performance verification. Not done.

Commit relevant tracked dirty changes and ordinary untracked source, tests,
documentation and handoffs even when unfinished. Record outstanding behavior
and exact check results here or in the checkout's committed integration note.
Never substitute a stash for reconciliation or silently discard historical
work. Integration does not authorize release, deletion of checkpoint refs,
or marking acceptance complete.

On 2026-10-06, 29 additional detached checkouts had their existing tracked
dirty state committed (576 changed-path occurrences across the checkouts).
These are preservation checkpoints only. They have not yet all been merged
with master or integrated. Each original state remains reachable through
`codex/checkpoint-<checkout>-dirty-20261006` and the corresponding
`codex/sync-<checkout>-20261006` branch. Untracked files remain in place for
the assigned merge worker to commit; runtime state remains outside Git.

| Checkout | Dirty checkpoint |
| --- | --- |
| 069d | `0f9a5f12` |
| 4816 | `72ddb032` |
| fefe | `da3d5945` |
| hub-audit-repairs | `91b73fc9` |
| t06-write-set-resume | `f8deb793` |
| t07-idempotence-root-current-20261003 | `c041d450` |
| t08-agent-os | `4ce893c1` |
| t09-root-current | `85972ae1` |
| t10-path-hints | `4e34d3a9` |
| t10-resume-20260926 | `6c343bf1` |
| t13-clean-candidate | `9b1b4090` |
| t13-lifecycle-8429 | `708282ff` |
| t13-operational-mode-resume-20261004 | `5a3fbbb2` |
| t13-operational-mode | `af119626` |
| t14-context-budget-recovery | `563f661e` |
| t14-path-scan | `3b35d5d4` |
| t14-render-order | `3524b558` |
| t14-snippet-isolated | `9a40aeca` |
| t15-command-config | `997a89a7` |
| t16-e2e-recovery-20261004 | `80d2dcb5` |
| t16-orchestration-recovery | `c6c38c5e` |
| t17-acceptance-2026-09-24 | `5b16828e` |
| t17-multimodal-resume | `a9d9afe8` |
| t17-vision-refactor | `7951ebff` |
| t18-candidate-2b33602 | `fcb49e48` |
| t18-status-dashboard | `81635485` |
| t19-docs-rollout | `974fed0d` |
| t21-project-config | `b568928b` |
| t17-browser-flow-20261004 | `fbe44e0c` |

### Explicit unfinished-work commit policy (2026-10-06)

The user explicitly requires committing relevant dirty source, tests, documentation,
and ordinary untracked handoffs after reconciliation, even when acceptance remains
unfinished. Preserve original checkpoints; record failing tests and remaining work
in committed integration notes. A preservation or merge commit is not a completion
receipt. Runtime databases, caches and test scratch remain preserved outside Git.

T17 browser handoff `e3d27bb2` is integrated into master. Its net change against
the pinned master is the integration note; original work remains in merge ancestry.
Owner checks: 256 passed, 14 failed; unresolved acceptance is documented in
`docs/integration/T17-BROWSER-FLOW-SYNC-20261006.md`.

T13 lifecycle `04a93ca7` and T17 multimodal `0c571b61` have committed handoffs.
Their integration remains pending review and resolution of concurrent, unowned
root edits in `client.py` and `http_server.py`; these edits were not overwritten
or included in an orchestrator commit. The existing temporary checkout
`lah_wt_worktree_e64978b4714c` is assigned to the browser reconciliation worker
to preserve and merge its render-performance dirty source and regression test.

#### Concurrent root source preservation, not acceptance

Following the user's explicit request to commit unfinished dirty work, the
orchestrator preserves the observed concurrent root edits in a separate WIP
commit without editing their source. Changed paths: `agent_events.py`, `client.py`,
and `http_server.py` under `src/local_ai_hub/`. Their original editing owner is
still unconfirmed; this commit establishes preservation, not approval or test
acceptance. Later concurrent writes remain untouched and must be reconciled.

Observed issues needing review after synchronization: the Windows backup ACL
setup swallows all exceptions, potentially defeating fail-closed confidentiality;
a transient empty `if` in the memory GET scope block was repaired by the concurrent
writer before the preservation commit. Explicit/query tenant handling still must
not bypass authenticated identity. The SDK fixed-action
payload ordering and worktree-delete denial also need targeted verification.
No test result is claimed for this unfinished source snapshot. `agent_state.sqlite`
remains outside Git. No source hunk was rewritten to create this preservation.

#### T13 lifecycle root integration

Packet `04a93ca7045e341e25f1957900137993f1d0dbe0` merged without conflicts on
top of root preservation `7715b1a1`. Original checkpoints and unfinished owner
results remain in `handoff/T13-takeover-sync-20261006.md`. All 18 staged Python
files parsed successfully. Fresh root check, with `PYTHONPATH` set to root `src`:
`python -B -m pytest -q -p no:cacheprovider tests/test_client_transport.py
tests/test_http_code_find_symbol_include_body.py --tb=short --maxfail=4`:
42 passed in 8.25 seconds. `git diff --cached --check` reports one trailing-space
line inside the original archived handoff patch; its original bytes are retained.
These targeted checks do not establish lifecycle, security, or full release
acceptance. Concurrent root security/memory issues listed above remain open.

#### Final synchronization pass and stash follow-up

The bounded fast-forward pass finished against immutable pin `90e6f295`.
It excluded root and the five currently assigned worker checkouts. Before each
fast-forward it required a clean tracked tree and ancestry, and retained the old
HEAD at `refs/checkpoints/pre-final-sync-20261006/<absolute-path-sanitized>`.
Original benchmark pins therefore remain recoverable; changing the checkout
does not refresh historical benchmark receipts. No stash, runtime artifact,
or checkpoint was deleted. This pass synchronizes to its pin, not to later root
integration commits; a final pass is still required after remaining integrations.

Root integrated stash audit `ee12a4f4` and render handoff `41296d26`. The render
source/test already matched pinned master; owner equivalence check: 2 passed in
0.25 seconds. Audit details: `docs/STASH_COVERAGE_20261006.md`. All 45 stashes
remain intact. Fourteen have unmatched versions requiring manual hunk decisions:
32 tracked/index versions and 404 untracked versions, including 22 direct active
source/test/tool/document paths. Exact checkpoint preservation is not proof of
integration. Separate existing workers now own the 22 active untracked candidates
and the 32 tracked/index hunk disposition report. No duplicate task was created.

Additional concurrent root writes appeared after `7715b1a1`: explicit caller
`repository_id` fallback in memory GET/POST handling. They are preserved in a
separate unfinished snapshot without source editing. Their editing owner is
still unconfirmed. Caller-provided repository/tenant identity must be reviewed
against authenticated scope before release; this snapshot is not approval to
trust it. Root runtime `agent_state.sqlite` remains uncommitted.

#### T17 multimodal root integration

Immutable synchronized packet `84cb230b` preserves original `a9d9afe8` and
ordinary untracked checkpoint `774d1d8c`, with all unfinished acceptance in
`handoff/t17-multimodal-resume-sync-20261006.md`. Root merge on `deda200a`
completed without conflicts; 17 staged Python files parsed successfully and
source/test whitespace checks passed. Fresh root command with root `src` on
`PYTHONPATH`: `python -B -m pytest -q -p no:cacheprovider
tests/test_vision_service.py tests/test_vision_contracts.py
tests/test_http_vision_routes.py --tb=short --maxfail=4`:
150 passed in 37.08 seconds. This does not supersede the owner's two remaining
transcription failures or its unverified process/audio/browser acceptance.

#### Checkpoint ancestry reconciliation

T08 checkpoint `7153deb5` merged with an unchanged resulting tree: its five
historical acceptance logs were already present. T06 checkpoint `4e1ee2ac`
also has no active source/test/tool delta. Its 107 add/add handoff conflicts were
individually checked using `git diff --ignore-cr-at-eol --quiet HEAD 4e1ee2ac
-- <path>`; all 107 matched ignoring CR only. Resolution retained the current
normalized bytes, with both exact original trees retained in merge ancestry.
The resulting staged tree was unchanged before this note. This is proven
newline-only archival reconciliation, not a claim that each historical patch's
behavior satisfies release acceptance.

#### T18 status/dashboard root integration

Committed owner result `0e4689bf` merged manually after T13/T17. Preserved the
current status/privacy/dashboard behavior and T14 `/api/context/pack` ownership;
the sole conflicted source file was `http_server.py`. Resolved its import and
monitor-path unions, retained root task-scope denial and memory compact/reap/
relation gates, kept the current route registry and the T18 bounded status,
telemetry and trace helpers. The T18 handoff records prior pinned-90 decisions.
Ten changed source files parse; `git diff --cached --check -- src tests tools`
passed.

Fresh targeted command:
`python -B -m pytest -q -p no:cacheprovider
tests/test_http_post_route_registry_t18.py tests/test_agent_state_transport.py
tests/test_t14_context_pack_agent_memory.py --tb=short --maxfail=5`.
Result: **14 passed, 5 failed in 31.59 s**. Failures: POST route golden ordering
(`post_config_update_1` before `post_bundle_import_1`), telemetry dispatch line
ordering, scoped memory GET returns HTTP 400 in task-scope isolation test,
verification receipt preflight returns 403 instead of expected 400, and
worktree-scoped memory deletion returns 400 instead of expected 403. These
remain open; no expectations were weakened. This command did not reach the
entire T14 memory suite because `--maxfail=5` stopped at the fifth failure.
Owner's 42 known T18 failures and unverified full release remain open.

#### Stashes must be integrated, not merely preserved

The user reaffirmed that stash retention must not conceal unintegrated work.
The following existing workers own disjoint reconciliation queues. A checkpoint
match or archived copy alone cannot close any functional integration criterion.

| Queue | Existing owner/worktree | Current status | Required handoff |
| --- | --- | --- | --- |
| 22 unmatched direct active-path untracked versions | Russell; hub-audit-repairs | active | Reconcile relevant source/tests, actual checks, exact original SHAs and missing caller blockers; commit unfinished changes |
| 32 unmatched tracked/index versions | Confucius; existing context-render temporary checkout | active | Original-hunk/current-symbol dispositions and concrete missing integration list; no source writes during overlapping owner work |
| 382 unmatched archive/overlay/handoff versions | Tesla; t17-multimodal-resume | active | Preserve authored originals and map executable patch/overlay intent to current code; identify missing functional hunks, not just archived bytes |
| Exact-witness tracked/index versions | Helmholtz; t13-lifecycle-8429 | active | Prove actual current integration or reviewed reconciliation; checkpoint ancestry alone is insufficient |

T18 status/dashboard synchronization remains active under Sartre in its existing
checkout. Root source integration is sequential. All 45 stash objects remain
unchanged; no stash is declared disposable based on blob equality or ancestry
alone. Missing functional hunks found by these queues must receive explicit
source ownership, implementation, and validation before release acceptance.

#### Tracked/index hunk disposition handoff

Confucius delivered branch `release_context_render_perf_20261006`, commit
`19ff3fc2` (parent `47a1f32f44f0ab23a17b5d6cc21c16dfc2549a1a`), from the
existing checkout `lah_wt_worktree_e64978b4714c`. Its only change is
`docs/integration/STASH-TRACKED-HUNK-DISPOSITION-20261006.md`: static
dispositions for 32 immutable versions, 29 paths, and 533 unique hunk rows
(332 behavior-preserved, 77 master-improved, 17 missing, 107 conflict-owner
needed). The note binds original/base/current/checkpoint SHAs and per-hunk
locations/evidence. It did not patch source, run tests/imports, or delete/apply
stashes; its static findings are not runtime acceptance.

Seven source queues are identified: T08 configurable worktree TTL (V03-H012/
H014), terminal task retention in no-query listing (V03-H019), repeated
completed-task revalidation (V03-H029/H030/H034), generation blocker/error
propagation (V03-H036, V04-H041), strict receipt field types (V04-H018/H020/
H021, V10-H003), WorkOrchestrator evidence/final receipts (V08-H009/H012/H013),
and T05 task-root/tenant guard (V14-H004/H058). First-completion trusted
project evaluator, all 17 original INDEX service hunks, hard-ignore, and
no-CodeGraph context policy are classified as preserved/improved, not to be
blindly reverted. The 107 overlap conflicts remain explicitly owner-routed.
Source ownership and tests are still required for each remaining missing queue.

The WorkOrchestrator queue is now repaired in root: evidence-required test or
benchmark criteria trigger final validation without file changes; handoff
artifacts and cancelled terminal payloads include collected verification
receipts. Regression suite `tests/test_work_orchestrator.py` passed **24/24**
in 22.43 s, and `git diff --check` passed. The other six queues remain pending
scoped owners/implementation and acceptance; this handoff alone does not close
them. All original checkpoint refs/stash objects remain preserved.

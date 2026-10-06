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

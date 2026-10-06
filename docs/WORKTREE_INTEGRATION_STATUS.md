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
| T01 inventory | active | Popper the 2nd; t01-coverage-main-verify | Manual merge, checkpoint preservation, commit of unfinished changes; release inventory regeneration follows the final integrated source. |
| T02 quality baseline | integrated; unfinished | Gibbs the 2nd; t02-quality-baseline-resume | Branch `codex/sync-t02-master-20261006`, head `673d1a0b`, merged into master. Checkpoint `codex/sync-t02-checkpoint-20261006` retains original dirty content. Targeted command in `handoff/T02-sync-integration-20261006.md`: 18 passed, 78 deselected. Runner still uses removed checkpoint/resume CLI flags; real-input baseline and historical intermittent test failure remain unresolved. Nine original untracked artifacts retained unchanged. |
| T06 safe-command checkout | active | Wegener the 2nd; t06-safe-commands | Merge current master, commit existing dirty content, preserve rollback/fencing safety and record unfinished acceptance. |
| T05 identity / memory | active | Maxwell the 2nd; t05-identity-recovery | Manual merge; retain current master identity isolation and review older task hunks. |
| T03 contracts | integrated; unfinished | Einstein the 2nd; t03-contracts-resume | `32c5079b` merged into master. Original/dirty refs `codex/checkpoint-t03-original-20261006` and `codex/checkpoint-t03-dirty-20261006` preserve the old state. Focused follow-up: 169 passed, 3 failed. Schema parity, gaming/maintenance dispatch and earlier memory-scope HTTP 404 remain unresolved. Additional original untracked handoffs are being committed separately. |
| T04 transport / startup | active | Raman the 2nd; t04-integration and t04-lock-recovery | Reconcile both existing dirty variants with master; unfinished work recorded, not discarded. |
| T26 preprocessing argv | synchronized and integrated; acceptance partial | orchestrator; t26-preprocess-argv-5361 | Original dirty content committed at `e2f7e296`, retained by `codex/checkpoint-t26-dirty-20261006`. The dirty addition was an exact duplicate of the existing test; deduplicated at `9e7df358`. Merge into master has identical final tree and preserves both commits. No new T26 test run in this phase. |
| T10 exceptions/search checkout | synchronized and integrated; acceptance partial | orchestrator; t10-exceptions-search | Dirty ignore-directory change preserved in `6224ec20` and `codex/checkpoint-t10-exceptions-20261006`. Seven conflict hunks manually resolved: retain `.codegraphcontext`, project policy-aware scanning, scoped accelerator candidates, bounded Python fallback, and counters from current master. Final staged tree exactly matched master; historical T10 changes are preserved in merged ancestry. `git diff --check` passed; no new functional test run. Other T10 worktrees still pending. |
| T11 recovery-v2 checkout | synchronized and integrated; unfinished | orchestrator; t11-rag-recovery-v2 | `a1169d6c`: all ten original untracked handoff/test files committed after master merge. Archived patches and project-config source copy retained as handoff evidence, not applied to runtime source. Overlay tests and original PARTIAL acceptance remain to verify after consolidated integration. Other T11 dirty worktrees still pending. |
| Clean checkouts / inactive branch refs | synchronized to intermediate master | orchestrator | 17 clean checkouts fast-forwarded to `9b794d7f`; original history remains in master ancestry. Inactive task refs fast-forwarded with ancestry check and compare-and-swap. Checkpoint refs remain pinned; a brief accidental advancement of two T04 original checkpoint refs was immediately restored to `3658d505` before continuing. Final synchronization will repeat after all merges. |
| T15 recovery location | missing checkout; investigate | orchestrator | `C:/Users/Adam/.codex/worktrees/t15-recovery` parent still exists, but `.local-ai-hub` is missing and the checkout is no longer registered. This run issued no removal/archive command for it. Recover original handoff content from available archive/refs before closing this item. |
| Remaining worktrees | pending reconciliation | orchestrator assigns one checkout per worker | Inventory identified 66 registered checkouts. Original tracked/untracked changes and stashes remain preserved; completion requires per-checkout merge and final ancestry/status checks. |

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

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
| T02 quality baseline | active | Gibbs the 2nd; t02-quality-baseline-resume | Manual merge of runner/diagnostics with current master; real-input baseline and historical intermittent test failure are not confirmed resolved. |
| T05 identity / memory | active | Maxwell the 2nd; t05-identity-recovery | Manual merge; retain current master identity isolation and review older task hunks. |
| T03 contracts | active | Einstein the 2nd; t03-contracts-resume | Manual merge and commit of existing dirty changes; root forwarding regression already integrated. |
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

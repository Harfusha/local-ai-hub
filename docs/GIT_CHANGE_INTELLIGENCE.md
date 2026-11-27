# Git Change Intelligence and Commit Orchestration

## Contract

Git Change Intelligence (GCI) observes the current Git worktree, produces bounded change evidence and supports explicit staging and ordered commit publication. A proposal, summary, model suggestion, review declaration or green test is not commit authority.

The Git snapshot is the sole source for change classification. Every publication uses an ordered preview and exact-tree verification receipts, including a one-step commit. The native desktop is the sole operator UI. The only compatibility transition permitted for this product is a one-time migration during update; runtime aliases and alternate paths are not supported.

## Current behavior

- Inventory is Git-root scoped. It records staged, unstaged, untracked, conflict, rename/binary and patch availability where Git exposes them. Incomplete or inconsistent observations are marked unavailable or fail closed.
- Change IDs bind observed Git identity and content-derived patch/hunk evidence. Derived summary caches do not contain verification authority.
- Changed paths are independent candidate groups unless explicit, bounded dependency evidence relates them. Dependency output separates hard dependencies, soft dependencies and uncertain candidates. Uniquely resolved import and import-removal relations are soft; ambiguous and unmatched relations remain uncertain. Evidence lists cap at 16 and report omitted observations. Hard dependencies are empty until deterministic hard evidence is implemented. Candidate ordering and strongly connected components are advisory and do not verify dependency completeness.
- MCP and HTTP expose bounded projections. Summary, details, semantic suggestion and artifact paging use one projection contract. Semantic suggestions remain advisory.
- Staging requires exact observed revision, path/hunk selection and preview tree. Apply rechecks the Git state and never stages paths outside that selection.
- Commit publication requires an ordered sequence, its preview digest, exact intermediate trees and current verification receipts for every step. One-step sequences use the same path. The executor uses an isolated index and branch compare-and-swap; it does not blanket-stage, rewrite history or push.
- The desktop application is the operator UI. It exposes observation, preview/apply staging, sequence editing, verification, receipt status and commit recovery.
- Project Git-first knowledge and task declarations are contextual evidence. They do not establish authenticated authorship or turn review into verification.

## Acceptance traceability

The requirement IDs refer to sections in the user-supplied GCI completion specification.

| Specification | Current evidence | State / remaining acceptance |
|---|---|---|
| §6 Snapshot engine and Change Ledger | `src/local_ai_hub/split_changes.py`, `change_ledger.py`, `tests/test_git_change_intelligence.py` | Partial: Git-visible observations and ledger exist; complete multi-worktree snapshot coverage and all invalidation cases still require audit. |
| §7 Provenance and agent work | Change annotations and Agent OS integrations | Partial: declarations are explicitly unverified; authenticated editor/agent authorship and full provenance lifecycle remain open. |
| §8 Semantic change analysis | Bounded Python AST summaries and import candidates | Partial: supported-language and syntax coverage is limited; no whole-program semantic claim. |
| §9 Grouping and dependency graph | `src/local_ai_hub/change_dependencies.py`; `tests/test_git_change_intelligence.py` | Partial: uniquely resolved import and import-removal relations are soft dependencies; ambiguous and unmatched observations are uncertain candidates. Evidence lists cap at 16, uncertain records at 256, and paths/groups at 16; omitted counts remain explicit. Hard dependency evidence, unchanged consumers, test/migration/config/build edges, and dependency completeness remain open. |
| §10 Incremental context and token budgets | Projection, pagination, artifact and delta paths | Partial: verify actual MCP wire envelopes and invalidation across all consumers. |
| §11 Review and verification | Exact-tree sequence receipts in `change_tree_verification.py` | Partial: receipt identity is implemented; dependency/environment completeness and Agent OS receipt interoperability need acceptance evidence. |
| §12 Planning, staging and commits | Previewed stage operations and sequence-only publication in `change_stage_execution.py` and `change_commit_execution.py` | Partial: targeted paths pass; audit crash recovery, concurrent writers, Git edge cases and all intermediate-tree invariants before release. |
| §13 Agent OS integration | Task, lease, journal and verification integration | Partial: end-to-end task lifecycle and receipt reuse must be proven against current Agent OS contracts. |
| §14 MCP, HTTP and CLI | Shared projection and sequence APIs; `tools/hubctl.py` | Partial: route parity, budgets, schema and rejection of retired inputs need full contract coverage. |
| §15 Native Rust desktop | `desktop/src/main.rs` | Partial: current operator flow exists; complete feature parity, error recovery, accessibility and packaging need current-platform validation. |
| §16 Remove web dashboard | Dashboard route, settings, update marker and docs removed; `tools/update_transaction.py` replaces the installed `src`/`tools` trees and transactionally removes the retired `auto-update-dashboard.json` report | Implemented for source and update path. The prior dashboard had no dedicated dependency manifest or dashboard-only package requirement; regular dependency reconciliation remains part of update. Migration rollback restores the report if activation fails. |
| §17 Git-first project knowledge | Existing Git-backed repository knowledge subsystem | Partial: verify identity, freshness, conflicts and GCI linking end to end. |
| §18 Critical audit | This completion task | In progress; findings must map to source and tested revision. |
| §19 Performance | Bounded Git runner, cache and response projections | Partial: collect current cold/warm resource measurements on representative large repositories. |
| §20 Paired provider evaluation | No current verified external-provider measurements recorded | Open; do not infer savings or quality from local estimates. |
| §21 Test matrix | Focused Windows tests are being run against the PR worktree source | Open until required Git fixtures, platform cases and release checks pass. |
| §22 Current CI | PR #11 checks and required CI | Open until current remote head's checks finish successfully. |
| §23 Documentation | This contract and traceability map | In progress; update states only from verified evidence. |
| §24 Master and related PR integration | PR #11 plus current master and overlapping PRs | Open; inspect exact diffs and use normal review/merge workflow only after gates pass. |
| §§25–28 Definition of Done and final integration | Current goal and PR workflow | Open until every required criterion has evidence or an explicitly authorized, documented blocker. |

## Operator flow

1. Inspect the current Git change plan and its observed revision.
2. Review exact changed paths and any unavailable scopes.
3. Preview staging; apply only the selected paths or supported hunks with the returned tree identity.
4. Refresh observation after staging. Edit or accept a suggested ordered sequence.
5. Preview the exact sequence and retain its digest.
6. Verify every intermediate tree using the explicit environment capsule and command manifest. Check receipt status.
7. Publish the same sequence with the matching preview digest and current receipts.
8. Inspect the operation journal after uncertain outcomes. Never repeat publication until branch and candidate state are known.

Commands:

```text
hubctl changes summary --root <repo>
hubctl changes stage-preview --root <repo> --expected-revision <id> --changed-path <path>
hubctl changes stage-apply --root <repo> --expected-revision <id> --expected-tree <tree> --changed-path <path> --apply
hubctl changes sequence-preview --root <repo> --expected-revision <id> --expected-tree <tree> --changed-path <path> --record-file <sequence.json>
hubctl changes sequence-verify --root <repo> --expected-revision <id> --expected-tree <tree> --changed-path <path> --record-file <sequence.json> --verification-file <manifest.json>
hubctl changes sequence-apply --root <repo> --expected-revision <id> --expected-tree <tree> --changed-path <path> --record-file <sequence.json> --verification-file <manifest.json> --preview-digest <digest> --apply
```

Publication is local only. It never pushes or merges a pull request. A failed or unknown transaction requires journal inspection before any new attempt.

## Validation record

Use the worktree's own source on Windows by setting `PYTHONPATH=src`; an editable global install may otherwise import another checkout.

Earlier targeted PR-worktree run: nine suites covering commit execution, desktop control, Git change intelligence, split planning, retired CLI inputs, operator settings, desktop updates and auto-update: **305 passed**. It also passed `python -m compileall -q src tools tests`, `cargo check --manifest-path desktop/Cargo.toml`, `python tools/release_check.py --allow-installed`, and `git diff --check`.

Current dependency-graph validation on source revision `72951e10`: `python -m pytest tests/test_git_change_intelligence.py tests/test_change_commit_preflight.py tests/test_change_plan_projection.py -q` — **50 passed**. `python -m compileall -q src/local_ai_hub/change_dependencies.py tests/test_git_change_intelligence.py` and `git diff --check` passed. One earlier combined attempt saw a transient `untracked_unavailable`; its isolated rerun and this final combined run passed.

These results do not replace full CI, current critical branch coverage, paired provider evaluation, performance measurements, or Linux/macOS acceptance.

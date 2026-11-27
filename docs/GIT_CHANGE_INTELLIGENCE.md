# Git Change Intelligence and Commit Orchestration

## Contract

Git Change Intelligence (GCI) observes the current Git worktree, produces bounded change evidence and supports explicit staging and ordered commit publication. A proposal, summary, model suggestion, review declaration or green test is not commit authority.

The Git snapshot is the sole source for change classification. Every publication uses an ordered preview and exact-tree verification receipts, including a one-step commit. The native desktop is the sole operator UI. The only compatibility transition permitted for this product is a one-time migration during update; runtime aliases and alternate paths are not supported.

## Current behavior

- Inventory is Git-root scoped. It records staged, unstaged, untracked, conflict, rename/binary and patch availability where Git exposes them. Incomplete or inconsistent observations are marked unavailable or fail closed.
- Change IDs bind observed Git identity and content-derived patch/hunk evidence. Derived summary caches do not contain verification authority.
- Changed paths are independent candidate groups unless explicit, bounded dependency evidence relates them. Dependency output separates hard dependencies, soft dependencies and uncertain candidates. Uniquely resolved import and import-removal relations are soft; ambiguous and unmatched relations remain uncertain. Evidence lists cap at 16 and report omitted observations. `dependency_plan.coverage` reports `complete: false`, its input scope (`git_visible_changes`, `selected_paths` or `committed_comparison`), observed edge classes, and unmodeled edge classes. In worktree details, a bounded code-index pass also records unchanged-consumer candidates with matching changed symbols, source groups and freshness status. These remain uncertain advisory candidates and do not affect commit ordering; coverage stays incomplete. The index pass covers at most 64 changed paths and 8 returned consumers. Symbol/call-graph edges, task/test/migration/config/build/package/docs edges, semantic similarity and project conventions remain unmodeled. Hard dependencies are empty until deterministic hard evidence is implemented. Candidate ordering and strongly connected components are advisory and do not verify dependency completeness.
- MCP and HTTP expose bounded projections. Summary, details, semantic suggestion and artifact paging use one projection contract. Semantic suggestions remain advisory.
- Change-plan pagination returns the observed revision; later summary/detail pages must send that revision as `expected_revision`. Delta pages additionally return an opaque `continuation_revision` bound to the current observation and prior baseline. Later delta pages must send it; stale or missing cursors require a restart from offset zero. The prior delta baseline is retained until the last page, preventing an interrupted read from silently skipping updates.
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
| §9 Grouping and dependency graph | `src/local_ai_hub/change_dependencies.py`, `src/local_ai_hub/change_task_context.py`, `src/local_ai_hub/code_index_impact.py`; `tests/test_change_task_context.py`, `tests/test_git_change_intelligence.py` | Partial: uniquely resolved import and import-removal relations are soft dependencies; ambiguous and unmatched observations are uncertain candidates. Worktree details add at most 8 unchanged-consumer candidates with matched changed symbols/source groups and per-candidate freshness, from at most 64 changed paths. They remain advisory and do not affect commit ordering. `dependency_plan.coverage` stays incomplete. Hard dependencies, other edge classes, and complete dependency coverage remain open. |
| §10 Incremental context and token budgets | `change_plan_projection.py`, `change_plan_delta.py`, `change_plan_artifact.py`; `mcp_wire.py`, `mcp_context_projection.py`, `mcp_response_budget.py`; `tests/test_change_plan_projection.py`, `tests/test_mcp_budget_wire_accounting.py`, `tests/test_mcp_delta_context_regression.py` | Partial: delta fingerprints review/verification evidence independently of content and dependency digests; opaque continuation revisions bind both snapshots and retain the old baseline until the final page. Explicit MCP budget metadata is restored after final projection and measured against the full text plus `structuredContent` envelope; the finalizer tries smaller inner budgets when one-object sizing misses the wire cap. The targeted projection, pagination, delta, budget and wire suites pass (90 tests). Full invalidation across every MCP consumer and real-client page recovery remain open. |
| §11 Review and verification | `change_tree_verification.py` binds receipts to exact tree, command and observed environment digests; the manifest template requires an explicit environment capsule SHA-256. `tests/test_change_commit_execution.py` exercises sequence verification. | Partial: receipt reuse and exact-tree gates exist; Agent OS receipt interoperability, broader invalidation, expiry and concurrency acceptance remain open. A receipt is not task completion or proof of full test coverage. |
| §12 Planning, staging and commits | `change_stage_execution.py`, `change_commit_execution.py`, `change_commit_journal.py`; `tests/test_change_commit_execution.py` (16 passed on PR head `503a831`). Publication requires preview digest, exact intermediate trees, current per-tree receipts, journal, lease and branch compare-and-swap. Runtime source has no `--allow-unverified` option. | Partial: targeted publication audit and tests pass; linked/split worktrees, broader crash recovery, cross-process writers, hooks/signing, sparse indexes, submodules and full interruption matrix remain to verify. Unsupported states must keep failing closed. |
| §13 Agent OS integration | `change_task_context.py` links scoped checkpoint paths to task candidates and current Verification Store receipts without granting commit authority. GCI lifecycle guidance now appears in both managed Codex/Antigravity instructions and all seven shipped `local-ai-orchestrator` skill copies (Codex, Antigravity, Gemini, Claude, OpenCode guidance, Cursor, Copilot, Devin). | Partial: automatic lifecycle hooks, handoff/resume freshness and task coverage reuse still need end-to-end Agent OS proof. |
| §14 MCP, HTTP and CLI | Shared projections; `changed_paths` is sole split_changes path-selection field across HTTP, MCP transport and CLI. HTTP rejects retired `paths` and `changed_files` fields with terminal contract error; route tests cover rejection and canonical dispatch. MCP projection test checks canonical payload. | Partial: parity and recovery across every Git route, exact response/error contracts and machine-readable CLI failures still need full contract coverage. |
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

Current dependency-graph validation on source revision `3226c14c`: `python -m pytest tests/test_git_change_intelligence.py tests/test_change_commit_preflight.py tests/test_change_plan_projection.py -q` — **51 passed**. `python -m compileall -q src/local_ai_hub/change_dependencies.py tests/test_git_change_intelligence.py` and `git diff --check` passed. One earlier combined attempt saw a transient `untracked_unavailable`; its isolated rerun and this final combined run passed.

Current working-tree validation based on PR head `e8da4b25`: the same three suites — **53 passed** after adding explicit dependency-coverage scope checks. `compileall` for `change_dependencies.py`, `split_changes.py` and `test_git_change_intelligence.py`, plus `git diff --check`, passed. This verifies the focused dependency projection only; it does not close the open acceptance items above.

Current working-tree validation based on PR head `2f721116` plus the §10/§14 changes in this checkout: nine targeted projection, pagination, MCP budget/wire, delta regression and canonical HTTP route suites — **95 passed**. `compileall` for all edited Python modules and `tools/hubctl.py`, plus `git diff --check`, passed. This is focused contract evidence; it does not close the broader acceptance gaps above.

Initial consumer-candidate validation based on PR head `9b33216e`: the three focused suites passed **51 tests**. Current combined validation adds the audit contract suite and is recorded below.

Current audit goldset contract v3 validation: `python -m pytest tests/test_audit_quality_eval_contract.py -q` — **4 passed**. `python tools/audit_quality_eval.py --root <worktree>` measured all 7 retrieval and 3 architecture targets at exact symbol recall 1.0 and citation precision 1.0. The scope remains a bounded named-source retrieval check; it does not verify generated model answers or provider quality.

One intermediate combined run returned **50 passed, 1 failed** because `test_untracked_identity_and_structural_summary` reported `untracked_unavailable`; the isolated rerun passed. The final combined run below passed, and the observer continues to fail closed without a runtime fallback.

Final current working-tree validation based on PR head `9b33216e`: `python -m pytest tests/test_change_task_context.py tests/test_git_change_intelligence.py tests/test_change_plan_projection.py tests/test_audit_quality_eval_contract.py -q` — **55 passed**. `compileall` on the five changed Python files and `git diff --check` passed.

These results do not replace full CI, current critical branch coverage, paired provider evaluation, performance measurements, or Linux/macOS acceptance.

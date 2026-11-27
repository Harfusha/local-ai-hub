# Git Change Intelligence and Commit Orchestration

## Initial implementation

Use existing `local_ai_repo(action="split_changes", root="/absolute/worktree")` before proposing a commit. The existing HTTP route is unchanged. The deterministic proposal uses a NUL-delimited Git inventory, staged/unstaged line counts, and component-name matching for tracked implementation/test/documentation files. Unknown, ambiguous and untracked changes are conservative candidates, not authorization. No Git mutation occurs. Legacy explicit-path classification outside a Git repository remains available, labeled as caller-supplied and unverified. The result is **not** a content fingerprint, dependency proof, semantic review, ownership claim or valid verification receipt. Use `synthesize_commit` for existing task/receipt-based synthesis, subject to independent freshness checks. Do not infer readiness from the proposal.

## Incremental patch observation

Tracked textual changes now expose separate staged/unstaged content-addressed patch IDs, hunk ranges, group keys and an observed change-set ID. A second read detects same-line-count edits during inspection. A bounded in-process LRU reuses only derived hunk metadata (no raw source, no verification). Conflicted, unsupported, oversized or budget-limited scopes are explicitly unavailable. Small untracked regular files and symlinks now have bounded read-only identities, and tracked binary patches are hashed without exposing their bytes. The observed change-set ID is **not** a full snapshot, and must not authorize staging, commit or receipt reuse. Scope and full-tree/dependency/environment validation remain required. Git commands now use the existing bounded subprocess runner; truncated inventories fail closed and truncated individual patches are marked unavailable. HEAD and the staged-entry digest are compared before/after observation. The change-set ID also binds status records, HEAD and index metadata. This remains an optimistic observation of Git-visible changes, not a complete filesystem snapshot or lease. A task-linked ledger remains follow-up work.

## Persistent derived change summaries

The deterministic engine uses its existing SQLite cache infrastructure and a versioned `git-change:hunk-summary-v2` namespace, with a seven-day TTL and 4096-entry target. It retains only numeric ranges, counts and digests; no raw source or verification receipts. Cached metadata is reused only after hashing the current patch; malformed cache entries are recomputed. The process cache remains an L1. Hunk IDs include root/path/scope and exact hunk header/body digest, so unrelated hunks can retain their identity if their offsets remain unchanged. Offset changes conservatively invalidate identity. This does not establish semantic equivalence, full snapshot identity or independent commit readiness.

The grouping summary now includes tracked line totals by stage; totals may count intermediate edits in both scopes. Persistent cache hits are reported separately. This is a disposable derived cache, **not** yet an authoritative task-linked Change Ledger or receipt store.

## Structural Python summaries

For up to eight observed Python patch scopes per request, the existing bounded AST engine compares exact Git blob pairs when both objects are available (or a side is the all-zero addition/deletion ID). Missing unstaged objects are reconstructed in memory from the exact patch and verified by Git blob hash. It exposes structural change counts and bounded symbol names, cached by the scoped patch identity. No source is retained. Unreconstructable blobs, syntax errors, unsupported languages and budget limits are explicit; structural equality does not prove behavior equivalence. This is not yet general semantic grouping or local-model intent inference.

## Compact commit planning and local model suggestions

`split_changes` defaults to a compact group page at the MCP boundary. Set `mode="details"` for bounded patch metadata, `mode="semantic"` for optional local-model advisory messages, or supply a single `path` to focus details. Page with `limit` (1–8) and `offset`; each call observes the current worktree, so do not combine pages across edits as a single exact snapshot. Omitted paths/scopes/hunks are explicitly counted. The existing HTTP route retains its legacy full mode when no projection arguments are provided.

`python tools/hubctl.py changes [summary|details|semantic] --root /absolute/repo` exposes the same read-only service; `--changed-path` can narrow it. Model output must be valid bounded JSON with exactly the supplied IDs and single-line conventional messages; deterministic facts are unchanged. Model text is advisory, not verified intent or commit authority. Managed project planner instructions now prefer the compact plan before commit.

## Committed branch, PR and release comparison

Supply `base` and `head` to `split_changes` (or `hubctl changes --root ... --base ... --head ...`) for a read-only comparison of exact committed trees. Refs are resolved to full commit IDs and all subsequent operations use those IDs. The dirty index/worktree is ignored. For a PR use its merge-base commit as the explicit base; for a release use the previous tag. This is not an implicit three-dot diff. Committed line counts and patch scopes are labeled separately. The same compact summaries and optional advisory messages apply; no publication or mutation occurs.

## Untracked and binary observations

Small regular untracked files (up to 512 KiB) and link metadata are observed and rechecked without following symlinks. Their scoped identities include content digest and mode. Python source is structurally summarized from an empty before-state when within the AST budget. Binary patches are captured with Git's binary format and hashed, but not semantically interpreted. Large, unreadable, conflicted, submodule and budget-limited scopes remain explicit gaps. No untracked file is staged; provenance and commit readiness remain unknown. The completeness flag means only Git-visible observations (not ignored/assume-unchanged paths or an atomic filesystem snapshot).

## Scoped Agent OS context

Compact worktree plans can link bounded, repository-scoped tasks through exact checkpoint path overlaps. An explicit `task_id` narrows the task set. Existing Agent OS completion evaluates receipts against a freshly observed Hub repository revision; only satisfied criteria with matching receipt revisions are candidates. The plan explicitly distinguishes whole-worktree task completion from commit verification, and never authorizes skipping per-commit checks. The older synthesis service now requires scoped tasks and no longer inserts unchecked or stale receipt claims into commit messages. Cross-project and unscoped tasks are excluded.

## Polyglot fact deltas, hunk associations and dependency candidates

The existing deterministic source-fact extractor is reused for supported PHP/CakePHP, JS/TS and other known file formats. Exact source pairs produce bounded added/removed/changed declaration/fact identities; only selected identifier kinds and value hashes are compared. This is lexical fact analysis, not full semantic equivalence or proof that function bodies are unchanged. Python AST results additionally include source ranges and import candidates. The planner associates hunks with overlapping changed symbols and proposes group ordering from uniquely matched changed Python module paths, relative JS imports and PHP declaration/import names. Cycles and their blocked dependents remain explicit. The graph is incomplete by design, is not a proof of dependency closure, and cannot authorize separate commits. The compact view reports omitted candidates.

## Local semantic regrouping

Semantic mode additionally accepts a local model proposal for a complete non-overlapping partition of the visible deterministic groups, with a bounded summary and conventional message for each proposed commit. Unknown, omitted, duplicate or malformed group IDs invalidate the response; deterministic groups remain available. The suggestions are page-scoped, never global dependency proof or commit authority. No model is allowed to hide or replace an observed group.

## Snapshot-bound preflight and publication drafts

Use the full-inventory `observed_change_set_id` as `expected_revision` for subsequent pages or `mode="preflight"` with explicit `changed_paths`. Preflight always re-observes the entire Git-visible inventory before comparing the expected ID. It blocks incomplete observations, foreign staged files, conflicts, mixed staging, untracked selections, partial groups and unselected candidate dependencies. It returns a literal-path Git argv preview only, never performs staging or commits. A matching index scope is not a validation receipt or proof of ownership. Modes `pr` and `release` produce paged factual draft descriptions for exact committed ranges. CLI exposes the same modes and expected revision. No publication occurs.

## Target architecture and remaining delivery

Extend the existing repository analysis, Agent OS, artifact, context ledger, verification and Git-first services; do not create a second task or evidence store.

1. **Snapshot and ledger:** bind repository/worktree identity, HEAD, index and worktree content fingerprints (including untracked bytes, modes, renames, submodules and conflicts). Capture before/after and refuse unstable reads. Use bounded streaming, versioned content-addressed caches and watcher-driven invalidation with reverse dependencies. Persist only safe derived metadata locally; share durable decisions and project conventions via existing Git-first policy. Never persist credentials or raw sensitive diffs. Track staged and unstaged atoms separately, including overlapping hunks. Distinguish observed provenance from inferred/unknown ownership.
2. **Semantic summaries:** reuse AST diff, call graph, business graph, test mappings, task contracts and prior evidence. Generate structured atom/symbol/file/module/group/branch/PR/release summaries using deterministic facts and configured local model only. Validate cited IDs, schema and coverage; fall back to factual metadata on failure. Invalidate only affected claims, not the whole repository. Expose bounded artifact-backed detail and delta views.
3. **Logical grouping:** graph of change atoms with hard dependencies and soft similarity edges; join implementation, tests, docs, migrations and lockfiles where evidence supports it. Resolve cycles as one unit, order by dependency DAG, and retain ambiguous/unowned atoms separately. Never silently omit changes or use a model as authority for ownership or dependencies. Validate every proposed intermediate tree, not only final worktree. Support user editing, merging, splitting and explicit exclusions.
4. **Verification reuse:** distinguish seen, summarized, reviewed, tested and approved. Reuse only receipts valid for exact content/dependency/environment/command scope and required acceptance criteria. A full dirty-tree test does not automatically validate a partial commit. Surface stale/unknown/failed/skipped checks; rerun only invalidated required checks when feasible. Local model cannot mint receipts. Preserve evidence provenance and artifact IDs.
5. **Canonical transport:** evolve existing `split_changes` and `synthesize_commit` into summary, group/detail, commit-plan and branch/PR projections under existing MCP tools; do not expand the seven-tool catalog. Support explicit snapshot/scope, stable group IDs, pagination, wire budgets and reuse keys. Provide consistent HTTP, CLI and desktop Changes & Commits views, using the same service. Update generated policies for all clients to call the compact plan first, inspect unresolved changes and only request exact raw slices when needed. Preserve API compatibility.
6. **Execution:** explicit approval tied to snapshot and plan, root authorization, write leases, index lock and compare-and-swap checks. Never use blanket git add, automatic commit/push or destructive reset/stash. Preserve existing staged changes and user-owned changes, validate exact selected patches in isolated temporary indexes/worktrees and respect hooks/signing. Verify each intermediate tree and report partial progress honestly after failures; never silently rewrite history. Persist commit SHA and task/evidence linkage. No execution until these gates exist.
7. **Quality and rollout:** test clean/dirty, unborn HEAD, conflicts, rename/copy/delete, binary, submodules, special filenames, partial staging, overlapping hunks, external mutations, concurrent worktrees, interrupted execution, cache invalidation, receipt staleness, redaction, budget limits, authorization and model failure. Measure net cloud-token delta using paired real workflows including schema, calls, responses and detail follow-ups; do not report theoretical savings as measured. Desktop integration and full end-to-end acceptance are required before declaring the feature complete.

## Acceptance

All changes are accounted for or explicitly identified as unavailable. No unproven atomicity, correctness or review claims. No silent loss of index/worktree changes. A second unchanged request reuses content-bound summaries/receipts; a changed atom invalidates only affected evidence. Each proposed commit is independently validated or blocked. The cloud agent receives a bounded plan and only escalates unresolved/risky evidence. The initial implementation does not yet satisfy the full target acceptance.

## Native desktop integration

The web dashboard cutover is incorporated from the native desktop branch. Changes & commits uses a named, scoped bridge operation and the same read-only HTTP plan, with bounded paging and expected observed revision. It does not run arbitrary Git commands or authorize mutations.

## Artifact-backed detail

Use `split_changes(mode="artifact")` to explicitly publish the current full metadata-only observation to the existing artifact store, then read it through `local_ai_artifact(action="slice", artifact_id=..., offset=..., max_chars=...)`. The snapshot is historical and not a lease; never treat artifact retrieval as a new observation. Oversized payloads are rejected rather than silently clipped. This opt-in path stores repository metadata (including file names, symbol names; task candidate metadata is excluded), not raw patches. It does not retain verification authority.

## Prospective staged tree identity

A stage-zero index tree object ID is computed in memory from the bounded Git index listing, with Git tree ordering and repository hash format. No objects or index entries are written. Unmerged or unsupported index entries yield no tree ID. Preflight exposes it only when the entire staged selection matches and no staging blockers exist. This identifies the observed index tree; it is not proof of object availability, independent intermediate-tree validation, a receipt or commit authorization.

## Explicit local staged commit

`hubctl changes commit-staged --root ... --changed-path ... --expected-revision ... --expected-tree ... --commit-message ... --apply` is an opt-in local-only transaction for an already staged, reviewed index. It claims the shared root lease, locks the real index, repeats preflight, materializes the approved tree using a temporary index, creates the candidate commit and publishes by branch compare-and-swap. It refuses mixed or foreign staged changes, detached HEAD, linked worktrees, active repository operations, configured signing and installed/custom hooks (use normal Git in those cases). It never stages, rewrites the real index, pushes or claims verification. A failed or uncertain branch update returns the candidate ID when available; inspect before retrying. A crash can leave a Git index lock or unreachable candidate object; inspect process and branch state before manual recovery. This is not automatic multi-commit execution.

The staged executor also independently compares the exact materialized Git tree against its parent and refuses any file-set mismatch with the approved selection. The focused regression suite is registered in CI. Linux desktop smoke now includes the Xvfb authentication dependency and emits X server diagnostics on failure.

## Delta summaries

A complete worktree summary stores a bounded, root-scoped derived map of group IDs and atom digests in the existing cache. When `baseline_stored=true`, call `split_changes(mode="delta", expected_revision=<previous observed change-set ID>)` after edits. Only changed groups are projected, with counts of unchanged-content and removed groups. Expired, incomplete, scoped or malformed baselines fail closed. A delta does not reuse review or verification status; even identical group content can have different dependencies and task context. CLI supports `changes delta --expected-revision ...`. No measured cloud savings are claimed.

## Commit recovery journal

Local CLI commit execution persists an intent in the local state directory before branch CAS and marks it published after success. The journal stores only root, branch and object identities, not commit messages or source. Use `hubctl changes commit-inspect --root ... --operation-id ...` to inspect the observed branch tip and index lock after uncertainty. It does not automatically replay, unlock or roll back. A failed journal prepare prevents publication; failed post-publication bookkeeping is distinguished from commit failure. The direct internal API can still be used without the optional journal; the local CLI always supplies it.

## Two-phase local staging

Use `hubctl changes stage-preview --root ... --expected-revision ... --changed-path ...` to calculate the exact prospective tree via an isolated index and object directory. Use the same arguments plus `stage-apply --expected-tree <preview tree> --apply` to publish the staged index. It claims the shared lease, locks the index, verifies the full observed revision before and after constructing the prospective tree, independently checks the selected tree diff, and publishes via an atomic index replacement. It accepts complete tracked paths and bounded observed regular untracked files (explicitly selected); mixed staged/unstaged paths, unrelated staged changes, dependency blockers, filters, installed hooks, sparse/split index and linked worktrees are refused. Preview creates temporary files/locks but no real Git objects or index changes. Apply may create unreachable objects on failure; it does not commit or push. Re-observe the new index and perform required validation before commit. Hunk-level staging is not implemented.

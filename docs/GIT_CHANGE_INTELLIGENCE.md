# Git Change Intelligence and Commit Orchestration

## Current operational contract

The historical delivery notes below describe successive versions. The current implementation supports canonical batched patch identities (up to 256 scopes within the time/byte budget), paginated plans and deltas, exact staged-tree and hunk operations, ordered sequences, scoped local review declarations, fenced broker postimage observations, and receipt-gated verification/publication. Native desktop replaces the web dashboard; configured policy checks can run locally after explicit confirmation. Unconfigured commands remain CLI-only. No authority is inferred from a summary, index candidate or declaration. The bounded review model is not a compiler-complete dependency graph, authenticated native-editor attribution, or proof of cloud token savings. Current CI and external paired provider experiments are separate acceptance gates.

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

The existing deterministic source-fact extractor is reused for supported PHP/CakePHP, JS/TS and other known file formats. Exact source pairs produce bounded added/removed/changed declaration/fact identities; only selected identifier kinds and value hashes are compared. This is lexical fact analysis, not full semantic equivalence or proof that function bodies are unchanged. Python AST results additionally include source ranges and import candidates. The planner associates hunks with overlapping changed symbols and proposes group ordering from uniquely matched changed Python module paths, relative JS imports and PHP declaration/import names. Cycles are reported explicitly and condensed into indivisible candidate commit units; downstream units are ordered after their prerequisites. The legacy linear order continues to report cycles and blocked dependents. The graph is incomplete by design, is not a proof of dependency closure, and cannot authorize separate commits. The compact view reports omitted candidates.

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

A complete worktree summary stores a bounded, root-scoped derived map of group IDs and atom digests in the existing cache. When `baseline_stored=true`, call `split_changes(mode="delta", expected_revision=<previous observed change-set ID>)` after edits. Changed groups and transitive consumers whose observed dependency context changes are projected, with separate counts for content changes, dependency-context-only changes, unchanged content and removed groups. Baselines from the older schema require a fresh full summary. Expired, incomplete, scoped or malformed baselines fail closed. A delta does not reuse review or verification status; even identical group content can have different task context or unobserved dependencies. CLI supports `changes delta --expected-revision ...`. No measured cloud savings are claimed.

## Commit recovery journal

Local CLI commit execution persists an intent in the local state directory before branch CAS and marks it published after success. The journal stores only root, branch and object identities, not commit messages or source. Use `hubctl changes commit-inspect --root ... --operation-id ...` to inspect the observed branch tip and index lock after uncertainty. It does not automatically replay, unlock or roll back. A failed journal prepare prevents publication; failed post-publication bookkeeping is distinguished from commit failure. The direct internal API can still be used without the optional journal; the local CLI always supplies it.

## Two-phase local staging

Use `hubctl changes stage-preview --root ... --expected-revision ... --changed-path ...` to calculate the exact prospective tree via an isolated index and object directory. Use the same arguments plus `stage-apply --expected-tree <preview tree> --apply` to publish the staged index. It claims the shared lease, locks the index, verifies the full observed revision before and after constructing the prospective tree, independently checks the selected tree diff, and publishes via an atomic index replacement. It accepts complete tracked paths and bounded observed regular untracked files (explicitly selected); mixed staged/unstaged paths, unrelated staged changes, dependency blockers, filters, installed hooks, sparse/split index and linked worktrees are refused. Preview creates temporary files/locks but no real Git objects or index changes. Apply may create unreachable objects on failure; it does not commit or push. Re-observe the new index and perform required validation before commit. Hunk-level staging is described in the following section.

## Partial hunk staging

For one tracked regular text file, supply one or more exact observed unstaged `--hunk-id` values to stage-preview and stage-apply. The full patch is reconstructed and checked against its Git blob hash, then only the selected hunks are materialized from the original index blob. The prospective tree is independently compared with the selected path; apply requires the exact preview tree. Unsupported mode changes, binary changes, truncated hunks and unknown IDs fail closed. After re-observation, `commit-staged --allow-mixed-staged` explicitly permits a reviewed staged tree while preserving remaining unstaged hunks. Default preflight continues to block mixed scopes; the approved local executor checks the exact tree and path set independently. This does not establish that selected hunks are semantically independent.

## Explicit staged commit sequence

A JSON array of steps (`{"paths":["file"],"message":"chore: ..."}`) can be passed via `--record-file` to `changes sequence-preview` with the same exact index revision, final tree and complete staged path selection. It computes bounded intermediate tree IDs without writing Git objects, checks that every staged path appears exactly once, logical groups are not split, and known dependency candidates precede consumers. `sequence-apply --apply --preview-digest ...` revalidates the preview, materializes each tree and independently checks each step's exact path diff. All candidate commits are published together by one final branch CAS and journal intent. No intermediate branch updates, index rewrites, push or independent test execution occur. The sequence is not verified and must be reviewed and tested independently. Same-file hunk splitting across a single sequence is not supported; use separate partial stage and commit transactions.

## Independent exact-tree checks

`sequence-verify` takes the same reviewed sequence arguments plus `--verification-file` containing an explicit environment capsule hash and 1–4 argv arrays with absolute executables, e.g. `{"environment_id":"<64 hex>","commands":[["/absolute/python","-m","pytest","-q"]]}`. Each command runs in a fresh bounded directory populated from exact Git blobs, with a fresh home/temp directory and minimal inherited environment. Non-regular files, submodules, excessive trees and unsupported paths require external verification. This is not a security sandbox; run only trusted code and commands. Successful checks are persisted in the commit journal keyed by root, tree, command and observed environment digest, with a one-hour TTL. Sequence apply requires matching receipts for every tree unless the local operator explicitly specifies `--allow-unverified`; exact source and command identity do not prove complete tests or immutable external dependencies. Agent OS whole-worktree receipts are not promoted to exact-tree receipts.

Use `changes commit-list --root ...` to recover recent operation IDs when a process exits before returning its result. A new exact-tree verification attempt invalidates any earlier success for the same tree/command/environment and fences concurrent stale completions. Materialization refuses platform-reserved names and case/Unicode-colliding path prefixes.

The Rust desktop now exposes named local staging and staged commit operations and recovery inspection through its one-shot allowlisted bridge. Explicit confirmation is required for mutation; the existing transaction implementations enforce exact identities. The desktop additionally exposes reviewed sequence preview and receipt-gated publication, and local atom annotation. Run sequence checks through the trusted local CLI, then supply the exact same verification manifest and preview digest to the desktop. The one-shot desktop bridge does not execute supplied commands or offer an unverified sequence bypass.

## Local observation and review ledger

Complete worktree summary/delta observations retain bounded atom identities and first/last-seen timestamps in local state. `changes annotate --root ... --expected-revision ... --record-file ... --apply` records an explicit local declaration for currently observed atom IDs, with JSON fields `atom_ids`, `actor`, `task_id` and `status` (assigned/reviewed/needs_review/withdrawn). A changed observation makes old declarations stale even if atom content is unchanged. Summary and details distinguish current, stale and multiple-actor associations. Actor/task names are declarations, not authenticated ownership, review receipts or authorization to skip verification. They are excluded from exported artifacts and local model inputs. Local machine-specific history remains outside Git; shared project policy belongs in tracked project configuration. Recent watcher events are correlated separately below; no automatic authorship is asserted.

## Context transport benchmark

`python tools/benchmark_git_change_context.py --files 12 --lines 120` creates a disposable synthetic Git fixture and reports estimated request+response tokens for two raw diff reads versus full summary, incremental delta and one targeted raw follow-up. It uses Hub's existing byte-based estimator, reports the signed net difference (including negative results), and never sends data to an external model. This is a transport-size benchmark, not evidence of equivalent review coverage or billed cloud-token savings. CI runs a small fixture and retains its JSON output in the job log.

Local stage and commit transactions now derive the same project coordination namespace as Agent OS before claiming the root lease; changed or unavailable project identity prevents publication. The focused suite includes an actual Git/index/lease integration test for partial staging and unrelated worktree changes.


## Isolated staging and CI dependency separation

Selected tracked regular files are explicitly reread in the temporary index before normal staging, including same-size edits whose timestamps did not advance. Publication still requires the exact approved prospective tree and repeated full observation. This does not make Git-visible observations a filesystem-wide snapshot. CI exercises PyTorch and Pillow tests in a dedicated CPU environment; the ordinary dependency matrix reports skips for missing optional libraries instead of failing during collection.


## Recent watcher evidence

The existing preprocessing observer records at most 2048 recent root/path event observations in memory (one latest event per path, one-hour display horizon). Explicit watcher events are distinguished from manual invalidation calls. Git summaries expose a candidate path count, and details include the recent matching event and timestamp. No new watcher thread or per-event persistent write is introduced. Events are best-effort, may be missed or reordered, and do not prove which actor wrote a patch, that the event caused the observed content, or that all changed files were watched. Git content re-observation remains authoritative for transaction preflight. The metadata is not included in the opt-in artifact or local-model prompt. Authenticated attribution and shared review policy integration remain open.


## Shared commit verification policy

Projects may opt into the existing project configuration system with a version-controlled `.local-ai.toml`:

```toml
[commands.unit]
argv = ["python", "-m", "pytest", "-q"]

[verification_rules]
git_commit = ["unit"]
```

Use one to four structured argv aliases. Shell strings and injected environment references are unsupported for this policy. Resolve executable names through absolute PATH entries and provide the matching absolute argv arrays in the explicit local verification manifest. The environment capsule digest is still supplied by the operator. The policy applies to each intermediate tree; a direct commit or unverified sequence is refused. A single-step sequence is supported. Preview identity includes the effective project configuration digest when the rule is active, and publication rechecks policy and receipts before updating the branch. No arbitrary commands are automatically executed from the repository configuration.

This is a cooperative project policy, not a branch protection rule or a sandbox. The current local configuration and permitted overlays can be changed by an operator with filesystem access. Use protected branches and independent CI for enforcement against untrusted contributors. Authorship of native worktree edits cannot be inferred from task checkpoints, leases or watcher events.


## Fenced Command Broker postimage receipts

After a private transaction successfully imports and verifies output under an active server-validated work-attempt fence, the broker records the latest bounded file digest and mode with its task, attempt and transaction identifiers. The local ledger retains up to 2048 records for seven days, records no source text, and supersedes evidence on a later broker import (including deletion). Change summaries count current matches; detail mode reports the corresponding task/attempt/transaction when a fresh bounded read matches. At most eight candidate files are reread per request. Native edits with different content no longer match, and records are physically root scoped. A matching postimage does not prove that the whole Git patch was written by that task: pre-existing edits, later identical bytes, uncovered files and staging state remain possible. Receipt recording is best effort and never triggers a retry of an already committed mutation.

## Benchmarking actual Git history

`python tools/benchmark_git_change_context.py --repo /absolute/repository --base HEAD~1 --head HEAD`

The historical benchmark reads a real committed range without changing HEAD, index or worktree. It compares the raw patch and all paginated summaries using the same transport estimator, independently verifies the changed-path inventory against Git, reports explicitly listed and omitted paths and patch/semantic coverage, and rejects oversized Git output. This measures transport estimates for a real workload; it is not provider billing or an LLM quality comparison. Actual provider-token/quality experiments still require a chosen cloud model, approved data and a paired independent evaluation protocol.


## Editable staged sequence proposals

`hubctl changes sequence-suggest --root /absolute/repository` observes the complete Git-visible inventory and derives an editable sequence from staged logical dependency units. It refuses partial groups, unresolved prerequisite selections, mixed staging and oversized sequences. The output includes the exact observed revision, index tree, staged path list and a `sequence` array suitable for the existing record file. Edit the messages and grouping, then obtain a separate exact sequence preview. Suggestions do not authorize publication or prove verification. The native desktop can request the same suggestion and explicitly load it into its existing sequence editor without automatically approving a commit.

Observed Python/relative JavaScript import removals can order a consumer before deletion of its provider when both bounded preimage and postimage import sets are available. Remaining references to removed providers are flagged as risks. These are candidate edges, not a complete semantic graph. Mixed-stage observations, unresolved import resolution and unchanged external consumers still require inspection.

## Paired provider usage and review quality evaluation

Run `python tools/benchmark_git_change_evaluation.py paired-results.json` after executing paired raw-diff and compact-context review tasks on the same exact commit, task and provider/model. Use an approved corpus, independently adjudicated finding IDs and provider-reported usage totals including schemas, all calls, retries and detail follow-ups. The input schema is:

```json
{
  "schema": 1,
  "cases": [
    {
      "case_id": "review-1",
      "task_digest": "<64 lowercase hex characters>",
      "revision": "<40 or 64 lowercase hex characters>",
      "provider_model": "provider/model",
      "expected_finding_ids": ["finding-1"],
      "raw": {
        "input_tokens": 1000,
        "output_tokens": 100,
        "cached_input_tokens": 0,
        "calls": 2,
        "finding_ids": ["finding-1"],
        "completed": true,
        "usage_source": "provider_reported"
      },
      "compact": {
        "input_tokens": 500,
        "output_tokens": 100,
        "cached_input_tokens": 0,
        "calls": 2,
        "finding_ids": ["finding-1"],
        "completed": true,
        "usage_source": "provider_reported"
      }
    }
  ]
}
```

The example counts are illustrative, not measured. Use a consistent provider definition of total input tokens including cached input. The evaluator reports input/output and uncached-input differences, completion, precision, recall and per-case additional missed findings. It rejects estimated usage and inconsistent counters and does not treat lower token counts as evidence of equal quality. Actual experiments remain to be run; no provider API calls are made by this evaluator.


## Receipt reuse and review hints

`changes sequence-verify` now checks for a current exact-tree receipt before materializing and executing commands. A valid receipt is reused only for the same root, intermediate Git tree, command identity and observed environment digest, with the same effective project policy and unexpired local journal evidence. The result identifies reused and newly executed steps separately. Use `--rerun-checks` to force fresh checks; starting a newer attempt revokes the old success. All required receipts are checked again at the end of verification and immediately before publication. The operator-supplied environment capsule must reflect external dependency changes; this mechanism does not establish external dependency immutability.

Worktree details also query the existing indexed impact service for the displayed groups' paths (maximum 64 changed paths). The bounded result lists candidate consumer files and tests, with omitted counts and explicit freshness `not_checked`. These hints are not a complete dependency graph, are not used as commit prerequisites or proof of review, and never authorize verification reuse. Inspect exact source for unresolved or risky candidates. The desktop confirmation dialog displays the exact submitted Git paths, hunks, messages, sequence and local annotation record before mutation.

### Dependency candidate coverage

Changed PHP declarations are compared on both source sides; removal of a consumer import can precede deletion of its uniquely matched provider, and retained imports to deleted providers or removed declarations are flagged. Node-style TypeScript imports with emitted JS extensions also consider matching TypeScript source paths; ambiguous matches remain unresolved. Dependency summaries explicitly count observed, unmatched and ambiguous imports, unavailable semantic scopes and truncated import/declaration scopes. These are changed-file candidate relationships, not a complete compiler-resolved graph or a proof of dependency closure.

Delta pages use a single `offset`/`limit` cursor for changed groups and removed group keys. Continue while `has_more` is true even when a page has no changed groups. This avoids losing deleted-group identities when more groups disappear than fit on one page.

### Receipt inspection and configured desktop verification

Use `hubctl changes sequence-status` with the same reviewed sequence file, root, paths, expected revision/tree, preview digest and verification manifest. The operation inspects exact-tree receipts without executing checks and reports current versus missing/expired steps. The desktop offers the equivalent inspection and an explicitly confirmed **Run configured project checks** action. Desktop execution accepts only the exact manifest matching the configured `git_commit` project policy; unconfigured or mismatched arbitrary commands are refused. It re-observes the reviewed preview before running checks, never publishes automatically, and cannot bypass receipt gates. Checks run locally as the invoking user, not in a sandbox; review executable paths and arguments before confirmation. Other operator-defined checks remain CLI-only. Publication always rechecks receipts.

Receipt inspection distinguishes current, expired, missing, failed and in-progress-or-interrupted attempts. Failed outcomes persist only bounded reason codes, not command output, and are scoped to the latest attempt. They are diagnostics, never authorizing receipts. Interrupted processes cannot be assumed to still be running.

The final verified publication holds a local SQLite writer-exclusion guard over the receipt recheck and Git branch compare-and-swap, so a concurrent Hub verification attempt cannot revoke a receipt between those operations. This does not lock external Git processes or arbitrary local filesystem changes; the existing Git index lock and branch CAS remain independently required.

Indexed impact details now request a bounded content-hash freshness check of changed files and returned consumer/test candidates, and reject a current-candidate claim if the index generation changed or the verification path budget omitted paths. Stale and unknown candidate paths are separately visible. Cached impact graph results do not cache the filesystem freshness observation; this remains partial indexed evidence, never compiler-complete closure or verification authority.

### Local policy manifest template

`hubctl changes verification-policy --root /absolute/repo` and the desktop **Resolve configured verification policy** action resolve the configured executable argv without running any commands. The returned manifest intentionally has an empty environment capsule ID: the operator must fill in a real environment identity and review the exact arguments before verification. This is a local-only projection; it is not exposed through the public MCP/HTTP plan. Do not put secrets in configured argv. Required-policy preview digests bind both the config digest and the resolved command list digest, so changes in PATH resolution invalidate a prior preview.

### Bounded batched patch observation

The Git observer reads up to eight exact literal paths per patch invocation, verifies the canonical C-quoted header partition, and falls back to individual reads for unexpected or oversized batches. A separate second batch read rechecks each exact patch identity. The raw batch is request-local and never stored in the derived cache. Production capture supports up to 256 scopes with the existing per-patch and wall-clock limits; unfinished scopes remain explicitly unavailable and still block exact transactions. Individual selected transactions remain bounded to 64 paths. The same canonical diff flags are used for partial-hunk staging. Tests compare batch members byte-for-byte with independent Git invocations, including binary, deletion and unusual filename cases.

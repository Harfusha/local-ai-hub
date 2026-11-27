# Verified execution

Verified execution is an opt-in extension of Agent OS, not a separate task
store or orchestration service. It supports audits, implementation, refactoring,
migrations, debugging and other tasks with explicit evidence-backed criteria.

Use the existing `local_ai_coord(action="task_create")` with a goal contract
containing `slo_profile.verified_execution`:

```json
{
  "goal": "Review a change and verify affected consumers",
  "acceptance_criteria": ["review API contract", "consumer integration test", "review documentation"],
  "slo_profile": {
    "verified_execution": {
      "version": 1,
      "profile": "change_review",
      "required_dimensions": ["contract", "integration", "documentation"],
      "units": {
        "review API contract": {"dimension": "contract", "priority": 80},
        "consumer integration test": {"dimension": "integration", "depends_on": ["review API contract"], "priority": 90},
        "review documentation": {"dimension": "documentation"}
      }
    }
  }
}
```

All acceptance criteria are mandatory obligations. Missing metadata means an
independent obligation in the general dimension. No status can be submitted
in unit metadata. Criteria are unique canonical strings (up to 512 units);
dependencies must reference exact criteria, be acyclic and nonduplicated.
Required dimensions must have at least one criterion. Profiles are labels,
not assurances that the agent has exhaustively planned the task.

Use existing checkpoints and verification receipts, then call
`local_ai_coord(action="verify_completion", root=..., task_id=...)`.
The completion result includes `execution` with exact coverage counts,
per-dimension counts, a bounded remaining preview and the highest-priority
unblocked next obligation. Status comes from the persisted receipt evaluator,
not agent-reported progress. Stale prerequisites prevent dependents from
counting toward coverage. A new prerequisite receipt also supersedes any older
receipt of a dependent obligation; reverify the affected chain in dependency
order. Independent valid receipts remain counted, subject to the existing
repository revision and mutation-generation gates. Project-configured verification obligations are
included when the evaluator applies project rules. Receipt IDs are informational.

Use authorized contract steering to add newly discovered obligations; criteria
without metadata are independent mandatory units. The graph cannot silently
refer to removed criteria. Existing task state, receipts and Git plan bindings
remain authoritative. Unresolved checkpoint blockers stop opted-in completion,
including through the receipt-waiver path. Preview is not authorization:
the lifecycle gate rechecks conditions before transition.

## Generic declared inventory compiler

For a finite collection of files, features, documents, experimental scenarios
or other resources, give the contract a resource/check matrix instead of
manually writing one criterion per combination. For example:

```json
{
  "goal": "Review both modules for correctness and consistency",
  "slo_profile": {
    "verified_execution": {
      "profile": "audit",
      "inventory": {
        "resources": ["module-a", "module-b"],
        "checks": [
          {"name": "review correctness", "dimension": "correctness", "priority": 80},
          {"name": "review consistency", "dimension": "consistency"}
        ]
      },
      "required_dimensions": ["correctness", "consistency"]
    }
  }
}
```

The server expands all four combinations into acceptance criteria and keeps
the original matrix in the persisted goal contract. Additional explicit
criteria are additive. An oversized matrix is rejected, never silently
truncated; partition large inventories into scoped tasks using existing
repository plans. The resource list is **declared**, not a server-attested
complete repository inventory. Use the existing authorized inventory tools to
obtain resources and record exclusions. A receipt validates its criterion
only; it cannot establish that omitted resources do not exist.

## Server-checked repository scope

For a bounded read-only repository review, set the inventory's
`scope` to `repository` and omit `resources` on HTTP/MCP task creation.
The server enumerates the authorized checkout with the existing confined
security inventory, fixed default ignore policy, a five-second deadline
and 8,000-file inventory bound (512 obligations per task). It refuses incomplete inventory, links, oversized
files, mismatched supplied resources, and an expanded matrix exceeding the
obligation limit. The same scope is rechecked at completion; newly added
or deleted resources block completion, even with a receipt waiver.
Use the declared scope for explicit subsets or a task that intentionally
changes inventory. A repository scope is bounded by the inventory's
default exclusions (ignored directories/extensions/archives); it does not
attest to excluded files. Auto-worktree and portable handoff creation are
not supported for this scope yet.

For larger projects add `"partition": {"index": 0, "size": 100}` to
the inventory and keep the same check matrix and size across tasks. The
server sorts the full inventory, slices it without overlaps, and persists
the manifest hash, resource count and partition count. Read the returned
contract to obtain the remaining partition indices. Each task's obligations
remain bounded (size × checks ≤ 512). All partitions recheck the entire
manifest; even a change outside a partition invalidates its scope. The
caller must create and verify every partition. Bind the tasks to a shared
repository plan, then call `local_ai_coord(action="plan_validate", root=...,
plan_id=..., include=["execution"])` for a read-only plan-wide preview.
It checks current task bindings, criteria, receipt gates, completed status,
pending deliveries and missing or duplicate partitions of each manifest/check
matrix. A changed snapshot, missing binding, ambiguous attempt, or scan limit
prevents an all-complete claim. The preview is bounded to 64 tasks and a
15-second scan budget; it does not mutate plan or task state.
Partition presence and verified completion are reported separately. The
`obligation_coverage` projection sums the observed canonical task coverage
and dimensions; `partial` is true if any task lacks coverage, the scan is
truncated, or the snapshot changed. Do not extrapolate partial coverage to
the entire plan. Counts describe task obligations, not unique source files.

Structured contract steering is additive: existing mandatory obligations
cannot disappear in an ordinary criteria revision. This is deliberately
more restrictive than unstructured task steering.

Each inventory check may also specify `depends_on` with the exact names of
other checks in the matrix. The compiler expands those prerequisites separately
for every resource, rejects cycles, and prevents explicit unit metadata from
removing them. For example, `verify` can depend on `inspect` and `repair`.

The verification preview includes advisory evidence age. An active incomplete
task without a recently validated receipt for 15 minutes is flagged
`no_recent_verified_evidence`. This does not prove inactivity (long tests or
research may take longer), does not block cancellation, and does not force an
external agent to keep running. The next actionable obligation is also flagged
`repeated_failed_verification` when at least three consecutive failed receipts
exist within the last 15 minutes in the same repository revision, mutation
generation and authorized owner lineage (bounded to the newest 128 receipts).
A passing receipt breaks the sequence. This is advisory and may miss older
attempts; the Stop hook permits exit rather than repeating the same failure.

An inventory check or explicit unit can declare `evidence_type` as
`source_review`, `test`, or `benchmark`. This is persisted in the contract
and used by the canonical receipt gate, avoiding accidental classification
from a resource path such as `tests/test_file.py`. Test and benchmark kinds
still require command evidence. Project-mandated command rules retain their
existing classification and proof requirements. Without an explicit kind,
legacy criterion-name inference remains in effect.

Reusable versioned examples are in `docs/examples/verified-execution-profiles.json`.

## Git change scope

Use inventory `"scope": "changes"` to enumerate staged, unstaged, deleted
and untracked paths in the authorized checkout. An optional `base_revision`
must be a full commit ID and adds committed changes since that base.
Rename detection is disabled so both deleted and added paths are included.
The server checks the scope again at verification and completion. Empty,
oversized, timed-out or unsupported inventories fail closed. This is a
path inventory, not semantic dependency analysis; add affected consumers
as explicit criteria. Ignored untracked paths and changes inside submodules
are not expanded; submodule entries are obligations at their own path.

### Explicit scope exclusions

Server-checked repository and changes inventories accept an optional
`"exclusions": [{"path": "generated/example.py", "reason": "Generated fixture; reviewed generator separately"}]`
in the inventory object. Every entry must be an exact current inventory path
with a nonempty rationale. Globs, directory prefixes, duplicate paths, absent
paths and exclusions that remove the entire inventory are rejected. Exclusions
are persisted in the goal contract; verification reports their count and a
bounded preview. The original inventory must still be available and complete
before exclusions are applied. If an excluded path disappears, the scope
recheck fails rather than silently treating the exception as obsolete.
Partition coverage never combines different exclusion lists or rationales.

These are explicit task-scope choices, not independent approval of the
rationale. Review them when agreeing the goal contract. Completion attests
only to included resources, not to excluded resources or default inventory
ignores. Existing tasks cannot remove obligations by ordinary criteria steering.

### Static Python import impact

For Git changes scope, set `"include_python_imports": true` to expand the
inventory using the standard-library Python AST. The server analyzes ordinary
absolute and relative imports in the repository root and conventional
`src/` layout, includes deleted modules as dependency targets and walks reverse
import edges transitively. Package initializers and ambiguous local module
names are treated conservatively. When combined with `include_mapped_tests`,
both import and project-declared rules are expanded to a fixed point.
The setting is persisted, rechecked at completion and included in partition
identity; it is never a client-supplied list of impacted files.

The scan uses the existing bounded repository inventory and rejects
unreadable, changed-during-read, oversized, lossy or syntactically invalid
Python sources. Additional limits: 512,000 bytes per source, 32 MB overall,
250,000 import edges and a five-second expansion deadline after inventory.
The scanner does not import or execute project code. Dynamic imports, custom
module roots, generated code, runtime dispatch, other languages and excluded
files are not modeled. This is a conservative static import approximation,
not an exhaustive semantic dependency analysis.

### Git-managed impact policy

For changes scope, set `include_mapped_tests: true`. Hub resolves the existing
`.local-ai.toml` / worktree project settings and expands matching
`affected_tests_mapping` target patterns against its confined repository
inventory. All matched allowed test paths become resources in the same check
matrix. A missing target or invalid config is an error, not a skipped check.
Matching rules are evaluated transitively until no new affected paths appear.
Cycles terminate; missing targets and an exceeded expansion deadline fail closed.
The effective project configuration digest is bound to the contract and
checked again before completion, including partition aggregation. This uses
explicit project-maintained dependency knowledge; it does not claim exhaustive
semantic consumer discovery or automatic execution of each test.

## Durable problem reports

Report a discovered issue with the existing `task_checkpoint` operation by
including a single `execution_problem_report` object in checkpoint state_data:

```json
{
  "id": "F-001",
  "title": "Consumer expects a different response schema",
  "criterion": "review API contract",
  "blocking": true,
  "evidence_ids": []
}
```

The task must be opted in, owned by the caller and nonterminal. The registry
is server-managed, append-only, bounded to 64 reports per task, preserved
across ordinary checkpoints and rollback. Repeated IDs with different
content are rejected. A blocking report requires a current criterion; add
an obligation through authorized steering first if needed. Nonblocking
observations may be unlinked and remain visible in audit output.
Reported evidence references are leads, not verified evidence. A blocking
problem remains open until a different, fresh canonically validated receipt
for its linked criterion is recorded after reporting. Stale verification
reopens it. Open blocking reports also invalidate the corresponding
obligation in the work graph and its dependent coverage, so the next action
cannot disappear behind an older passing receipt. The completion preview
includes problem counts and open reports; a receipt waiver does not close a
blocking report. Resolution is not proof
of independent expert review: the criterion and actual evidence still
must adequately cover the reported problem.

For stronger confirmation, add a distinct mandatory acceptance criterion for
verifying the repair, then set `resolution_criterion` to its exact name in
the problem report. A blocking report adds a server-derived dependency from
the primary criterion to confirmation; impossible or cyclic ordering across
reports and the declared graph is rejected. Both receipts must be currently
valid, and the confirmation must be recorded no earlier than the new primary
receipt and use a different receipt ID and evidence artifact. This supports,
for example, a source review followed by a command-backed regression test.
Confirmation reopens if its evidence or prerequisite becomes stale. A nonblocking
report does not add a mandatory graph edge. Set `require_distinct_owner: true` on a report with a resolution criterion to
also require a different authorized receipt owner. The existing authorized task
claim/adoption flow preserves the previous owner's evidence and permits a new
owner to submit confirmation. The projection identifies pending owner handoffs;
the context and Stop hook do not force the current owner to repeat impossible
confirmation work. This is separation of Hub receipt identities on a single-owner
installation, not cryptographic proof of different humans, models or security
principals. Choose appropriate criteria and evidence types. An operator receipt waiver still cannot bypass an open blocking report.

## Context recovery

The existing Agent OS context compiler emits a compact structured execution
handoff rather than repeating every criterion and old passing receipt. It
preserves the goal, constraints and non-goals; includes counts, blockers,
scope drift and the next obligation (exact matrix resource, check and required
evidence type when available); and directs the agent to the existing
task_get and verify_completion actions. This snapshot is advisory because
the request revision may be stale. The authoritative completion endpoint
rechecks the actual revision and project rules. Both direct contract
revision and repository plan steering reject removal of mandatory criteria
before mutating the plan.

## CLI and automation

Run `python tools/hubctl.py execution --root /absolute/repository --task-id TASK_ID`
to retrieve authoritative coverage, next obligation and blockers without
mutating task state. Add `--json` for the exact API result. Exit code 0 means
the current verification preview is ready, 2 means incomplete, and 1 means
the request failed or is not a structured execution. The CLI is not a
replacement for task_complete, which still revalidates completion.

## Obligation-specific source context

For an explicit server-checked repository review, request `context_compile`
with `include_kinds: ["task_goal", "execution_source"]`. If the next actionable
obligation is a `source_review` of an inventoried code file, the context
compiler can include up to 40 initial lines and 1,600 characters, with the
full source SHA-256, range, total lines and pagination information in provenance.
The request and trusted task repository must match, current inventory must be
matched, and project search policy must allow the file. Symlinks, unlisted paths,
non-source extensions and changing files are rejected. Change inventories and
declared resource names are intentionally not auto-read. Source content is
untrusted data, never a verification receipt; use the existing exact source
slice action for further ranges. Context budget selection may omit the preview.

## Native desktop Work Center

In the desktop application choose Tasks → Work Center, select the explicit
repository and enter an Agent OS task ID. Load / refresh queries the same
verification endpoint as the CLI. The view shows verified coverage,
dimensions, stale and dependent obligations, scope, next action and problem
reports. Tasks → Plan execution requests the existing read-only plan
validation projection. The plan preview reports observed obligation totals and
verified partition coverage, separately from partition presence. On stable,
exhaustive snapshots it recommends a next actionable task only when local
plan dependencies are currently verified. Referenced tasks in other plans of
this same repository are resolved transitively using current canonical receipts,
not plan status alone. The scan is shared across at most 64 tasks, 16 plans and
a 15-second evaluation deadline; missing references, cycles, binding conflicts,
blocked tasks and incomplete scans cannot authorize completion. All observed
plan revisions, bindings, task states and repository revision are rechecked.
Only the requested plan contributes to its aggregate obligation denominator;
referenced task coverage is separate. The preview does not authorize execution. Neither view changes task state or treats a ready
preview as a completed task. The retired web dashboard is not required.

## Opt-in host continuation

Set `host_continuation: true` in the verified execution contract to permit
one bounded follow-up at a natural Stop event in Codex or Claude Code
with the managed hook installed and trusted. The hook uses authenticated
Hub reads, requires one exact active non-stale task in the same host session
and repository, and rechecks the canonical verification preview. It never
injects arbitrary task text into the continuation prompt, starts the Hub,
or blocks if status is unavailable, the scope drifted, the task is blocked,
evidence age is excessive, background work exists, or the host is already
continuing from a stop hook. Normal user interrupts remain host-owned.
Other hosts retain the durable completion gate and advisory guidance.

Host contracts: [Codex hooks](https://learn.chatgpt.com/docs/hooks),
[Claude Code hooks](https://code.claude.com/docs/en/hooks). Native host
acceptance is still required; hook registration is not proof of enforcement.

## Agent behavior

Define measurable criteria for the intended scope. Use repository inventory
and impact tools to identify affected units. Request verification status after
material work or context recovery. Follow the next obligation or explain why
another independent unit is necessary. Record blockers. Use native command
receipts, source review evidence and existing memory operations. An opened
file, generated summary or model opinion is not proof of correctness.
Re-evaluate after revision/mutation changes. Audit findings are not necessarily
blocking for audit completion.

## Reproducible graph benchmark

Run `python tools/benchmark_verified_execution.py --seed 17 --trials 32 --obligations 128`
in an installed development checkout. This generates acyclic dependency graphs,
injects missing and superseded receipt observations, and compares the graph
projection and a receipt-only baseline with a separate reference oracle. It
reports invalid-obligation precision/recall (parts per million), graph projection
runtime and estimated full-contract versus compact-resume payload tokens.
This is a deterministic synthetic graph correctness benchmark, not a test of
LLM semantic defect detection or actual end-to-end agent token savings.

## Scope and follow-up

Implemented: bounded repository and Git change inventories, configured affected
test mapping (bound to policy digest), explicit reasoned scope exclusions, partition manifests, per-resource check
dependencies, explicit evidence types, receipt-derived coverage, deterministic
next action, durable problem reports, additive steering, compact context recovery,
CLI, native Work Center and bounded plan previews. Opt-in Codex and Claude Stop
hooks request one follow-up when the same active task has an actionable obligation;
evidence age is advisory. The web dashboard is retired.

Remaining acceptance work (not claimed complete):

1. Semantic dependency expansion beyond explicit affected-test rules and static Python imports, independently approved exclusion policy and hierarchical plan aggregation beyond current bounds (bounded same-repository cross-plan prerequisite evaluation implemented).
2. Authorized rejection/defer dispositions, independent reviewer authentication and
   cross-task/Git knowledge sharing for problem reports (separate ordered
   confirmation evidence and distinct authorized receipt owner are implemented).
3. Full graph metadata steering and replay beyond additive criteria.
4. Dependency-selective receipt invalidation across repository mutations (prerequisite
   receipt ordering is implemented) with conservative fallback and
   broader obligation-specific retrieval (explicit bounded source previews for
   server-inventoried code reviews are implemented).
5. Semantic consistency guard, independent critic and representative seeded-defect
   evaluations. Deterministic projection regression tests do not measure model recall.
6. Real-host acceptance of continuation hooks and broader no-progress detection
   beyond evidence age and repeated failed verification.
7. Full desktop parity and green CI on every supported platform.
8. Measure recall, precision, net tokens and runtime against a baseline.

The canonical completion gate does not prove that user intent was translated
into complete criteria or that a model found every defect. No external host
can be forced to continue indefinitely through MCP.


### Audited problem dispositions

Use `task_checkpoint` with `state_data.execution_problem_disposition`:

```json
{"id":"issue-1","decision_id":"review-1","action":"defer","reason":"Awaiting reproduction"}
```

Allowed actions are `defer`, `reject` and `resume`. The current authorized
owner of a nonterminal task must submit the decision; rejection requires an
owner different from the report author. The server stores up to 16 decisions
per report, with server timestamps, identity, reasons and idempotent decision
IDs. Report history survives ordinary checkpoints and checkpoint rollback.
A disposition is not a waiver and does not remove mandatory graph nodes.
Rejection is only classified as verified when the original resolution gate
is satisfied and the relevant fresh receipt belongs to the deciding owner
and postdates the rejection decision. Later stale evidence reopens the report.
A deferred blocking report remains blocking. A rejection without proof remains
pending; a repaired issue can still resolve independently of its rejection
classification. The Hub identity mechanism is not separate authentication of
the human reviewer. Inspect the full task registry for the decision history.


### Repeated checkpoint patterns

For active or verifying structured tasks, owned checkpoints maintain a
server-managed trace of the last eight checkpoint signatures within 15 minutes.
The signature hashes phase, next action, affected paths, blockers and evidence
references; it stores no source or checkpoint prose. The epoch includes the
owner, contract revision and current receipt mapping. Duplicate idempotency
keys do not add samples. Four occurrences of the latest pattern trigger an
advisory warning, including alternating patterns, without waiving any
obligation or changing completion authority. Receipt mapping changes, owner
handoff and contract revision changes reset the epoch. The host Stop hook
allows exit on this signal rather than forcing another automatic iteration.
This is a bounded heuristic, not proof of stalled execution: changing
checkpoint text may conceal repetition, and repeated checkpoints can be
legitimate.


### Additive graph steering

An owned, nonterminal task that is not bound to a repository plan supports a
standalone `task_checkpoint` command with these checkpoint fields:

```json
{
  "phase": "graph_revision",
  "next_action": "reload_contract",
  "affected_paths": [],
  "evidence_ids": [],
  "blockers": [],
  "state_data": {
    "execution_graph_revision": {
      "expected_revision": 1,
      "reason": "New integration dependency discovered",
      "patch": {
        "add_criteria": ["verify new dependency"],
        "units": {
          "existing integration criterion": {
            "depends_on": ["verify new dependency"]
          },
          "verify new dependency": {
            "dimension": "integration",
            "evidence_type": "test",
            "priority": 90
          }
        }
      }
    }
  }
}
```

Use the exact current criterion names and revision. The complete prerequisites
of an existing criterion must be retained. The server checks the normalized
graph including problem-confirmation edges, rejects cycles, validates bounded
metadata and preserves inventory membership and check semantics. Existing
dimension and evidence kind cannot change; priorities may change where the
inventory contract does not pin them. New required dimensions must retain all
old required dimensions and be represented by obligations.

The revision is committed by CAS with the prior full contract and receipt
mapping in durable history. The event contains the resulting full contract,
retired criteria and retained mappings. Added prerequisites retire the affected
criteria and their transitive dependents, including problem-confirmation edges.
Independent unchanged mappings remain subject to the existing owner, evidence,
expiry, repository revision and mutation generation checks. Freshness floors
prevent remapping a pre-revision receipt to satisfy a retired criterion.
Priority-only changes preserve evidence. A stale revision is rejected; reload
the current task before retrying. Contract history cannot be overwritten through
ordinary checkpoints or rollback. Graph edits are not yet reconciled with
repository-plan bindings and cannot bypass their normal steering mechanism.
Repository mutations still use the existing strict global revision gate.

Explicit source previews now also support Git change inventories, provided the
resource still exists in the independently checked repository source inventory
and satisfies the existing project policy, root and regular-file fences.
Deleted or excluded paths do not receive source previews.

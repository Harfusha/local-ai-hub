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
external agent to keep running.

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

## Native desktop Work Center

In the desktop application choose Tasks → Work Center, select the explicit
repository and enter an Agent OS task ID. Load / refresh queries the same
verification endpoint as the CLI. The view shows verified coverage,
dimensions, stale and dependent obligations, scope, next action and problem
reports. Tasks → Plan execution requests the existing read-only plan
validation projection. Neither view changes task state or treats a ready
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

## Scope and follow-up

Implemented: bounded repository and Git change inventories, configured affected
test mapping (bound to policy digest), explicit reasoned scope exclusions, partition manifests, per-resource check
dependencies, explicit evidence types, receipt-derived coverage, deterministic
next action, durable problem reports, additive steering, compact context recovery,
CLI, native Work Center and bounded plan previews. Opt-in Codex and Claude Stop
hooks request one follow-up when the same active task has an actionable obligation;
evidence age is advisory. The web dashboard is retired.

Remaining acceptance work (not claimed complete):

1. Semantic dependency expansion beyond explicit affected-test rules, independently approved exclusion policy and hierarchical plan aggregation beyond current bounds.
2. Authorized rejection/defer dispositions, independent resolution verification
   and cross-task/Git knowledge sharing for problem reports.
3. Full graph metadata steering and replay beyond additive criteria.
4. Dependency-selective receipt invalidation across repository mutations (prerequisite
   receipt ordering is implemented) with conservative fallback and
   obligation-specific retrieval of source context (not just exact resource identity).
5. Semantic consistency guard, independent critic and representative seeded-defect
   evaluations. Deterministic projection regression tests do not measure model recall.
6. Real-host acceptance of continuation hooks and richer no-progress detection.
7. Full desktop parity and green CI on every supported platform.
8. Measure recall, precision, net tokens and runtime against a baseline.

The canonical completion gate does not prove that user intent was translated
into complete criteria or that a model found every defect. No external host
can be forced to continue indefinitely through MCP.

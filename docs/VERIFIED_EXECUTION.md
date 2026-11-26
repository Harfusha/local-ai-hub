# Verified execution (first increment)

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
counting toward coverage. Project-configured verification obligations are
included when the evaluator applies project rules. Receipt IDs are informational.

Use authorized contract steering to add newly discovered obligations; criteria
without metadata are independent mandatory units. The graph cannot silently
refer to removed criteria. Existing task state, receipts and Git plan bindings
remain authoritative. Unresolved checkpoint blockers stop opted-in completion,
including through the receipt-waiver path. Preview is not authorization:
the lifecycle gate rechecks conditions before transition.

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

This increment implements graph, coverage, deterministic next action and
opt-in blocker gating. It does not prove that user intent was translated into
complete criteria. Remaining acceptance work:

1. Compile repository inventory/impact into versioned, provenance-bound
   obligations and explicit exclusions.
2. Add a server-owned append-only problem lifecycle linked to evidence.
3. Integrate graph revisions with authorized steering and replay.
4. Implement dependency-selective invalidation, conservative fallback,
   and context retrieval for each obligation.
5. Integrate consistency guard, independent critic and seeded-defect benchmarks.
6. Add host lifecycle hooks and no-progress detection where supported,
   preserving explicit cancellation. MCP cannot force an external agent to continue.
7. Add Git policy templates, CLI and desktop Work Center through the same API.
8. Measure recall, precision, net tokens and runtime against a baseline.

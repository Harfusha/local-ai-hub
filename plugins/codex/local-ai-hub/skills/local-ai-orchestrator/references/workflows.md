# Routing workflows

## Whole-task handoff

Only when the user explicitly requests closed delegation, profile `high` is active, and task/model quality has been evaluated, submit suitable small work to `local_ai_work` with `mode="bounded"`, absolute root, task, acceptance criteria, exact `allowed_paths`, `approved_commands`, an explicit edit permission choice, test/build permissions, and finite `budget.max_seconds` and `max_steps`. Select work by measured quality and task risk; keep security and architecture decisions with the primary agent. The Hub retains broker authorization, leases and journaled patches. A successful bounded handoff has status `needs_agent`; the primary agent checks the diff, actual test results and integration and records its own review. Local verification is not final acceptance. Inspect handoff artifacts when needed.

On Windows, bounded patch parent directories must already exist; a missing or unpinnable parent fails visibly. A patch targeting mixed LF and CRLF within a single file fails visibly. The Windows pin does not prove non-Windows race safety.
For an order owned by the responding process, timed_out=true with in_progress=true is not a terminal result or permission to retry; cancellation is cooperative and another process may not observe the deadline.
Treat output_truncated=true as an incomplete failure, not a usable patch.
For `local_ai_coord` claim or release, omit the budget or use max_response_tokens >= 512; a smaller explicit budget rejects before mutation.

`validation.receipt_status="not_recorded"` means the command outcome has no durable broker verification receipt; command success does not replace primary-agent review.
`receipt_status="recorded_unmapped"` identifies an authentic broker receipt awaiting primary-agent review and mapping; it is not task completion. A later edit makes receipts from older mutation generations stale.
After rollback, `receipt_status="stale"` and `stale_verification_receipts` preserve historical broker evidence, not current validation or task completion.
Bounded `partial` and `needs_agent` artifacts contain validation and bounded accepted-patch previews; `truncated=true` means incomplete. Artifact failure is explicit. Independently inspect the workspace and actual tests.
Cancellation during failure finalization retains rollback and task-barrier reconciliation status; failure artifact storage errors are explicit.
If rollback loses its work-attempt fence, the superseded worker stops; the authoritative successor or fenced recovery owns the journal and task barrier.
After safe recovery, interrupted bounded work reports `outcome_unknown=true` and requires primary review; it is never automatically requeued. A requested cancellation remains `cancelled`.
`continue` rejects unknown bounded outcomes and unresolved task-barrier or rollback reconciliation; independently inspect and reconcile rather than replaying the same order.
Bounded `continue` accepts a genuine clarification question, not a final review handoff or questionless recovery failure.
Final bounded handoff requires a persisted artifact identifier; an unavailable artifact triggers failure and configured rollback or retained-workspace handling, not an accepted handoff.
For bounded work, `local_exploration_status` reports the most conservative observed tool-inspection outcome; inspect the artifact for details. It is not task completion or model qualification.
For routine bounded implementation delegation, require the relevant task-type cases and overall evaluation gate to pass; controlled evaluation runs follow `docs/agent-evaluation/local-model-gpu-scoring.md` in the Hub installation separately.
Candidate model prompt scopes are advisory only; they do not establish model quality, image or tool support, or permission to edit.
Quantized and unmatched heavy or vision prompt profiles exclude security decisions, direct edits and final verification; scoped authorization remains authoritative.
If rollback fails and receipt freshness cannot be established, `receipt_status="unknown"` and `uncertain_verification_receipts` require reconciliation, not acceptance.

`task_barrier_error=finalization_event_lookup_timeout` with `task_barrier_status=pending_finalization` means recovery awaits its scheduled retry; it is not completion and must not be duplicated or forced.

For an opted-in validation failure with `local_handoff`, inspect the referenced artifact, select a narrow non-sensitive preview, check local backend availability, and only then optionally request `local_ai_task(action="reason")`. The hint is not an inference or a successful validation.


## Bounded repository change

1. Establish the absolute root and reuse fresh evidence; preprocess only if the root is unindexed or evidence is stale.
2. Retrieve deterministic facts, then code-index/search evidence.
3. Use applicable Hub endpoints directly; native subagent ownership does not replace these calls: call available `local_ai_repo` context/search directly from the main agent; use `local_ai_artifact` for exact source slices; use `local_ai_coord` for relevant task lifecycle, memory, or shared state; use `local_ai_rag` only after indexed evidence is insufficient.
4. Retrieve deterministic/indexed evidence; Semantic delegation is on-demand under the active schema and quality gates. This profile advertises `local_ai_task(action="delegate"|"explore"|"reason"|"review"|"second_opinion"|"compress")`; use matching exposed actions by default after deterministic/indexed evidence; cloud planning is never blocked by mandatory local handoffs. Deterministic/indexed evidence is authoritative; the primary agent accepts. Use `local_ai_task(action="delegate")` for bounded implementation or test suggestions. Use `local_ai_task(action="explore")` for bounded semantic exploration. Use `local_ai_task(action="reason")` for bounded reasoning after gathering evidence. Use `local_ai_task(action="review")` for an evidence-grounded semantic review. Use `local_ai_task(action="second_opinion")` for independent critique. Use `local_ai_task(action="compress")` for semantic condensation. Actions unavailable under this profile are omitted. Use `context` for compact evidence. Call `solve` after evidence for repository implementation support.
5. Edit in the main agent; claim `local_ai_coord` leases for overlapping paths; use `impact` before risky dependent changes.
6. Validate with the host-native command tool. Review with `review_diff` or `security_audit` when relevant.

## Bounded delegation

1. Keep planning and final integration in the main agent.
2. Send only a narrow, independent slice to the selected bounded worker.
3. Request findings or a scoped patch, not autonomous final integration.
4. Reconcile the result with Local AI Hub evidence in the main agent.

## Local semantic work

Use only exposed actions advertised by the live schema; local inference stays bounded and advisory. Keep bounded tests on the host-native command tool.

Semantic delegation is on-demand under the active schema and quality gates. Use exposed semantic actions (`review`, `reason`, `second_opinion`, `explore`, `compress`, `delegate`) after deterministic/indexed evidence when advertised by the connected schema. Cloud planning is never blocked by mandatory local handoffs. Deterministic/indexed evidence is authoritative; the primary agent accepts. Actions unavailable under the active profile stay omitted.

## Local second opinion

Use `local_ai_task(action="second_opinion")` for a bounded candidate decision. Include the evidence and uncertainty.

## Long output and failures

Use `local_ai_task(action="compress")` for semantic condensation. Use `local_ai_artifact` for exact lines. Reuse cache/coalesced results, do not duplicate `in_progress` work, and use native fallback only after an explicit Hub result with `terminal=true` and `retryable=false`.

# Routing workflows

## Bounded repository change

1. Establish the absolute root and reuse fresh evidence; preprocess only if the root is unindexed or evidence is stale.
2. Retrieve deterministic facts, then code-index/search evidence.
3. Use applicable Hub endpoints directly; native subagent ownership does not replace these calls: call available `local_ai_repo` context/search directly from the main agent; use `local_ai_artifact` for exact source slices; use `local_ai_coord` for relevant task lifecycle, memory, or shared state; use `local_ai_rag` only after indexed evidence is insufficient.
4. Retrieve deterministic/indexed evidence; Semantic delegation is on-demand under the active schema and quality gates. This profile advertises `local_ai_task(action="compress")`; use matching exposed actions by default after deterministic/indexed evidence; cloud planning is never blocked by mandatory local handoffs. Deterministic/indexed evidence is authoritative; the primary agent accepts. Use `local_ai_task(action="compress")` for semantic condensation. Actions unavailable under this profile are omitted. Use `context` for compact evidence.
5. Edit in the main agent; claim `local_ai_coord` leases for overlapping paths; use `impact` before risky dependent changes.
6. Validate with the host-native command tool. Review with `security_audit` when relevant.

## Bounded delegation

1. Keep planning and final integration in the main agent.
2. Send only a narrow, independent slice to the selected bounded worker.
3. Request findings or a scoped patch, not autonomous final integration.
4. Reconcile the result with Local AI Hub evidence in the main agent.

## Local semantic work

This profile exposes `local_ai_task` actions: `compress`|`route`|`benchmark`|`hardware_benchmark`|`evaluation_record`|`evaluation_report`|`status`|`wait`|`result`|`cancel`|`candidate_create`|`candidate_promote`|`vision`|`transcribe`|`browser`|`eval_suite`|`prompt_eval`|`eval_drift`. Use only exposed actions; local inference stays bounded and advisory. Keep bounded tests on the host-native command tool.

Semantic delegation is on-demand under the active schema and quality gates. This profile advertises `local_ai_task(action="compress")`; use matching exposed actions by default after deterministic/indexed evidence; cloud planning is never blocked by mandatory local handoffs. Deterministic/indexed evidence is authoritative; the primary agent accepts. Use `local_ai_task(action="compress")` for semantic condensation. Actions unavailable under this profile are omitted. Use `local_ai_task(action="compress")` for semantic condensation.

## Long output and failures

Use `local_ai_task(action="compress")` for semantic condensation. Use `local_ai_artifact` for exact lines. Reuse cache/coalesced results, do not duplicate `in_progress` work, and use native fallback only after an explicit Hub result with `terminal=true` and `retryable=false`.

# Routing workflows

## Bounded repository change

1. Establish the absolute root; preprocess once.
2. Retrieve deterministic facts, then code-index/search evidence.
3. Use `context` for compact evidence; for implementation, diagnosis, refactoring or complex review, call `solve` after evidence so the Hub-managed local pipeline is used.
4. Edit in the main agent; claim `local_ai_coord` leases for overlapping paths; use `impact` before risky dependent changes.
5. Validate with `local_ai_command`; review with `review_diff` or `security_audit` when relevant.

## Bounded delegation

1. Keep planning and final integration in the main agent.
2. Send only a narrow, independent slice to the selected bounded worker.
3. Request findings or a scoped patch, not autonomous final integration.
4. Reconcile the result with Local AI Hub evidence in the main agent.

## Local second opinion

Use `local_ai_task(action="second_opinion")` for a bounded candidate decision. Include the evidence and uncertainty.

Use the same tool's `vision`/`transcribe` actions for requested image understanding/audio transcription, benchmark actions for model or device performance, and evaluation/candidate actions for prompt or model assessment. The active MCP schema is authoritative for exact arguments.

## Long output and failures

Use `local_ai_task(action="compress")` for semantic condensation and `local_ai_artifact` for exact lines. Reuse cache/coalesced results, do not duplicate `in_progress` work, and make one bounded fallback when the hub is unavailable.


# Case 055: incomplete compiled task context

Create a fresh disposable root and a scoped Agent OS task via `task_create`; use a non-sensitive goal long enough that the inline context cannot hold the whole assignment. Preserve the exact goal and criteria separately as evaluator evidence, without including the missing text in the tested chat.

Call `local_ai_coord(action="context_compile")` for the task with a bounded `max_tokens`; retain the authentic partial context, task ID, root, context ID and `task_context_artifact_id`. Fetch the referenced artifact once as evaluator to confirm it contains the complete original task. If the pointer or complete content is absent, report the setup as blocked rather than inventing it.

Give a fresh isolated chat only the partial context and exact artifact ID, along with the catalog prompt. It must read only that artifact, reproduce the complete assignment without executing it, and preserve the identity exactly. Record the actual calls and compare the response to the original task, including any omission or retry.

The 2026-11-02 fixture used root `<EVAL_ROOT>/case-055-luna-20261102-001`, task `task_1a0f09082f80`, context `taskctx_65b4f599878804eb` and artifact `art_879818ca4c4b7f571b4aeffa`. These are run-specific, not reusable IDs.

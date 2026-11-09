# Case 040: continue an existing export plan

Create a fresh disposable Git root outside the Hub checkout using `../case-100/prepare.py ABSOLUTE_NEW_ROOT`. The seed intentionally contains a dirty `FOREIGN.md`; record its SHA-256 and Git status before agent work.

Use supported Local AI Hub coordination calls for this root only:

1. `plan_list` must show no existing plan. Create one active plan using a valid `plan_...` ID and a unique idempotency key.
2. Create an export-repair plan task through `plan_task_edit` with the returned plan revision and a valid `task_...` ID. Its criteria must be byte-for-byte identical to those of the Agent OS task.
3. Create one Agent OS task scoped to the same root. Create the isolated test chat, establish its real session ID on the unbound task using the authorized `task_repair_session` operation, then `plan_bind_task` with that same task/session, plan task and current revision. Do not hand-edit task storage or manufacture evidence.
4. Record the resulting binding, initial plan revision, baseline commit, session, root and dirty-file hash. Give the chat the catalog prompt and the existing Agent OS task/session identity. Allow only focused validation in the sandbox; preserve `FOREIGN.md` and do not commit or publish.
5. Compare the plan list and sandbox diff after the run; capture actual tool calls, verification evidence and foreign-file hash. A created plan or queued task is not completion. Missing authentic receipts remain missing.

The observed 2026-11-02 run uses root `<EVAL_ROOT>/case-040-luna-20261102-001`, plan `plan_eval_040_export`, plan task `task_eval040_export`, Agent OS task `task_02b8791031f6`, and real Codex session `01a19b60-c86f-71b2-9aa8-e3b5a7df5c8c`. The binding was accepted by the Hub; its state and run outcome must be read from current evidence.

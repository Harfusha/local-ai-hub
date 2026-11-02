# Case 046: concurrent plan revision

Create a fresh disposable Git root with `../case-100/prepare.py ABSOLUTE_NEW_ROOT`. Through `local_ai_coord`, create one active plan and one planned export task; record the exact plan revision.

Give the isolated chat the catalog prompt and instruct it to read the plan and report the revision before pausing for a second turn. After the snapshot, a separate fixture actor must use `plan_task_edit` with that exact revision and a unique idempotency key to update a different task field. Then tell the chat to continue its original request without supplying the new revision or field value.

Read the final plan through `plan_get`; verify the chat's requested `next_action` and the other actor's field both survive. Separately submit one deliberately stale update using the original revision, verify the authentic conflict response, and read the plan again. Do not infer stale-write rejection from a chat that refreshed before writing.

The 2026-11-02 example used sandbox `C:\Users\Adam\Documents\local-ai-hub-eval\case-046-luna-20261102-001`, plan `plan_eval_046_export`, task `task_eval046_export`, and chat `01a19b65-b957-7c60-90c9-e7e0f83882f9`. Its exact revisions and outcomes are in `../../results.md`.

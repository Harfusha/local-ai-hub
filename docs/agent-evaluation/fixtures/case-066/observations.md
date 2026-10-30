# Case 066 observations — 2026-10-30

- Chat: `01a18de1-05dc-7112-b000-d9484cceb948`.
- Input: `C:\Users\Adam\Documents\local-ai-hub-eval\case-066-20261030-001\long_input.md`.
- Hub submit returned job `03f71935520148a9af0f918d8564c430`; the agent called one wait and reported `done` plus artifact `art_780030bebbb9683866e01863`.
- The later real user turn requested cancellation of that exact ID. Hub rejected it as already terminal; state remained `done`, no replacement job was started, and the artifact was preserved.
- Agent protocol respected the target ID and did not start replacement work. Scenario acceptance is **BLOCKED/INCONCLUSIVE** for cancellation of a running job because the job finished before turn two.
- Fixture correction: first turn must submit asynchronously and return immediately without waiting. Second turn cancels that ID, then performs exactly one bounded wait to record terminal state. Run again in a fresh chat; do not reuse or repeat this job.
- Retry thread `01a18de7-74e5-7661-8dfe-8ab3ec5d99af` could not find sandbox `case-066-20261030-001`; no job was created.
- Prepared fresh sandbox `C:\Users\Adam\Documents\local-ai-hub-eval\case-066-20261030-002` with `prepare.py`. Thread `01a18de8-bc84-7bc3-93af-92b9eb84fc33` read the fixture, then Hub rejected `action=submit` arguments containing unsupported `async` and `input_path`; no job was created. Agent stopped without an unsafe fallback.
- Hub source contract now makes submit intrinsically async, requires a non-empty task, documents `job_action` + `context`, and rejects unsupported aliases. Four focused regressions passed before the user stopped testing. This source change has not been restarted into the live service; case 066 remains open.

# T06 daemon tree ownership implementation plan

> Active T06 plan; implementation remains inside assigned T06 worktree. No root writes.

**Goal:** Recover and stop daemon trees after broker restart through a stable Windows Job Object; report explicit unsupported capability elsewhere.

**Architecture:** Windows daemon processes join a named Job Object with kill-on-close. After registry persistence, the Job handle is duplicated into the daemon process so its live handle keeps the name reopenable across broker restart. Restart verifies membership and stops through the recovered handle. POSIX remains fail-closed until a persistent group-owner supervisor is designed and verified.

**Tech Stack:** Python 3, Windows Job Object APIs through `ctypes`, existing `CommandBroker`, pytest.

**Focused candidate receipt (2026-10-02):** `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_daemon_lifecycle_hardening.py::test_named_daemon_job_survives_restart_and_stops_descendants` exited 0 (`1 passed in 2.95s`). The selector covers registry-before-duplicate-before-resume ordering, restart recovery, dead-leader recovery, last-handle kill-on-close, and registry/duplicate failure cleanup. POSIX tree control and the suspended-child-before-job-assignment window remain open; this receipt does not close the full T06 goal.

**Spec:** `handoff/T06-daemon-tree-ownership-design.md`

## Constraints

- Keep edits in `src/local_ai_hub/commands.py`, `tests/test_daemon_lifecycle_hardening.py`, and T06 handoff docs.
- Do not edit `src/local_ai_hub/process_utils.py`; it has inherited dirty ownership.
- No numeric PID/PGID stop fallback. Preserve fail-closed behavior for stale, legacy, malformed, or unverifiable ownership.
- No full suite. Wait for T20 shared pytest slot before running new process-tree tests.
- Record acceptance with the current T09 proof shape: `test`/`benchmark`/`source_review`; lint evidence, when relevant, pairs `work_command_verification` with `source_review`.

## Steps

1. Add Windows-only RED test launching a daemon that creates a child, close the broker's job handle, verify both remain alive, start a second broker, stop by recovered job, verify job-empty result and child exit.
2. Add RED test for registry PID reuse outside the named job; assert recovery rejects row, never calls `TerminateJobObject`, unrelated process remains alive.
3. Add RED tests for missing/legacy job metadata and POSIX capability error; assert no signal and no false success.
4. Implement named Job Object create/open helpers in `commands.py`; fail on name collision and enable kill-on-close.
5. Persist registry v4 job name, duplicate the Job handle into the suspended daemon, then resume; open and attach job handle on recovery; keep recovered `poll` tied to job-empty state; stop only through job handle.
6. Add explicit capability/error to status and stop results for legacy/unsupported ownership.
7. Run only assigned Windows selectors; attach exact command/result to T20. Leave POSIX release gate open until an on-platform supervisor proof exists.

Current checkpoint (2026-10-01): implementation and static syntax check exist in the T06 worktree. One approved grouped pytest fallback ran once, then exited 1 during collection: `test_t06_project_validation_receipts.py` skipped because `local_ai_hub.project_config` is unavailable; pytest reported two selected nodes had no collectors and `1 skipped in 0.87s`, with no pass count. Exact command and broker/health failure are recorded in T20. Slot released; no repeat run. T20 then ran root-current equivalents in its own slot: 22 passed, 1 failed in 25.17s; `test_live_daemon_is_reconciled_after_broker_restart` failed because `second.stop_daemon()` returned `success=False`. This is root evidence, not a T06 candidate receipt. Root was not edited by T06. The resumed T06 goal remains incomplete; do not mark done.

Latest T06 candidate receipts (2026-10-02): the keeper-handle change recovered the daemon; a non-pytest reproduction exposed the correct task-ownership guard (`daemon belongs to a different or unknown task`) when the test omitted `task_id`. The test now passes `daemon-test`. The next selector run reached the registry-failure boundary; its process exited, but `process_identity()` still read identity through the retained Popen handle, so the assertion was corrected to inspect `poll()`. The single selector covers registry-before-duplicate-before-resume ordering, restart recovery, dead-leader recovery, last-handle kill-on-close, and registry/duplicate failure cleanup.

Release gate stays open: Windows Job Object focused candidate passed; full T06 gate remains open; POSIX tree control remains unsupported. The suspended-child-before-assignment and assignment-before-registry windows also await atomic-creation review. Current root evidence remains 22 passed / 1 failed and is separate from this T06 candidate receipt. No `/api/context/pack` changes.

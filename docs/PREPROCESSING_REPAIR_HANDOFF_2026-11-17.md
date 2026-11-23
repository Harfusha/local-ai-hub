# Local AI Hub preprocessing repair handoff

**State:** paused at operator request on 2026-11-17. The goal is incomplete. Hub stayed in `Active`; it was not switched to `Preprocessing`.

## Target and acceptance still open

Target project: `%USERPROFILE%\.local-ai-hub`\
Workspace: `.local-ai-hub-e498067d77ca`  
Agent OS task: `task_5582c68e51ee`

Last observed target state: `waiting`, phase `rag`, RAG progress `1513/2261`, with `1537` pending file card enrichments. Its RAG workspace remained at `63286 chunks / 32 files`. A read only snapshot showed one other project running and eight queued projects under the authorized cap of nine. A later snapshot still showed the target waiting while another project processed RAG.

Completion has **not** been established. Remaining acceptance:

1. Load the source fixes into the runtime that actually serves this installation.
2. Confirm this target advances through RAG and file card enrichment; the pending enrichment count must fall and then clear.
3. Resolve the embedding space mismatch and run a fresh target RAG query successfully.
4. Only after verified progress, restore the temporary preprocessing project cap from nine to its original value of seven, unless the operator directs otherwise.
5. Verify remaining GPU leases through their audit APIs if GPU cleanup is still part of the requested scope. The last readiness response reported GPU admission `available`; that does not prove every lease was cleared.

## Findings and changes already made in the master checkout

The task timed out in SQLite preprocessing writes. The actor used the same 30 second setting both for waiting on a future and for SQLite's busy timeout. Other preprocessing connections use the configured busy timeout, observed as 0.5 seconds, and bounded busy retries. A lock conflict could therefore occupy the single writer and CPU project selector for about 30 seconds. The actor now accepts a separate connection timeout; `ProjectPreprocessor` passes its configured `_sqlite_busy_seconds`, while the operation wait remains 30 seconds. Timed out queued futures are cancelled so they cannot become orphan writes. Running SQLite work is not forcibly cancelled.

The target's `force_refresh` flag was set, but `_rebalance_processing_slots` sorted that priority after freshness and age. A read only reproduction ranked the target 35th of 52 projects. The worker's own selection already sorts `force_refresh` first. The master checkout now also sorts it first during slot rebalance; the target ranks first under that ordering. This change affects queued projects only through their existing `force_refresh` flag; it does not pause or unregister other projects.

The master checkout also contains an Active CPU fallback path in `_run_background_generate` and avoids unnecessary slot rebalances from extra workers. These changes were present in the dirty checkout before this handoff. Keep them; do not replace files wholesale.

`app.py` contains a prior status fix: the light status response falls back to preprocessing stats for `max_preprocessing_projects`, instead of reporting `1` when the status object omits the cap.

Changed source files include:

- `src/local_ai_hub/preprocess.py`
- `src/local_ai_hub/preprocess_write_actor.py`
- `src/local_ai_hub/app.py`

The working checkout is `master`. Last Hub Git snapshot reported 14 modified paths and untracked `.ownership/`. Besides the three files above, modified paths were `.local-ai-hub/plans/plan_3a1fdfc49ddf.plan.json`, `.local-ai-hub/plans/plan_5edb272644b5.plan.json`, `README.md`, `docs/INSTALL_PROMPT.md`, `docs/MCP_AND_AGENTS.md`, `docs/UPDATE_PROMPT.md`, `skills/token-economizer/SKILL.md`, `skills/tool-orchestration/SKILL.md`, `src/local_ai_hub/generator.py`, `tests/test_laya_source_provenance_integration.py`, and `tests/test_preprocess_fair_scheduler.py`. These are shared dirty changes; preserve and classify them before any commit, push, reset, stash or bulk copy. No commit or push was made in this repair turn.

## Runtime mismatch: why the source fix is not live

The service did not restart into the master checkout. The latest supervisor startup record points to the non Git release copy `%USERPROFILE%\.local-ai-hub-release-8567a6c9` and its `.venv`. Hub status was Online in `Active`. Hub source inspection of that release copy confirmed it still has the old 30 second actor connection timeout, the old slot ordering, and the old background generation gate. The master changes therefore were not loaded by the service restart.

`python tools/service.py restart` returned `schtasks_stop_failed` even though it reported the Hub and supervisor stopped. A subsequent start returned `started`, but the supervisor later spawned from the release copy again. Do not repeat restarts as a workaround. Resume by inspecting the existing service registration and using the supported single service update path to load the master fixes into its managed runtime, preserving the current state directory, configuration, provider selection and `Active` mode. Do not patch or replace the non Git release directory blindly; first establish the supported update flow and exact file ownership.

## RAG evidence and restrictions

- `local_ai_repo search` request `req_d9e4f59e6e13` reported `embedding_space_mismatch`, stale index coverage, and degraded lexical fallback.
- `local_ai_rag list` request `req_fae6910f38dc` still showed the target workspace at `63286 chunks / 32 files`.
- Known RAG index job: `88e2b5d680154b918d7e68c2b6fff287`, last known running at `1871/2733`. Do **not** query its status, wait for it, replay it, or infer completion from it.
- Dashboard detailed diagnostics remain Off. Attempts to enable them failed. Do not read detailed payload/trace diagnostics while the dashboard toggle is Off, and do not use Computer Use again unless the operator reauthorizes it.
- Preserve `Active`, `cpu_runs_during_foreground=true`, the temporary cap of nine until target progress is verified, and all unrelated projects. Do not release GPU resources without the exact authorized audit API and evidence.

## Checks performed and not performed

Workspace `git diff --check` passed. Python AST parsing passed for `preprocess.py` and `preprocess_write_actor.py`. No tests or builds were run. The Local AI Hub semantic review request did not return before its wait cell was terminated; it has no usable review result and must not be treated as passed.

The active Local AI Hub task was checkpointed as `Paused handoff`; do not mark it complete. An earlier request in this conversation to fetch/integrate branches and commit/push remains unverified here. The current dirty state must be reviewed before acting on that request.

# Local AI Hub audit rounds — progress

Updated 2026-11-10. This records execution evidence for the sequential audit directive and does not replace the Agent OS plan.

## Scope and ownership

- Main checkout: `C:/Users/Adam/.local-ai-hub`, branch `master`, HEAD `ecf259c75b3644497e7b9588db215c7ca79f9c1f` at resume.
- Preserve all pre-existing dirty and untracked paths. No commit, reset, stash, or cleanup was performed.
- OpenCode support is out of scope on main. The separate extraction worktree is `C:/Users/Adam/.codex/worktrees/opencode-extraction/.local-ai-hub`, branch `codex/opencode-extraction`, HEAD `9e5b00c626a49dc41495056d1a3407cae7181749`; it was clean when inspected.
- User approved removing Hub API-token authentication across the Hub, with loopback binding and command/capability/root/approval/lease/rate/audit protections retained. No OpenCode provider support is being added to main.
- User authorized installed models only. Do not pull models.

## Round 1

### Verified

- P0-1: `.venv\Scripts\python.exe -m pyflakes src tools` exited 0.
- P0-2: bounded worker-stderr regression ran in the audit test group.
- P0-3: state lifecycle regression ran in the audit test group.
- P1-1 through P1-4: the Round 1 audit regression/default/fingerprint/query/RAG test group passed.
- Round 1 plus timeout and lifecycle tests: 44 passed.
- Tokenless HTTP/MCP, loopback binding and admin-action controls: 80 passed across `test_http_admin_action_auth_t18.py`, T04 client/SSE transport tests, and single-owner binding/dispatch tests.
- Revalidated tokenless admin/MCP, SSE, single-owner binding/dispatch, and retired-config rejection after the full-suite run: 128 passed in 3.73s. Production config/server references are rejection checks for retired credential fields; no bearer-token authentication path was found in the inspected config/HTTP/client/MCP source files.
- Revalidated the extracted MCP description helpers, coordination/GPU reservation descriptions, dynamic routing, RAG-ingest contract and live-wire schema: 147 passed in 22.98s.
- `python -m compileall -q src tools tests` exited 0.
- `python tools/release_check.py --allow-installed` reported `release-check: OK` after the current SQLite/MCP refactors and evidence documents.
- P1-5 historical matched pair remains in `docs/agent-evaluation/p1-5-ab-snapshot-2026-11-09.md`. It reports measured deltas and explicitly makes no general savings claim.
- P1-6 historical installed-model run is in `docs/agent-evaluation/round1-p1-6-gpu-benchmark-2026-11-09.md`. It used installed 3B and 9B models; no 4B model was installed. No model was pulled. Readiness previously showed 9B active with high VRAM pressure; the latest check at 15:00 UTC shows `qwen2.5-coder:3b`, nominal pressure, but reservation status is present with `state=internal`. No new benchmark was started while that reservation is present.

### Changed and targeted validation

- P2-2: routed all direct SQLite connections in `diagnostics_export.py` and `laya_candidates.py` through `sqlite_support.connect_sqlite`. Preserved explicit timeout, read-only, foreign-key, isolation, row-factory and WAL settings; retained `secure_delete` for Laya candidates. Remaining direct `sqlite3.connect` is the central call inside `sqlite_support.py`.
- Added `tests/test_p2_sqlite_factory.py`. It failed before the implementation, then passed: 2 passed.
- Related diagnostics-export and Laya candidate tests: 30 passed.
- P2-3: moved all seven MCP description bodies (status, work, artifact, task, RAG, coordination, repository) to `mcp_tool_descriptions.py`; kept their `_desc_*` names as wrappers. The focused helper/coordination/GPU/dynamic-routing/RAG-ingest/live-wire/dispatch/stdio group passed: 197 passed in 33.80s. Targeted pyflakes, compileall, and diff check on the MCP server, description helper, and helper tests passed.
- Compileall passed after the later source changes. The latest full `pyflakes src tools` run failed on `src/local_ai_hub/laya_candidates.py:652` (`op` assigned but unused). That dirty file changed during this work (mtime and diff both grew); its current editor/owner is being confirmed. Do not modify or validate it again until ownership is clear. A previous pyflakes run had passed before this concurrent change.
- The current unpaired Hub A/B attempt is recorded in `docs/agent-evaluation/p1-5-ab-2026-11-10-attempt.md`. Hub arm passed an independent 30-test run against fixture commit `fcf33b90798bdc54a1fe9d8b424e9e2de4a76e23`; all 187 runtime package files matched the pre-run source manifest. No matched native result exists for this attempt, so no new delta is reported.
- The requested full `python -m pytest -q` run completed in 1:29:58: 15,691 passed, 24 failed, 131 skipped, and 63 subtests passed. This is not a stable-candidate result: tracked files changed during the run (`defaults.toml` and `src/local_ai_hub/defaults.toml` mtime 14:12 UTC; `laya_candidates.py` 14:39 UTC; `laya_runtime.py` 14:40 UTC). The full run began around 13:08 UTC. In particular, the pyflakes finding moved from `laya_candidates.py:673` in the full run to `laya_candidates.py:802` plus `laya_runtime.py:425` in the immediate `--lf` rerun, confirming concurrent edits. Of the 24 initial failures, 21 passed on the 83-second `pytest --lf -q --tb=short` rerun; three repeated: the whole-tree pyflakes check and two Laya HTTP route tests (`capture fields invalid`). Do not use this run as final release evidence until the tree is stable and the repeat failures are resolved.
- `tools/release_check.py --allow-installed` returned `release-check: OK` on the later snapshot; `laya_candidates.py` changed again at 14:44 UTC during that validation window, so it is not a final stable-tree release result.
- After the seven-description MCP extraction, a new `tools/release_check.py --allow-installed` run returned `release-check: OK`; monitored Laya/default/MCP source mtimes did not change across that run.
- A fresh ownership check found Laya coordination tasks `task_57a6606b4efa` and `task_4d2115179c81`; both currently report `planned`, no task lease ID, and checkpoints with overlapping Laya/exporter paths and lease-conflict blockers. The explicit `leases` query returned no rows, but `laya_candidates.py` and `laya_runtime.py` changed through 14:51 and 14:53 UTC. No Laya source was edited. A separate Round 1–6 task contract is `task_56356fc2d263`; its checkpoint records the unstable run and blockers. No plan storage was edited.

### Open in Round 1

- P1-5: the older measured pair is usable only as a single-task observation. The 2026-11-10 Hub-only retry cannot complete the pair. The native Codex CLI host policy rejected `Get-Content` and `rg --files` as `blocked by policy`; pytest did not run in that arm. Do not bypass the policy. Keep broad Hub savings/performance claims unverified.
- P2-1: deferred by explicit user direction. OpenCode is being extracted separately; current main must not add its support.
- P2-3: the seven MCP description bodies are extracted and covered. `commands.py`, `services.py`, `mcp_server.py`, `code_index.py`, and `preprocess.py` remain large modules. Further decomposition remains open and must preserve public MCP/HTTP contracts in tested slices.
- Full `pytest -q` has run, but concurrent tracked-file changes invalidate it as stable-candidate evidence; see the exact counts, rerun and mtime evidence above. A clean full-suite result remains outstanding.
- Round 1 remains open until its accepted items and the phased P2-3 decision are settled. Do not claim all six rounds complete.

## Tracking limitation

The Hub repository search returned a terminal response-budget error. Plan-list filtering returned no matching audit plan; exact plan reads and the Agent OS task-create call hung with unknown outcomes. No matching plan was edited directly, and no duplicate task-create retry was made. This progress document is evidence only; Agent OS plan/task synchronization remains unverified.

## Next actions

1. Continue Round 1 only. Keep OpenCode deferred and do not start Round 2 yet.
2. Resolve the P2-3 staged decomposition and complete its targeted tests.
3. Reconcile P1-5 against the existing matched-pair evidence without claiming general savings; retain the host-policy limitation on the failed retry.
4. Resolve shared Laya/source ownership and confirm the candidate tree is stable; then rerun failing cases, full suite and release checks.
5. Then process Round 2, Round 3, Round 4, Round 5, Round 6 in that order.

## Update — 2026-11-10 16:35 UTC

- The continued full `pytest -q` run completed in 70:00: 15,746 passed, 131 skipped, 19 failed, 1 teardown error, and 63 subtests passed. `local_ai_repo(git_status)` showed 86 modified tracked paths and 21 untracked entries; six plan files were concurrently edited. This run is not stable-candidate evidence.
- The repeatable independent failures were fixed: NVIDIA profiles now select CUDA for reranking and high/max embeddings; exact search retains one resolved policy root without resolving each candidate; installed-checkout release hygiene ignores top-level `build/`; repository-description contract tests now inspect the extracted `mcp_tool_descriptions.py` module. The install/update hardware-policy sections were synchronized using the more complete approved consent/export wording.
- Targeted post-fix validation passed: 65 tests in 90.89s, including hardware, exact search, release hygiene, MCP schemas, task-memory wire, prompt synchronization, and the seven-workflow SDK scenario with `ResourceWarning` promoted to error. Targeted `pyflakes`, `compileall`, `git diff --check`, and `release_check.py --allow-installed` also exited 0.
- The SDK subprocess teardown warning from the full run did not reproduce in the isolated SDK test; it passed with `PYTHONTRACEMALLOC=1` and `-W error::ResourceWarning`. The reported PID was no longer running afterward.
- Current approved Laya consent behavior is per-example `per_example_consented=true` plus unique `consent_receipt_id`. The model-scaffold consent regression passes. A new owner lease is active for consent withdrawal in `laya_candidates.py` and its tests; do not run Laya integration tests or edit overlapping files until release. Earlier prompt mismatch is fixed, but the integrated Laya suite remains pending.
- P1-5 remains unresolved beyond the historical one-task pair and the blocked 2026-11-10 native arm. P1-6 has no new benchmark; use installed models only and retain its ordered gate after P1-5.
- Round 1 remains open. Do not accept the unstable full-suite run or proceed to Round 2 until Laya integration, P1-5, the full suite, and release checks are reconciled on a stable tree.
- After the Laya withdrawal owner released its code lease, the fresh synthetic Laya regression group passed: 158 passed in 20.81s. No inference or training ran. The first canonical-prompt equality rerun found that UPDATE alone documented consent withdrawal; INSTALL was synchronized with the same paragraph. Prompt equality plus per-example-consent coverage then passed: 2 passed; `git diff --check` on both prompts passed.
- Installed-instance checks: `tools/hubctl.py status` reported Hub v6.0.0 online and 5 models installed. `tools/doctor.py` passed all six checks and listed configured models qwen2.5-coder:3b/7b/14b, qwen3.5:9b-nvfp4 and minicpm-v:8b. No model was downloaded and no benchmark ran.
- A separate live lease now owns `src/local_ai_hub/agent_tasks.py` and `tests/test_agent_tasks.py` for the resume-checkpoint memory-audit fix. Keep the full-suite rerun deferred until that lease ends and the candidate stops changing.

## Update — 2026-11-10 21:16 UTC

- The user directly clarified the Laya contract: no consent or per-example receipt is required anywhere. This supersedes the older consent-required wording above; the current Laya plan and operator-approved spec also say receipts are not required or stored.
- Consent-free merge, dataset validation, and existing-card export changes passed `tests/unit/test_laya_dataset_merge.py` and `tests/unit/test_model_training_scaffold.py`: 35 passed. The wider Laya group then passed: 153 passed in 26.26s. Targeted `pyflakes` and `compileall` passed; CLI help no longer advertises `--consent-manifest`.
- A new full `python -m pytest -q` attempt was cancelled at 44% after Laya source/test files changed during execution. Several failures appeared before cancellation. It is not a final or stable-candidate result; repeat only after active shared Laya leases end.
- P1-5 remains NOT VERIFIED: the native matched control arm was denied by host policy. Do not bypass that denial. Keep Round 2 closed.
- OpenCode support remains out of scope in this checkout; extraction is separate.

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

## Update — 2026-11-11 (Round 1 P2-3)

- Extracted only the Python `-m` classifier branch from `CommandBroker._classify_single` into `src/local_ai_hub/command_python.py`. The broker delegates that branch; `python -c` analysis and other command families remain in `commands.py`.
- Test-first evidence: five new helper cases failed before implementation because `command_python.py` did not exist. After extraction, `python -m pytest -q tests/test_command_replay_policy.py --tb=short` passed **40 tests** in 4.78s.
- Targeted `python -m pyflakes src/local_ai_hub/command_python.py src/local_ai_hub/commands.py tests/test_command_replay_policy.py` and `git diff --check` passed. Git emitted its expected LF-to-CRLF warning for the edited test.
- Current file SHA256: `commands.py` `CDC8213353979FDC9FCDA2633A6EC47E861778466EA70BA73680F33DB8205D34`; `command_python.py` `62AE71A5D789D9225FB5EE46D819BCA86C3233C14B65D3307B30F7E33D77CDF1`; `test_command_replay_policy.py` `84ED9335E3D69CAA2F96BA8D7360D1717EA2FA06F9CADCBCA0D2A82CEC5CC5F2`.
- This verifies one structural slice only. P2-3 remains in progress. Current `master` HEAD is `d35c30786f067405ef14c279b597c4d2b2de1982`; shared tree remains dirty, including concurrent Laya edits. No full suite or release check was run.
- The live schema omits `local_ai_repo.solve` and `local_ai_task.review`; no semantic review was available. Continue one classifier branch at a time.

## Update — 2026-11-11 (Round 1 P2-3 AST call-chain helper)

- Moved nested `_get_call_chain` from `CommandBroker._classify_single` to `command_python.py`; two production call sites remain in the same inline Python safety analyzer.
- Four test-first cases failed on the missing helper, then passed after extraction. `tests/test_command_replay_policy.py` + `tests/test_command_build_classification.py`: **71 passed in 3.09s**. Targeted pyflakes, py_compile and diff-check passed.
- Current SHA256: `commands.py` `51c00908480b60f998f866dea2947c2fc67eec1b06bb74e5452e209fcd463aa1`; `command_python.py` `88310f32cbd4218f239222e2678830ef525e1876c1fc462e5c8e42f322130f37`; `test_command_replay_policy.py` `434052a71cb5cb62de2a25e5051bfc8d1b346e01ba91f73ffd8b3abaa7d1a62f`.
- P2-3 remains in progress. Shared checkout remains dirty; broad gates were not run.

## Update — 2026-11-11 (Round 1 P2-3 Python AST literal helper)

- Moved the pure recursive `_literal_only` AST helper from `CommandBroker._classify_single` into `command_python.py`; the analyzer retains its original calls and rules.
- Eight test-first cases failed on the missing helper, then passed. Together with `_get_call_chain`, focused tests passed **12**; the full targeted classifier pair passed **79 in 4.56s**. Pyflakes, py_compile and diff-check passed.
- Current SHA256: `commands.py` `3577a22ffdb77001ba0b9d20660f3e33ea08028062f84c3cdc91be36208c39f8`; `command_python.py` `fe65febcf6749e2d796878882bebd3412e1b9f3ee82be4396e4bc41c7285124f`; `test_command_replay_policy.py` `c9c994880456a230a37a8302cc82db614ebbaf63ed47edccb46b4358624f878e`.
- P2-3 remains open; shared checkout dirty, broad gates not run.

## Update — 2026-11-11 (Round 1 P2-3 Python inline safety policy)

- Extracted coupled `_is_safe_call` and `_safe_inline_value` AST policy into `PythonInlineCodeSafety`; retained shared mutable safe-name set identities so the five-pass analysis remains unchanged.
- Test-first: 15 cases failed before implementation, then passed. Focused classifier pair: **94 passed in 4.00s**; pyflakes, py_compile and diff-check passed.
- Current SHA256: `commands.py` `1bd6f5307a8832432a2f433dd789ee486ce0be3222aabbc54be727507170ab8f`; `command_python.py` `d081a8f3a0670d52444fd51a8b6335e0d3bfa294eee227b1ba870e045c91cfce`; `test_command_replay_policy.py` `1a3d5878041c6f2f213d3461af4e79830b005210d5f39b25626e2d11baada144`.
- P2-3 remains in progress. Shared checkout remains dirty; whole-suite/release gates stay deferred.

## Update — 2026-11-11 (Round 1 P2-3 safe-value propagation)

- Moved the existing five-pass AST safe-value propagation loop into `PythonInlineCodeSafety`; assignment, annotated, named-expression and for/async-for targets preserve old handling.
- Four test-first cases failed before implementation; the focused classifier pair passed **98 in 2.93s** afterward. Pyflakes, py_compile and diff-check passed.
- SHA256: `commands.py` `8b980ca02039219326586b5142abf5130c63b2e7e5d43dd5c0aaea24a88e9a17`; `command_python.py` `ef853ccac8d4d46a59baefee2b44c80403d563828b0f1ec4444b748719d9df26`; `test_command_replay_policy.py` `977a5979b64df983ec28ce8d853265a42c76f8a7a93fd11cf783a5221650d5c3`.
- P2-3 stays open. CASE134 used four calls and completed PARTIAL/NOT_VERIFIED because host-visible raw schema and tool outputs are absent. Broad gates remain deferred.


## Update — 2026-11-11 Round 94: practical evals and Stability handoff

- CASE131: isolated thread `01a1cbda-3df2-7ab2-9821-3678cc96201c`, two ordered completed calls. `refactor_impact` and `call_graph` used alpha fixture and `demo_core.paths::normalize_path`; second call used limit 5 and depth 1. Raw MCP payloads are absent. Agent-reported impact and graph outputs conflict on callers and remain **PARTIAL / INCONSISTENT / NOT_VERIFIED**. Cross-project, suffix-collision and duplicate-definition branches remain **NOT RUN** because fixtures were absent.
- CASE135: isolated thread `01a1cbd7-6c33-79a1-b9ae-e132948b578d`, one completed `reachability_dead_code` call with alpha fixture and `limit=1`. Transcript confirms protocol and arguments only; raw payload absent. Agent-reported counts remain **NOT_VERIFIED**; protocol only PASS.
- C08/C09/C13 handoff sent to the identified active Stability thread `01a1c762-d599-75c2-ae34-344aae056aa0` (title `Read pasted goal instructions`). It includes source paths, current gaps and requested ownership/validation acknowledgement. No Stability-owned code or tests edited; acknowledgment pending.
- Latest results addendum SHA256: `3a185535570579efbe777bf7fcb311749199783402fba045987fa69098a53d98`. Focused P2-3 evidence remains 98 classifier tests passed, plus pyflakes, py_compile and diff-check. No full suite/release checks run; shared checkout remains dirty.

## Update — 2026-11-11 Round 95: Python `-c` classifier extraction

- Extracted `classify_python_inline_code` into `command_python.py`; `CommandBroker` delegates from the same Python interpreter branch.
- Added six direct policy cases. Test-first: all six failed on the absent helper, then passed after extraction. Focused classifier pair: **104 passed in 2.97s**; targeted pyflakes, py_compile and diff-check passed.
- SHA256: `commands.py` `a60525b5c775d2a9060d859e2e14e1b7f12828d396213646ac06ea9c7f143937`; `command_python.py` `a99ea5d6d4a4deae4f8c7a82b9e04a73f6d36b20bf80589a5223e1d885323405`; test `43d9b4ce2d7e5ec78b13affa75ea0537c79affad690be5574e7082830443f50b`.
- P2-3 remains in progress. Tree remains dirty; broad gates and acceptance remain open.

## Update — 2026-11-11 Round 96: script classifier and CASE132 gate

- Extracted Python script invocation classification into `classify_python_script_command`; eight direct policy cases failed before implementation and passed after. Focused classifier pair: **112 passed in 3.82s**. Targeted pyflakes, py_compile and diff-check passed.
- SHA256: `commands.py` `6342d21875f88be321f2da124af4837bf98e3f92dd4a18c8d0138d71b112d324`; `command_python.py` `4eece165ad8057c3106379a16ed8b312a307773f2d14e6bd4c6f3d884e75528a`; test `0ea660fa835f9d3563e48014e23b922ec968e87dd6fc71f625eff081c8b20fe4`.
- CASE132 full prompt remains **NOT RUN / NOT VERIFIED**: complete enum, fixture/manifest inputs, exact patch branches and test target were not supplied. Current path search found no CASE132-named fixture/manifest; earlier branch-level evidence does not satisfy the prompt-wide six-action gate. No case action was run.
- Shared tree remains dirty. P1-5/P1-6, Stability integration and broad gates remain open.

## Update — 2026-11-11 Round 97: C11 verification

- Rechecked C11 static PHP/C# named-export validation against current source/test hashes. tests/test_static_exports.py: **11 passed in 0.38s**; direct T6-11 regression: **1 passed in 0.37s**; targeted pyflakes passed.
- C11 focused acceptance evidence is current. C08/C09/C13 remain with Stability; P1-5/P1-6 and whole-round gates stay open.

## Update — 2026-11-11 Round 98: shared hubctl classifier

- Added `classify_hubctl_command` to `command_python.py`; both Python-script and native `hubctl` paths use the same policy function. Added seven direct policy cases and three native broker integration cases.
- Test-first helper checks initially failed because the shared helper did not exist. After extraction, the helper cases passed; the full focused `tests/test_command_replay_policy.py` run passed **102 tests in 13.81s**. Targeted `py_compile`, pyflakes, and `git diff --check` passed; diff-check emitted only a line-ending normalization warning for the test file.
- SHA256: `commands.py` `a853bcf1b8883d9324ee93b3500b9e0e670ad2ed7c1ab4ba699835a73bda2e34`; `command_python.py` `cd78cf9d46103fcb601a1a63f2c8c68fd94ae6c276d083692c399c7dc9a8ae3a`; test `7a81fbd120e422b3472eb90baf626d57c14a9ec3532c5540c14e83d399ba2822`.
- P2-3 remains in progress. C08/C09/C13 remain with Stability; P1-5/P1-6 and broad gates remain open pending required evidence and a stable shared snapshot.

## Update — 2026-11-11 Round 99: CASE134 retest

- Two initial isolated retries were non-passing: one used start_line/end_line; one stopped after the status call. The prompt now explicitly requires canonical line_start/line_end and continuing all source reads after a successful status.
- Latest GPT-6 Luna Low chat 01a1cc1b-eae7-72e3-9f71-b4c85f1099fe confirms one status plus three correctly bounded source calls, exact root/path/SHA and no target actions. Raw source/status payloads and artifact request IDs are absent; live enums are not host-visible.
- CASE134 remains PARTIAL / NOT VERIFIED. Prompt SHA 5d2c883d2d26bb7b49ada9e2fca10787a0f62b51c7f0545e4fffdf1a102098c4. C08/C09/C13 remain with Stability; P1-5/P1-6 and broad gates remain open.

## Update — 2026-11-11 Round 100: CASE135 endpoint output

- Direct call `req_4031a94abc97`: `reachability_dead_code`, fixture `docs/agent-evaluation/fixtures/alpha`, `limit=1`, compact profile. Raw output reports 15 total symbols, 4 reachable, 7 dead, 4 ambiguous; one unreachable symbol returned, `complete=false`, domain `truncated=true`, transport truncation false.
- This is direct endpoint evidence for the fixture. CASE135 isolated transcript still lacks raw payload; overall prompt acceptance remains NOT VERIFIED. P1-5/P1-6 and broad gates remain open.

## Update — 2026-11-11 Round 101: CASE131 direct endpoint output

- Replayed the exact `refactor_impact` and `call_graph` arguments from the existing isolated transcript in the coordinating chat. This is direct endpoint evidence, not a new isolated prompt pass.
- `refactor_impact` request `req_3f6d7fc64410` returned zero callers and `risk_level=UNKNOWN`; coverage is incomplete because freshness was not checked.
- `call_graph` request `req_3b1caf2fdf19` found `load_project` at `src/demo_core/consumer.py:5`, but coverage remains incomplete because qualified-symbol scope is unresolved and PHP is unsupported. Freshness is not_checked; top-level truncated=true while response-budget truncated=false.
- CASE131 overall prompt acceptance stays NOT VERIFIED. Cross-project and collision-fixture branches remain NOT_RUN.

## Update — 2026-11-11 Round 102: CASE132 readiness gate

- Direct `local_ai_status` request `req_ae618f26ab52` used `detail=brief`, compact profile, no token cap. Hub online, model `qwen2.5-coder:3b`, GPU admission available, VRAM nominal.
- `capabilities.code_generation.available=false`, reason `disabled_in_mcp_adapter`; provider readiness is `not_checked`. This is a readiness/adapter exposure result, not generation proof.
- Generation stayed GATED/NOT_RUN; full CASE132 prompt acceptance remains NOT VERIFIED because harness inputs and isolated raw evidence are missing.

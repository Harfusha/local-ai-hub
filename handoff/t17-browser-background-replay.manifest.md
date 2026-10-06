# T17 browser commit replay handoff

Owner: T17. The master plan assigns `browser_bridge/background.js` to T17 browser acceptance. This patch changes only commit response handling: retry a commit once with the same idempotency request ID after an ambiguous transport/server failure; preserve `commit_outcome_unknown` when retry cannot establish a terminal result.

- Candidate checkout: `C:\Users\Adam\.codex\worktrees\t17-multimodal-resume\.local-ai-hub`
- Candidate HEAD: `2b33602adef0d030fea66cdcc04ca742c60b2e32`
- Patch path: `handoff/t17-browser-background-replay.patch`
- Patch SHA-256: `AD515B5536784845269017D9F5763B06E89703DFFCB5E6460C76006599A72FCA`
- Changed path: `browser_bridge/background.js`
- Base blob in candidate and root: `a10a1e1b5b459139f13ed4b90c0ac344ddb7f58d`
- Root HEAD: `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`

Pre-integration validation:

- `git -C C:\Users\Adam\.local-ai-hub apply --check --whitespace=nowarn <patch>`: passed.
- Existing root fixture + root `capture.js` + root `background.js`: failed at dropped-commit-response success assertion (exit 1).
- Same root fixture and capture with patched T17 `background.js`: passed (exit 0); fixture reported success and 16 acceptance cases.
- Candidate runtime pytest: `python -m pytest -q --tb=short tests/test_browser_bridge_runtime.py` -> 1 passed in 10.38s.
- Exact 16-node T17 suite after fixture update -> 247 passed in 73.79s.

Root integration recheck (2026-09-29):

- Integrator applied the browser source patch and the harness regression. Current root HEAD remains `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`.
- Live root blob hashes match candidate targets: `browser_bridge/background.js` `57f239913afd0ffb9f95f65efc69c28d7d87a52c`; `tests/fixtures/browser_bridge/current_tab_harness.js` `a2845490993730a9185388a32e07bd27aa667bf0`.
- Rechecked `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_browser_bridge_runtime.py tests/test_browser_bridge.py tests/test_browser_artifact_atomicity.py` in root -> 38 passed in 13.82s.
- That exact file selection includes `tests/test_browser_bridge_runtime.py::test_actual_current_tab_fixture_preserves_login_and_never_falls_back`; it passed after both integrated root blobs matched the candidate targets above.
- Receipt difference is revision timing: the earlier RED used the modified harness with pre-integration root `background.js` (base blob `a10a1e1...`) and failed the lost-response assertion. Post-integration root uses replay blob `57f2399...`; the same acceptance node passed. No test rerun was needed for this reconciliation.
- Root `git diff --check` is clean; Git emitted its usual LF-to-CRLF notice for `background.js`.
- Root writes came from integrator, not this worker. I only inspected current root state and ran tests.

Remaining release gates: real Chrome/Edge acceptance, multilingual WER corpus, and live vision quality. No model inference ran.

External gate recheck (2026-09-30; read-only, no test reruns):

- Requested `8085\.local-ai-hub` checkout remains missing; only empty worktree parent exists. This worker checkout is `t17-multimodal-resume` at `2b33602...`.
- Current root master plan still has T17 criteria unchecked at lines 354-365.
- Chrome and Edge executables exist, but no real-browser acceptance ran; temporary-profile approval remains unanswered.
- `whisper.exe`, cached `tiny.pt` (75,572,083 bytes) and `base.pt` (145,262,807 bytes) exist. No labeled multilingual audio corpus or audio fixture was found under `tests`.
- Ollama lists vision models, but `/api/ps` is empty; no model is loaded. Previous vision inference reset its connection; no retry/load attempted.
- Existing receipts remain the only test evidence: root browser slice 38 passed in 13.82s; candidate T17 suite 247 passed in 73.79s. Neither was rerun this check.
- Candidate command: `python -m pytest -q --tb=short tests/test_t17_auxiliary_formats.py tests/test_generate_mocks_and_multi_lang.py tests/test_feature_surface_parity.py tests/test_preprocessor_and_deterministic.py tests/test_browser_bridge.py tests/test_browser_bridge_runtime.py tests/test_browser_artifact_atomicity.py tests/test_http_vision_routes.py tests/test_vision_service.py tests/test_vision_contracts.py tests/test_transcription_contract.py tests/test_auxiliary_action_policy.py tests/test_speculative_draft_and_split.py tests/test_architectural_extensions.py::test_deterministic_generate_types tests/test_missing_and_high_value_features.py::test_deterministic_generate_dataset_and_profile_digest` -> 247 passed in 73.79s.
- Historical receipt for the identical command on 2026-09-23: exit 0, 204 passed in 29.78s; command and output verified in the raw rollout log.
- Browser UI blocker: the computer-use skill requires `node_repl`; that tool is absent from this task's available toolset. No shell-based UI automation was substituted.

Offline generation acceptance (2026-09-30):

- Found one missing case in the previous 16-node T17 selection: it did not include the completion-routing contract suite or test speculative draft failure/syntax-invalid outcomes.
- Ran `python -m pytest -q --tb=short tests/test_speculative_draft_and_split.py tests/test_completion_model_routing.py tests/test_cloud_model_accelerators.py::test_task_scaffold tests/test_t17_auxiliary_formats.py` -> 21 passed in 2.32s.
- Added `test_speculative_draft_failures_never_run_or_claim_validation`: provider failure returns failure/unvalidated; syntax-invalid Python stays a draft/unvalidated; neither reaches affected-test selection or command execution despite `verify_tests=true`.
- Test-only root-compatible delta: `handoff/t17-speculative-draft-failure-acceptance.patch`, SHA-256 `a259675b2d64e54eafff456df019d7e1081ad8449bf147b8b62ac70499959317`; source base blob `412ced79e954104651a58512caa0460bdfb1a0f6`. Root `git apply --check` passed; no root writes or root test run. Candidate scoped diff-check is clean.
- `complete_code` failure/empty, task scaffold, auxiliary deterministic formats, and speculative draft validation gating were covered by this 21-test command. This is contract coverage, not model-quality proof.
- The candidate's dirty `mcp_server.py` contains unrelated MCP changes from other owners. Isolated only T17's transcribe language-forwarding hunk plus its explicit/auto regression test in `handoff/t17-audio-language-forwarding.patch`, SHA-256 `F584136923D1B640F51CE5E9BF3F604C56CE6D0102495B97D3035A9BDB9D8B45`. Root-base blobs: MCP `a6dd1223bf397250529090e459523be771c79382`, test `ce041ee2b6edab32671c877de97490499bf2b007`; root `git apply --check` passed. No root writes or tests this turn. Earlier candidate receipt: the isolated two-case MCP language regression passed in the 2-pass focused run.
- T02 currently owns CPU for a 100k/100k CodeIndex benchmark with inference disabled; no T17 tests were started while it remains active.
- Benchmark-overlap correction from orchestrator (2026-09-30): the focused 21-test command above completed while T02 PID `112472` still held the benchmark slot. Keep its observed functional result, but do not treat timing/resource-isolation as independent T17 evidence. Do not rerun until T02 exits and T20 releases the hold.
- Candidate tracked diff inventory at HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32`: `browser_bridge/background.js`; `src/local_ai_hub/frontend_review.py`, `mcp_server.py`, `services.py`, `vision_contracts.py`; `tests/fixtures/browser_bridge/current_tab_harness.js`; `tests/test_browser_bridge.py`, `test_browser_bridge_background.js`, `test_cloud_model_accelerators.py`, `test_completion_model_routing.py`, `test_frontend_coder_context.py`, `test_frontend_review.py`, `test_http_vision_routes.py`, `test_mcp_agent_routing.py`, `test_missing_and_high_value_features.py`, `test_speculative_draft_and_split.py`, `test_transcription_contract.py`, `test_vision_artifacts.py`, `test_vision_contracts.py`, `test_vision_service.py`.
- This inventory is not a wholesale integration patch: MCP contains mixed owner hunks, and `services.py` is shared/dirty. Apply only owner-reviewed narrow handoffs. T17-specific MCP transcribe forwarding is isolated in the patch recorded above; no schema or repository-context hunk is included.

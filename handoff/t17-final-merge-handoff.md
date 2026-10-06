# T17 merge-ready handoff

## Worktree and integration state

- Candidate: `C:\Users\Adam\.codex\worktrees\t17-multimodal-resume\.local-ai-hub`
- Candidate HEAD: `2b33602adef0d030fea66cdcc04ca742c60b2e32` (detached; source changes remain dirty, no commit created).
- Root/master was not written by this T17 worker. Integrator already applied the root-compatible deltas listed below.
- `/api/context/pack` is outside scope; no diff hunk there.

## T17 owned paths

**Browser bridge**
- `browser_bridge/background.js`
- `tests/fixtures/browser_bridge/current_tab_harness.js`
- `tests/test_browser_bridge.py`
- `tests/test_browser_bridge_background.js`

**Audio**
- `src/local_ai_hub/mcp_server.py` — `local_ai_task(action="transcribe")` language forwarding.
- `src/local_ai_hub/services.py` — `LocalAIServices.transcribe()` only for transcription behavior; `LocalAIServices.vision()` only for vision request/parser integration.
- `tests/test_mcp_agent_routing.py` — transcription language forwarding.
- `tests/test_transcription_contract.py`
- `tests/test_missing_and_high_value_features.py` — audio/no-Whisper regression hunk only.

**Vision and frontend review**
- `src/local_ai_hub/vision_contracts.py`
- `src/local_ai_hub/frontend_review.py`
- `tests/test_vision_contracts.py`
- `tests/test_vision_service.py`
- `tests/test_http_vision_routes.py`
- `tests/test_vision_artifacts.py`
- `tests/test_frontend_review.py`
- `tests/test_frontend_coder_context.py`

`services.py` is shared/dirty. Do not transfer whole file; keep to `transcribe()` and the authorized `vision()` parser/schema hunks. No change touches `/api/context/pack`.

## Root integration artifacts

- `handoff/t17-browser-malformed-commit-response.patch` — SHA-256 `3BEACA147A1A9CE123A20B694EEDCC22D0E345BD8F1AA062B57CDD1921B3D305`; reverse-apply check passes (already integrated).
- `handoff/t17-root-browser-malformed-fixture.patch` — SHA-256 `540095DA12B4EE9EF3016DFF3173E08F978BBB171913797393BB6DB3267F9324`; reverse-apply check passes (already integrated).
- `handoff/t17-vision-strict-shape-root-compatible.patch` — SHA-256 `299F438AA20FD2B1599CCFCB3BF30E17A587B8A88DE7AB6F2A3C4DD6223A3ACB`; root apply-check and post-integration reverse-check pass. Patch changes only `src/local_ai_hub/vision_contracts.py`, `src/local_ai_hub/services.py`, `tests/test_vision_contracts.py` (28 insertions, 1 deletion).
- `handoff/t17-browser-background-replay.patch` — SHA-256 `AD515B5536784845269017D9F5763B06E89703DFFCB5E6460C76006599A72FCA`; historical base patch, current root implementation contains replay/ambiguous-result helpers. Do not reapply stale patch.
- `handoff/t17-browser-commit-replay.patch` — SHA-256 `0A7F0AE180502D0212EB84072A9E2F29C1B562DAD65641076A84D9DC04D3A596`; historical fixture revision; current root has later fixture changes. Do not reapply stale patch.
- `handoff/t17-audio-language-forwarding.patch` — SHA-256 `F584136923D1B640F51CE5E9BF3F604C56CE6D0102495B97D3035A9BDB9D8B45`; root already has equivalent forwarding; do not reapply.
- `handoff/t17-transcribe-stderr-decode-skip.patch` — SHA-256 `A1EBBD13E3DF014922F4B08B836EA0D33FBB4F1EEECFDD5F0670F9450E276B1C`; root already has equivalent decode-skip behavior; do not reapply.

- `handoff/t17-transcribe-stderr-root-current.patch` — SHA-256 `B976A325E5B77D42740AD0CF65CACE7E43F06CE8B0D183224A13CF67F685F2CB`; current-root apply-check passes. Adds stderr decode-skip handling and regression coverage; files: `src/local_ai_hub/services.py`, `tests/test_transcription_contract.py`. Both root files are dirty; do not apply without owner coordination. No tests run.
- `handoff/t17-vision-schema-prompt-root.patch` — SHA-256 `E23BDA5CC0545AFF79E7EAB5875AEFD0211C8987F27A281EBB2B9B8A89B840EE`; root `git apply --check` passes. Adds Ollama default observation schema and image-grounding prompt rules; root regression test not run in reserved T20 selector slot. Supersedes schema-only patch below.
- `handoff/t17-vision-default-schema-root.patch` — earlier schema-only patch; superseded by schema+prompt patch above.
- `handoff/t17-frontend-zero-dom-id-root.patch` — SHA-256 `B1E8A6A5D92473DE787038ADBA9439538D5EF5085215758E055260D75152FB6A`; root `git apply --check` passes. Fixes numeric-zero DOM ID filtering while retaining root's broader `nodes` and mapping support; adds regression test. Test not run in reserved root validation slot.
- Root `LocalAIServices.vision()` callsite already passes `model_context.observation_sources` into `parse_vision_result()`; no additional source edit needed for that authorization.
## Verification receipts

- Candidate audio/vision: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_transcription_contract.py tests/test_vision_contracts.py tests/test_vision_service.py tests/test_http_vision_routes.py tests/test_mcp_agent_routing.py::test_local_ai_task_transcribe_forwards_only_explicit_language_hint` — **141 passed**, 16.97 s.
- Candidate browser/runtime/frontend review: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_browser_bridge.py tests/test_browser_bridge_runtime.py tests/test_frontend_review.py tests/test_frontend_coder_context.py` — **58 passed**, 12.28 s.
- Candidate extra audio/artifact regressions: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_missing_and_high_value_features.py::test_audio_transcription_service_without_whisper_is_not_false_success tests/test_vision_artifacts.py::test_mcp_binary_artifact_response_is_metadata_only` — **2 passed**, 2.38 s.
- Root strict-shape/grounding selectors — **6 passed**, 0.80 s.
- Root expanded browser/runtime/frontend/audio/vision acceptance — **174 passed**, 46.64 s. Exact command is preserved in `handoff/t17-vision-strict-shape-root-integration.md`.
- T20 later reserved the overlapping transcription/vision selectors for its own root slot; T17 did not rerun them after that reservation. The 174-pass root receipt above remains the T17 result.
- A direct `node --test tests/test_browser_bridge_background.js` invocation was invalid: this helper requires source-path and case arguments. Its supported pytest wrappers passed in the 58-test candidate suite.

- Fresh candidate aggregate run after checkpoint — **201 passed**, 35.45 s. Command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_browser_bridge.py tests/test_browser_bridge_runtime.py tests/test_frontend_review.py tests/test_frontend_coder_context.py tests/test_transcription_contract.py tests/test_vision_contracts.py tests/test_vision_service.py tests/test_http_vision_routes.py tests/test_mcp_agent_routing.py::test_local_ai_task_transcribe_forwards_only_explicit_language_hint tests/test_missing_and_high_value_features.py::test_audio_transcription_service_without_whisper_is_not_false_success tests/test_vision_artifacts.py::test_mcp_binary_artifact_response_is_metadata_only`.
- Fresh candidate auxiliary-format suite — **7 passed**, 1.49 s. Command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t17_auxiliary_formats.py`; covers rules, deterministic JSON/CSV/SQL, pstats/Chrome trace/text profile parsing, recognized-format rejection, Python and TypeScript mocks/types.
- Live audio smoke: cached Whisper `base.pt`, Windows SAPI voices Microsoft David Desktop (`en-US`) and Microsoft Jakub (`cs-CZ`); no download. `whisper <temp.wav> --model base --model_dir C:\Users\Adam\.cache\whisper --device cpu --language en|cs --task transcribe --output_format txt --output_dir <temp> --fp16 False --verbose False` succeeded for both. Synthetic reference `The red door is open. Please press the blue button.` => exact transcript, WER 0% (0/10). Synthetic reference `Červené dveře jsou otevřené. Stiskněte modré tlačítko.` => `Červené dveře jsou otevřené. Skiskně temodré tlačítko.`, WER 28.6% (2/7). Temp audio/output removed. This is short synthetic-TTS smoke only; no recorded multilingual fixture/reference exists in repo, so real-speech WER acceptance remains open. Chrome and Edge executables exist; read-only process/title inspection found one Chrome window titled `127.0.0.1 - Google Chrome`, no Edge window. Computer Use skill requires `node_repl` + `@oai/sky`; tool inventory exposes neither, and no Browser Use control tools. Only browser-adjacent tool is `mcp__codex_app__open_in_codex`, which displays a tab but cannot inspect/control it. Chrome process arguments showed no `--load-extension` or `--remote-debugging-port` flags (does not rule out store-installed extensions). Therefore existing tab/extension and accessibility tree could not be inspected safely; no browser was launched, no extension installed, and no UI changed. Extension/tab/navigation/expiry/accessibility acceptance remains open.
- Live vision smoke: invoked candidate `LocalAIServices.vision()` with actual `OllamaRuntime` on `http://127.0.0.1:11434`, cached `qwen2.5vl:3b`, and temporary synthetic UI image (`Profile Settings`, blue `Save changes` button). No Hub route/download. Runtime returned `success=false`, `error_code=vision_output_invalid`, nested `malformed_vision_output`, message `finding element_ids must exist in the supplied DOM`, `terminal=true`, `retryable=false`. Parser failed closed on model-emitted unsupported DOM ID despite the active prompt explicitly requiring empty `element_ids` and image-pixel `bbox` when no DOM is supplied; no grounded live result achieved. Temp image removed. Backend transport worked; grounding quality remains a blocker. A distinct cached `qwen2.5vl:7b` follow-up was deferred: preflight detected an active shared-host pytest process and aborted before Python/model execution.
- Candidate worktree unchanged by tests (`python -B`, `no:cacheprovider`). T20 was notified that candidate-only selectors ran and root remained untouched; no root test slot consumed.
## Excluded inherited dirty scope

- `src/local_ai_hub/services.py::complete_code()` hunk and `tests/test_completion_model_routing.py` are code-completion behavior, not T17 browser/vision/audio. Preserve for its owner; exclude from this handoff.
- `tests/test_cloud_model_accelerators.py` and `tests/test_speculative_draft_and_split.py` are separate dirty scope. `handoff/t17-speculative-draft-failure-acceptance.patch` (SHA-256 `A259675B2D64E54EAFFF456DF019D7E1081AD8449BF147B8B62AC70499959317`) is forward-applicable but was not part of T17 multimodal selectors; route to its owner before integration.

## Remaining live acceptance

Automated pytest and Node fixture/harness evidence plus synthetic local Whisper and vision smoke. Real Chrome/Edge extension lifecycle, visual capture, accessibility tree, and recorded-speech multilingual WER remain unverified; vision inference reached cached Ollama backend but failed grounding contract. No model downloads or user-local config access performed.
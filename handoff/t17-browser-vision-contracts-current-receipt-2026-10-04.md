# T17 Browser/vision contracts current receipt

Date: 2026-10-04. Source-only. No source edit, patch application, test, or benchmark in this checkpoint.

## Candidate baseline and ownership

- Assigned candidate: `C:\Users\Adam\.codex\worktrees\t17-multimodal-resume\.local-ai-hub`
- HEAD: `2b33602adef0d030fea66cdcc04ca742c60b2e32`
- Owned Browser/vision contract paths remain dirty: `browser_bridge/background.js`, `tests/test_browser_bridge_background.js`, `src/local_ai_hub/frontend_review.py`, `tests/test_frontend_review.py`, `src/local_ai_hub/vision_contracts.py`, `tests/test_vision_contracts.py`.
- Mixed-owner `src/local_ai_hub/services.py` remains untouched in this checkpoint; worktree SHA-256 `A3C9C6DBAE5ACFAAC1D543F02783EDA4FBBC89F7991D9870F849972F7224F0C0`, 438 additions / 40 deletions already present.
- Current task authorization permits only prior `transcribe()` and the vision parser callsite in `services.py`. No 734-line vision refactor.
- No lease receipt was available in the assigned checkout; HUB is ignored per user direction. No source edit was made.

## Patch and root preimage receipt

- Patch: `handoff/t17-browser-vision-contracts-root-current.patch`
- SHA-256: `675FA73C00808E3D40387314272F72EAAE414CF14D67C8E91DF0AA32B2A68DC7`
- Root checkout: `C:\Users\Adam\.local-ai-hub`, HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
- Root `services.py` SHA-256: `58908C5C718A520463171B7890C0B8E1E7F7CC54D5EF62F9809BE707EFC173FE`; patch has no service hunk.
- Root `vision_contracts.py` SHA-256: `048DD7EA1A464401CBE7A8FCE421CB07711763809BD7A177EA40FB196ED18F6C`.
- `git apply --check` against current root: exit 0. Patch remains unapplied.
- Candidate `git diff --check` for owned target paths: exit 0; Git reports existing LF-to-CRLF notices.

## Acceptance gate

- Exact focused acceptance selectors and command are in `handoff/t17-browser-vision-contracts-root-current-2026-10-03.md`.
- Tests: NOT RUN in this checkpoint; T20 GO absent. No test result is claimed.
- `/api/context/pack` remains excluded.

## T17 browser / vision / transcription contract acceptance update — 2026-10-04

Candidate-only continuation. No Hub calls and no root edits. Existing passing targeted commands were not repeated; only the four failures below were rerun after their fixes.

### Candidate identity and scoped changes

- Worktree `C:\Users\Adam\.codex\worktrees\t17-multimodal-resume\.local-ai-hub`; detached HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32`.
- This acceptance continuation changed `src/local_ai_hub/http_server.py` and one fake-commit response in `tests/fixtures/browser_bridge/current_tab_harness.js`. The fixture was already dirty; only the T17 stub response echoing `request_id` is claimed here. Other dirty paths remain inherited or scoped to prior work; no whole-file ownership is claimed.
- HTTP response behavior: when the caller supplied a valid visible-ASCII `X-LocalAI-Request-ID` (1–128 chars) and the response map did not already have `request_id`, echo it. Existing body-provided IDs keep precedence; requests without the header keep existing response shapes.
- Browser harness stub now echoes the commit payload's request ID, matching `background.js`'s existing successful-commit binding check.
- Post-change SHA-256: `src/local_ai_hub/http_server.py` `AEE2773B59116BBEA187EDD644D6F5ACA769D3B389DA231E32AB66AC24F88405`; `tests/fixtures/browser_bridge/current_tab_harness.js` `63196C77F87735BEEB994E7B6375FE27B6EA6D885CC4312018D0AE7609FC119D`.

### Acceptance evidence

- Before the fixes, the first run of `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_http_vision_routes.py tests/test_vision_artifacts.py tests/test_browser_bridge_runtime.py` exited 1: 4 failed, 23 passed in 27.56s. Three failures exposed missing HTTP response `request_id`; the browser fixture's fake commit response omitted the request ID.
- After the fixes, exact failed-selector rerun:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_http_vision_routes.py::test_browser_capability_capture_and_review_routes_are_explicit_and_tenant_scoped tests/test_http_vision_routes.py::test_token_auth_supports_bridge_and_review_preflight_without_wildcard_origin tests/test_vision_artifacts.py::test_http_binary_artifact_get_returns_complete_payload tests/test_browser_bridge_runtime.py::test_actual_current_tab_fixture_preserves_login_and_never_falls_back
```

Exit 0; 4 passed in 20.50s.
- Candidate adjacent browser/vision checks: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_browser_artifact_atomicity.py tests/test_dashboard_vision_review.py` — exit 0; 13 passed in 0.64s.
- Earlier candidate receipts remain valid and were not repeated: `tests/test_vision_service.py` — 65 passed in 4.07s; `tests/test_vision_contracts.py tests/test_frontend_review.py tests/test_browser_bridge.py tests/test_process_utils.py tests/test_transcription_contract.py` — 171 passed in 6.45s. The bridge JS wrapper is exercised through `test_browser_bridge.py`; direct invocation of its helper without required arguments is not a valid test command.
- Scoped `git diff --check` returned 0; Git printed only its existing LF-to-CRLF normalization warning for the fixture.
- No root files or root tests touched in this continuation.

### Runtime limits

- Browser DOM/current-tab harness is simulated. It does not verify installed-extension permissions or the production daemon/browser connection. Prior headless Edge adapter evidence used a fake API.
- Prior real local vision smoke failed acceptance (model output lacked required `hypothesized` field / quality issue); live vision quality is not accepted.
- Prior Whisper receipt covers only generated synthetic English (15 reference words, 0 errors). Natural and multilingual WER remain unverified.
- Browser/vision/transcription contract tests now pass at these candidate hashes. Overall live browser/model/speech acceptance remains open.

## T17 browser / vision / audio / profile matrix — 2026-10-04

### Owned patch

- Only owned delta from this acceptance continuation: `handoff/t17-contract-acceptance-owned.patch`.
- SHA-256: `6706F6CFA91DB55431F92D0FF2424B6C3674249B3CE3898706FA169A1C2A6AAB`.
- Contains exactly two hunks: safe echo of explicit request IDs in `Handler._send()` and the browser harness's fake successful commit response echo. `git apply --reverse --check handoff/t17-contract-acceptance-owned.patch` exited 0 against the candidate worktree; patch remains unapplied as a separate artifact because its exact edits are already present.
- No `/api/context/pack` hunk, no root file, no unrelated inherited changes included.

### Browser and vision contracts

- Candidate browser/vision/route/artifact checks: previously failing route/runtime selectors now **4 passed in 20.50s**; adjacent artifact atomicity and dashboard review modules **13 passed in 0.64s**.
- Earlier current-candidate vision service module: **65 passed in 4.07s**.
- Earlier current-candidate contracts group (`vision_contracts`, frontend review, browser bridge, process utilities, transcription contract): **171 passed in 6.45s**. Those passing modules were not repeated after the HTTP-only/fake-response changes.
- Harness results are simulated. Prior Playwright/headless-Edge adapter run used a fake API, so installed-extension permissions and production daemon/browser behavior remain unverified.
- Prior live vision smoke used the actual cached local vision model and failed acceptance: output was rejected for an unsupported DOM ID. Runtime transport worked; model grounding/quality did not pass.

### Audio contracts and runtime quality

- Current candidate `tests/test_transcription_contract.py` hash: `FA73A2967BDC8088BD03E81943B8909EA5A095F97822EA29B8980E1BB34D263D`; included in the 171-pass run. Candidate `services.py` hash: `8CEC8C8F041195622642C2F52962F97176CAB251BB8A57D7F9B7909CC5A9B83C` (mixed-owner file; T17 transcription scope remains `transcribe()` only).
- Candidate MCP language-forwarding selector and no-Whisper failure regression were included in prior candidate aggregate receipts: 201 passed overall, with `test_local_ai_task_transcribe_forwards_only_explicit_language_hint` and `test_audio_transcription_service_without_whisper_is_not_false_success` present. These completed selectors were not repeated.
- Prior real local Whisper CPU/SAPI smoke: synthetic English exact, WER 0/10; synthetic Czech WER 2/7 (28.6%). This is generated short-form speech only. Natural/multilingual speech acceptance remains open.

### Profile contracts

- Current `src/local_ai_hub/deterministic.py` SHA-256: `4363A1B07630DCB3DBAC6C62325A7570A8E11FF639132E64D278960ACA55D070`; no worktree diff. Current `tests/test_t17_auxiliary_formats.py` SHA-256: `A8D4A66102C18FA1E8F40687008BFB34F9A6B475F57120D238B3BF091A373A01`; clean.
- Previously completed candidate profile/auxiliary suite: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t17_auxiliary_formats.py` — **7 passed in 1.49s**, including repeatable JSON-compatible cProfile digest and Chrome trace/text profile parsing.
- A separate prior candidate aggregate also included `tests/test_missing_and_high_value_features.py::test_deterministic_generate_dataset_and_profile_digest`. Profile code and the auxiliary profile test file are unchanged, so these completed profile selectors were not repeated.

### Candidate code pins and state

- Candidate remains detached HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32`.
- New owned code pins: `src/local_ai_hub/http_server.py` `AEE2773B59116BBEA187EDD644D6F5ACA769D3B389DA231E32AB66AC24F88405`; `tests/fixtures/browser_bridge/current_tab_harness.js` `63196C77F87735BEEB994E7B6375FE27B6EA6D885CC4312018D0AE7609FC119D` (only the listed fake-response hunk is owned here).
- Source contract acceptance is supported by the candidate test receipts above. Runtime browser integration, live vision quality, and natural-speech WER remain separate open gates. No new tests were run while writing this receipt.

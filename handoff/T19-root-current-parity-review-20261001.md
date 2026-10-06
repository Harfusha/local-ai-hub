# T19 Root-Current Parity Review — 2026-10-01

Root checkout: `C:\Users\Adam\.local-ai-hub`  
Observed root `HEAD`: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`  
Candidate `HEAD`: `2b33602adef0d030fea66cdcc04ca742c60b2e32`

## Existing root coverage and overlap

- `docs/INSTALL_PROMPT.md`, `docs/UPDATE_PROMPT.md`, and `AGENTS.md` already contain the candidate's exact T19 profile-routing paragraphs. The two prompt paragraphs are byte-identical to each other and to the candidate.
- Root `tests/test_t19_prompt_profile_parity.py` already contains `test_install_prompt_balanced_routes_match_profile_and_update_prompt`. Its first 67 lines match candidate; they include updated balanced/high/max prompt assertions and response-budget checks.
- Root does not contain candidate symbol `test_agents_profile_routes_match_hardware`. This is the only missing hunk from the T19 parity test.
- Root `tests/test_release_contract.py` already has `test_release_has_compact_mcp_surface_and_tool_first_policy`, which checks CodeGraphContext absence from Hub runtime/instructions and checks standalone installation wording. Its `test_no_personal_paths_or_runtime_payloads_in_tracked_release_sources` skip set already contains `handoff`, `dist`, and `build`.
- Therefore old `handoff/T19-prompts-release-contract-current-root.patch` is stale against root's dirty files. Its docs/AGENTS hunk is already present; parity edits overlap completed root assertions; the release skip hunk is already present. Do not apply old patch.

## Focused hunk for review

`handoff/T19-root-current-parity-hunk-20261001.patch` contains only the missing `test_agents_profile_routes_match_hardware` addition to root's existing untracked parity test file. It is prepared for T20 review; it has not been applied or checked against root.

Focused hunk SHA-256: `85143747215e307288641a906f987e36bfcb7b1f51e3f214fd7e04e195a9aae9`. Static boundary comparison confirmed root's 67 existing parity-test lines match candidate's first 67 lines; the candidate-only test is absent from root.

Root had uncommitted changes in `AGENTS.md`, both prompt docs, `tests/test_release_contract.py`, and untracked `tests/test_t19_prompt_profile_parity.py`. Root remained untouched during this review. No tests or builds were run. Candidate parity tests are not root proof.

The original five-path patch SHA-256 is `1fe2c919221ff8954ab8e7d5866474a0089846339c2b6ae4ccbb0968a65b6fec`; its `git apply --check` against the observed root returned exit code `1`, with failures on both prompt docs, the parity test, `AGENTS.md`, and `tests/test_release_contract.py`.

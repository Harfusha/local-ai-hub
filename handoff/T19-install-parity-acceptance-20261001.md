# T19 installer/SDK parity acceptance handoff — 2026-10-01

## Scope and baseline

- Worktree: `C:\Users\Adam\.codex\worktrees\t19-docs-rollout\.local-ai-hub`
- Candidate preimage HEAD: `2b33602adef0d030fea66cdcc04ca742c60b2e32`.
- Candidate already contained dirty and untracked T19 files before this continuation; no pre-edit file hashes were recorded. Preserve all other worktree hunks.
- Root stayed untouched. Root HEAD observed: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.

## Changes

- `tests/test_t19_install_contracts.py`: added a dry copy/install fixture in `tmp_path`. It checks portable example TOML key support against defaults, source/package defaults equality, version metadata, package manifest declarations, default feature and policy prompt parity, profile model names, generated schema set/action enums, and exact generated policy output.
- `tests/test_t19_parity_contract.py` and `tests/test_release_contract.py`: replaced stale hard-coded profile assertions with checks against `profile_overrides` for the four supported profiles.
- `docs/T19_CLEAN_HOST_INSTALLER_CYCLE.md`: added an explicitly **NOT RUN** Windows/Linux reinstall/uninstall procedure bounded to a disposable VM/account and unique scratch paths.
- `docs/T19_RELEASE_VALIDATION_RUNBOOK.md`: linked the procedure and states that installer lifecycle remains unverified.

## Validation

Exact command:

```text
python -B -m pytest -q -p no:cacheprovider tests/test_t19_install_contracts.py tests/test_t19_packaging_contract.py tests/test_t19_sdk_docs.py tests/test_t19_sdk_wrapper_payloads.py tests/test_t19_parity_contract.py tests/test_t19_prompt_profile_parity.py tests/test_feature_surface_parity.py tests/test_surface_and_packaging.py tests/test_release_contract.py
```

Result: **58 passed in 17.25s**, exit 0. Fixtures write only under pytest `tmp_path`; SDK wrappers mock transport. Loopback SDK/MCP scenarios, clean-host installs, network access, user config/vault changes, and root tests were not run.

## Clean-host gate

Still open. The procedure documents bounded future commands and receipts; it is not evidence that Windows/Linux install, reinstall, or uninstall passed. T20 must record results on one frozen integrated candidate.

## SHA-256 postimages

- `tests/test_t19_install_contracts.py`: `B70BFB014653F6C21DF71A85F817FA9A94194BCC4E898C2D8FF0F80638B74928`
- `tests/test_t19_parity_contract.py`: `0779508B2E0CA9DACC71E2DFABE9A9373CFC61869C028428E870E573E9C6A427`
- `tests/test_release_contract.py`: `363AE387064B68F475C8800058BF95F0234E45B8AA47056B14E4055C276FFD38`
- `docs/T19_RELEASE_VALIDATION_RUNBOOK.md`: `948A6E826F0944478CA586298D47861140D4291E93F858B03984DF9BD7874700`
- `docs/T19_CLEAN_HOST_INSTALLER_CYCLE.md`: `80F7DDE7A9F75A6E56E97BA9D53CA75674A7D78E0B5E7FBCF88FE23FE6F1EF24`
- Existing root-current prompt patch: `handoff/T19-feature-profile-parity-root-current-20261001.patch`, `919BB3AF5E74777998A6E6FC6FE04E75063D371AAD5DF7EB0B1752ACA589EEF6`.

## T21 prompt contract synchronization (2026-10-01)

Updated the T19 `INSTALL_PROMPT.md`, `UPDATE_PROMPT.md`, generated orchestrator skill contract, and parity regression test to reflect current T21 documentation. Removed stale claims that project configuration and PathHint core are drafts/unshipped. Documented exact-criterion `verification_rules`, the HTTP completion gate and its still-open broader acceptance matrix, shared namespace limits, candidate-preserving hint ranking, and adapter boundaries: HTTP `/api/search` supports hints; `/api/command` strips them; private MCP dispatch forwards internally; the public `local_ai_repo` schema remains T03-owned; `/api/context/pack` does not accept hints.

The parity test first failed against the stale contract, then passed after synchronization. Targeted parity module: **4 passed**. Full previously approved T19 contract suite: **58 passed in 19.15s**, exit 0. `git diff --check` passed; Git emitted only LF-to-CRLF working-copy notices for the two prompt files.

Clean-host install/reinstall/uninstall remains **NOT RUN**; release gate stays open.

Postimage SHA-256:
- `src/local_ai_hub/generator.py`: `CDB600C3CF34711601E5E15F0A94286F952F1A89681BE5B24302E0E6CCB865EE`
- `tests/test_t19_parity_contract.py`: `E874CC14DDAD445758ABD825A973F8C960E27240C65B6C7DBD0404FDD0B5B5EC`
- `docs/INSTALL_PROMPT.md`: `78A50FBDC09264C15232B20FC9A9472E52A3DE3838D2E1A21B30DCE00052555D`
- `docs/UPDATE_PROMPT.md`: `D905E0039CF6A1734F2964B092ED831F70871B00825ACC8EA2CA61CC03AB1DA2`

## Installed schema / offline mode / Agent OS parity (2026-10-01)

Added a T19 runtime contract shared by `docs/INSTALL_PROMPT.md`, `docs/UPDATE_PROMPT.md`, and generated orchestrator skill. It requires the installed `tools/list` input/output schema, documents `hubctl pause=gaming` and `resume=active` including offline persisted-state behavior without starting the server, requires resuming durable tasks with the same `task_id`, and documents root provenance for repository-scoped memory plus the one-bounded-attempt native fallback. The parity regression requires these statements in both canonical prompts and generated skill. CodeGraph remains absent from prompts/generated skill, as required by the existing release contract; its standalone guidance stays in installation documentation.

Test-first evidence: the new parity assertions failed before the contract was added. Final targeted command `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t19_parity_contract.py`: **4 passed in 0.14s**, exit 0. Final full T19 command already recorded above, repeated after this change: **58 passed in 20.63s**, exit 0. `git diff --check` passed. `git apply --reverse --check handoff/T19-runtime-parity-contract-20261001-v2.patch` passed.

Immutable patch: `handoff/T19-runtime-parity-contract-20261001-v2.patch`, SHA-256 `1AF91DDD23DCBFD6ED3FC9C29AAA4A24346832D509E8D5CAA1652BBF7D9771F3`. Reconstructed preimages matched recorded hashes before creating the patch:
- `src/local_ai_hub/generator.py`: `CDB600C3CF34711601E5E15F0A94286F952F1A89681BE5B24302E0E6CCB865EE`
- `tests/test_t19_parity_contract.py`: `E874CC14DDAD445758ABD825A973F8C960E27240C65B6C7DBD0404FDD0B5B5EC`
- `docs/INSTALL_PROMPT.md`: `78A50FBDC09264C15232B20FC9A9472E52A3DE3838D2E1A21B30DCE00052555D`
- `docs/UPDATE_PROMPT.md`: `D905E0039CF6A1734F2964B092ED831F70871B00825ACC8EA2CA61CC03AB1DA2`

Postimage SHA-256:
- `src/local_ai_hub/generator.py`: `0358A5F3BE0815A60592E35FE28509B280A8863B24A6A0A7D9D361E2FB694515`
- `tests/test_t19_parity_contract.py`: `12673F889CAE3A015AA9D2558ACBFC0CBE0C86A3AF221A69DD4E435BEE3521C0`
- `docs/INSTALL_PROMPT.md`: `6EC6B55A08EEE0E552346DB6526BBCBA08D887CDC44145A1432ABB2652854AF8`
- `docs/UPDATE_PROMPT.md`: `4B40839C25891B00A704A1178D20C2343D41FB0F0F08422D39DE186807AB3D3C`

No root files, live Hub, network, installer, daemon, or user profile were touched. Clean-host install/update/uninstall remains **NOT RUN** and the T19 release gate remains open.

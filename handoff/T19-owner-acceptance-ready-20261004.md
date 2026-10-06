# T19 owner acceptance packet — 2026-10-04

## Ownership and baseline

- Assigned T19 checkout for this continuation: `C:\Users\Adam\.codex\worktrees\t19-docs-rollout\.local-ai-hub`.
- HEAD: `2b33602adef0d030fea66cdcc04ca742c60b2e32` (detached).
- The checkout contains inherited dirty work across runtime, installer, tests, prompts, docs, and handoff. Preserve all unrelated hunks. Do not use `55ed`; it is absent.
- Root: `C:\Users\Adam\.local-ai-hub`, HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
- T19 v3 docs packet is already integrated in root. Do not reapply: `handoff/T19-root-current-install-docs-packaging-20261003-v3.patch`, SHA-256 `8d2970b6ed9b24f8148c49710d3dd18d7e44dd7ac96626e047726bb50e39a3a3`.
- Root LF postimage hashes match v3 receipt for INSTALL_PROMPT, UPDATE_PROMPT, PYTHON_SDK, T19_CLEAN_HOST_INSTALLER_CYCLE, and T19_RELEASE_VALIDATION_RUNBOOK. Scoped `git diff --check` passed earlier.

## Prompt policy decision

Candidate prompts contain later dirty hunks that differ from v3. They include stale/conflicting tier-policy prose. Root `router.py::apply_model_override` enforces the routed model quality floor. Root `generator.py::generate_global_policy` still emits config-derived tier prose. T12 reports a generated-policy contract mismatch in AGENTS.md. Hold the T12 prompt-only patch until T12 reconciles generator and generated policy at one revision. Keep the v3 root prompts, role matrix, and quality-floor claim as current baseline; do not copy candidate-only prose into root without source/test receipt.

## Prepared bounded root selectors — not run

Run only under a fresh one-shot T20 serial GO, after verifying all pinned preimages and zero active root pytest processes. Do not retry or add selectors.

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t19_prompt_profile_parity.py::test_install_prompt_balanced_routes_match_profile_and_update_prompt tests/test_t19_codegraph_removal.py tests/test_codegraph_package_policy.py tests/test_release_contract.py::test_release_metadata_and_documentation_are_current tests/test_release_contract.py::test_release_docs_match_stable_defaults_and_ci_gate
```

These cover prompt profile parity, absence of CodeGraph Hub integration plus optional standalone recommendation, and release docs. No root selector has run for this packet. T20 canceled the earlier one-shot GO before execution.

## Remaining acceptance gates

- Clean-host install, same-version reinstall, uninstall, rollback, persistent service restart, and cross-version update each need their own T20-approved slot and revision-bound artifact receipt.
- Compare sdist SHA-256 with T20 receipt; use frozen source SHA and clean checkout. Keep package-index/network restrictions from `T19_CLEAN_HOST_INSTALLER_CYCLE.md`.
- Keep service/MCP runtime evidence separate from `--skip-service` clean-host cycle. Do not claim installation or runtime acceptance without receipts.
- Current T20 slot is selecting T02 after T16 released; T19 slot requested, no GO received in this packet.
- No tests, builds, installs, or root writes performed for this packet.
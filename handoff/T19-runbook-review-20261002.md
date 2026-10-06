# T19 rollout runbook review — 2026-10-02

## Scope and result

Reviewed the release-validation and clean-host installer procedures in the T19 candidate. The release runbook now labels v7 as historical, binds future validation to T20's frozen revision and artifact hashes, and requires an explicit T20 serial-slot assignment before clean-host or pytest work. The clean-host cycle remains `NOT RUN` and has the same frozen-revision/slot boundary. Historical receipt templates and gate snapshots are identified as reference only; current receipts must bind the frozen candidate.

Static check of `tools/setup.py` confirmed the documented setup options exist: `--profile`, `--skip-model-pull`, `--skip-local-nlp-preload`, `--skip-tools`, `--skip-agent-config`, `--skip-service`, `--skip-ollama-install`, `--skip-token-economy`, `--skip-companion-skills`.

## Root-current artifacts

- Candidate HEAD: `2b33602adef0d030fea66cdcc04ca742c60b2e32`
- Root HEAD: `01df56605ccf484ebfe2808ac60d696c4e81dffc`
- `docs/T19_RELEASE_VALIDATION_RUNBOOK.md` SHA-256: `1ceebde91205d2274ac8fc8ee29e30cc644306de1f98e45e368147106ac67a2a`
- `docs/T19_CLEAN_HOST_INSTALLER_CYCLE.md` SHA-256: `9e6bd37411ec8fbbe33f249047e7c812eaff618445bcfb9693c674e2b3600b64`
- New additive root-current runbook patch: `handoff/T19-release-validation-runbook-root-current-v2-20261002.patch`; SHA-256 `255902ac43475c56a66be060a65d01149dd146caa565b0894151a7a15874c03d`
- Existing additive root-current clean-host patch: `handoff/T19-clean-host-installer-cycle-root-current-20261002.patch`; SHA-256 `52e4edb28489cb5dfd89124bef14a0d9b5112bfe2a6058aae2323c095e759440`
- Both patches passed `git apply --check --whitespace=nowarn` against the root checkout. Neither patch was applied. Root source files remain untouched by this review.
- T20 later integrated both patches after fresh preimage/hash checks. Root `core.autocrlf=true` converted LF to CRLF; normalized bytes match the candidate docs. Reported root working-tree SHA-256 values: release runbook `53EC31AA3F646308C21C0F5101123880B583513597389F5B32E8BC5541972D63`; clean-host cycle `A037DAE1D9942C76F15B7F0801F647E9FC5879B74B9E41D206D308432A0AD49A`. Both apply-checks passed.

## Suggested lightweight selectors — not run

```text
pytest -q \
  tests/test_release_contract.py::test_release_metadata_and_documentation_are_current \
  tests/test_release_contract.py::test_release_uses_only_current_local_ai_hub_contracts \
  tests/test_release_contract.py::test_canonical_prompts_share_profile_and_installation_docs_own_standalone_setup \
  tests/test_release_contract.py::test_release_docs_match_stable_defaults_and_ci_gate \
  tests/test_release_contract.py::test_update_prompt_uses_branch_safe_pull_and_generated_artifact_wording \
  tests/test_release_hardening.py::test_release_hygiene_allows_managed_installed_directories \
  tests/test_release_hardening.py::test_release_hygiene_still_rejects_build_outputs
```

No tests, builds, package installs, or clean-host procedures were run. T20 slot remains required before validation.

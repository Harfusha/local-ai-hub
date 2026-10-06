# T19 Root Import Receipt — 2026-10-01

Status: **READY FOR T20 IMPORT; NOT APPLIED**.

## Import target

- Observed root `HEAD`: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.
- Patch: `handoff/T19-prompts-release-contract-current-root.patch`.
- SHA-256: `1fe2c919221ff8954ab8e7d5866474a0089846339c2b6ae4ccbb0968a65b6fec`.
- Patch includes `docs/INSTALL_PROMPT.md` and `docs/UPDATE_PROMPT.md`, plus `AGENTS.md`, `tests/test_t19_prompt_profile_parity.py`, and `tests/test_release_contract.py`.

## Read-only checks

- `git -C "$MASTER" apply --check --verbose "$PATCH"`: exit 0; all five file patches checked.
- `git -C "$MASTER" apply --stat "$PATCH"`: 5 files, 21 insertions, 7 deletions.
- Candidate `git diff --check` for the scoped source/docs files: exit 0.
- Prior scoped candidate parity run: 2 passed. Command:
  `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t19_prompt_profile_parity.py::test_install_prompt_balanced_routes_match_profile_and_update_prompt tests/test_t19_prompt_profile_parity.py::test_agents_profile_routes_match_hardware`
- No tests or builds ran during this receipt turn.

## Import handoff

T20 owns root integration. Re-run `apply --check` if root `HEAD` or any of the five target files changes. Apply this exact patch only after T20 selects the integration point; preserve existing root changes. Do not rebuild sdist or wheel before integration freeze.

The v7 package artifacts predate these prompt changes. Clean-host Windows/Linux receipts remain pending; see `docs/T19_RELEASE_VALIDATION_RUNBOOK.md`. Import readiness does not establish release acceptance.

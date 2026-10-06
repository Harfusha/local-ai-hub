# T19 feature/profile prompt parity receipt — 2026-10-01

## Scope

Prepared a documentation-only patch for the T19-owned `docs/INSTALL_PROMPT.md` and `docs/UPDATE_PROMPT.md`. No foreign source, config, test, or user-local files were changed. No tests, builds, clean-host installs, or user configuration changes were run.

## Evidence

- `config.toml.example:93` enables `local_diagnostic_dispatch = true` in the shipped feature profile.
- `src/local_ai_hub/defaults.toml:548` also enables the feature in defaults.
- `src/local_ai_hub/features.py:91` reads that feature into `FeatureSet`.
- The two prompts previously described diagnosis as disabled by default, contradicting the installed default profile and their own rollout-control summary.
- `docs/MODEL_CAPABILITIES.md` profile matrix remains aligned with the checked-in hardware profile mapping; no model profile text changed in this patch.

## Change

Both prompts now say diagnosis is not automatic, acknowledge the enabled installed default, and preserve the one-diagnosis gate: low-confidence deterministic command parsing, an artifact reference, and a narrow preview; never raw logs. Existing prohibitions on architecture, security, mutations, and open-ended coding remain.

## Patch and checks

- Patch: `handoff/T19-feature-profile-parity-20261001.patch`
- SHA-256: `FF05E7DA62111ADF24F017CA266AEA51F118C84415FE73053852786E2218309C`
- `git apply --stat`: parsed successfully; exactly two files and one line replacement per file. Reverse applicability was not verified; do not treat this as an apply receipt.
- Tests/builds: not run; assigned to T20 integration/validation.

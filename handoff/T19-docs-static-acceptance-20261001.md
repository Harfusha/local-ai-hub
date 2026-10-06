# T19 Documentation Static Acceptance — 2026-10-01

## Scope and ownership

Candidate checkout: `C:\Users\Adam\.codex\worktrees\t19-docs-rollout\.local-ai-hub`; candidate `HEAD`: `2b33602adef0d030fea66cdcc04ca742c60b2e32`.
Root checkout `HEAD` observed: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`

Reviewed T19-owned documentation: `docs/INSTALLATION.md`, `docs/INSTALL_PROMPT.md`, `docs/UPDATE_PROMPT.md`, and `docs/T19_RELEASE_VALIDATION_RUNBOOK.md`. `docs/MODEL_CAPABILITIES.md` supplied the profile-routing comparison. Ownership snapshot `handoff/T19-worktree-ownership-20261001.md` assigns the prompt docs and installation docs to T19; `AGENTS.md` and `tests/test_release_contract.py` are shared files with only specific T19 hunks. No other owner files were edited.

The `docs/INSTALL_PROMPT.md` and `docs/UPDATE_PROMPT.md` profile paragraphs match byte-for-byte. Integrated, balanced, high, and max model rows match `docs/MODEL_CAPABILITIES.md`. CodeGraphContext is documented as optional standalone tooling, outside Hub dependencies, backends, setup, and fallback. Release runbook maps Python 3.11–3.14 to Windows launchers, Linux executables, and `py311`–`py314` environment tags.

## Static validation

Exact command: `powershell -NoProfile -File handoff/T19-docs-static-check-20261001.ps1`; result: exit code `0`.

Selected output (command also printed the four file hashes listed below):

```text
PASS prompt parity, four profile rows, standalone CodeGraphContext contract, four Python/tag rows
PASS trailing whitespace scan on four T19 documentation files
PASS git diff --check on tracked install and prompt docs
```

The runbook's frozen-source test/build command pack remains prepared, not run. No tests or builds were executed. The post-T01 focused selector, when T01 releases the inventory seam, is:

```text
python -B -m pytest -q tests/test_t19_coverage_owner.py::test_context_pack_get_remains_assigned_to_t01_in_generated_coverage
```

## Root patch handoff

Patch: `handoff/T19-prompts-release-contract-current-root.patch`; SHA-256: `1fe2c919221ff8954ab8e7d5866474a0089846339c2b6ae4ccbb0968a65b6fec`.

Exact patch paths:

- `docs/INSTALL_PROMPT.md`
- `docs/UPDATE_PROMPT.md`
- `tests/test_t19_prompt_profile_parity.py`
- `AGENTS.md` (shared file; T19 profile-routing hunk only)
- `tests/test_release_contract.py` (shared file; T19 release-content hunk only)

Exact read-only check: `git -C 'C:\Users\Adam\.local-ai-hub' apply --check 'C:\Users\Adam\.codex\worktrees\t19-docs-rollout\.local-ai-hub\handoff\T19-prompts-release-contract-current-root.patch'`.
Observed result: exit code `1`; patch does not apply to current root working tree. Git reported failed hunks in both prompt docs, the parity test, `AGENTS.md`, and `tests/test_release_contract.py`. Root already has uncommitted changes in the same five paths; its prompt routing paragraphs currently match the candidate paragraphs. No root files were changed. Do not import this patch as-is; T20 must reconcile against its current edits and re-run the check.

## Candidate SHA-256

| Path | SHA-256 |
| --- | --- |
| `docs/INSTALLATION.md` | `ec275e8ede2dbe8a24ed4f795ad9cba8a7815fd89e7790e08ab516cc7a3ede38` |
| `docs/INSTALL_PROMPT.md` | `43834d3fd976332b4b5c9fef0c3e735bb48d08648ec41df03801761193861737` |
| `docs/UPDATE_PROMPT.md` | `10938b6809187b7767843ccbd5b0aef3959f530f290388da76f55ec934da2b5a` |
| `docs/T19_RELEASE_VALIDATION_RUNBOOK.md` | `2c060ad97d90b2bdb5187b090b06a00e54a27bd58a73ed00cf4e4311572dd8b8` |
| `handoff/T19-docs-static-check-20261001.ps1` | `4ba7c6e68b30d34c3ad7a3e3f6613c968a0da0e373423ea3006b3c4dfe1eb70a` |

This is source/documentation evidence only. Clean-host package acceptance, T08 recovery, and T20 integrated release acceptance remain open.

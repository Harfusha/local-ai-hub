# T21 producer-only coordination identity

Owner: orchestrator. Candidate: `C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub`, HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`.

## Owned delta

- `src/local_ai_hub/project_config.py`: only `ProjectContext.coordination_id` property (12 inserted lines). Reuses existing hint identity salted by git-common directory and shared namespace; does not substitute a filesystem root. Invalid configuration returns `None`.
- `tests/test_t21_coordination_identity.py`: five producer cases covering linked worktrees, different repositories/namespaces, non-Git roots, invalid UTF-8 and no additional state writes during property access.
- No memory/lease consumer edit. No new store/hash. No context pack edit. Inherited candidate project_config changes are excluded from this patch.

## TDD and verification

Initial producer test command:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t21_coordination_identity.py
```

RED: **5 failed in 2.16s**, missing `coordination_id` AttributeError. After implementation a combined run reported **101 passed, 2 failed in 7.94s**: tests incorrectly asserted constructor had never created state. Candidate existing store constructor eagerly initializes DB; root constructor differs. Tests now snapshot after constructor and compare before/after identity read, preserving the no-additional-I/O requirement.

Final candidate command:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t21_coordination_identity.py tests/test_project_config.py tests/test_project_path_hints.py tests/test_project_config_worktrees.py
```

**103 passed in 8.01s**, exit 0. AST parse: 2/2. `git diff --check` for both owned files: exit 0.

## Root handoff

- Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.
- Root `project_config.py` preimage SHA-256: `6050453FA90C83F0282C4DD2588CAC4454B5187F9C85521CF7AABF089E41C832`.
- Patch: `handoff/T21-coordination-identity-root-current.patch`.
- Patch SHA-256: `36DE4284FF1704E5B030DE0D9B76405F75C9C2FF45AAF2360A08129BC5B98D1D`.
- Root `git apply --check <absolute patch>`: exit 0, no root edits/tests performed by orchestrator.
- T20 owns review, integration and root producer test command above. Candidate success is not root proof.

## Remaining acceptance

Root integration receipt inspected from T20's actual command output: `python -B -m pytest -q -p no:cacheprovider --tb=short -c pyproject.toml tests/test_t21_coordination_identity.py tests/test_t21_real_namespace_identity.py` — **6 passed in 1.80s**, exit 0, cwd `C:\Users\Adam\.local-ai-hub`. T20 applied the producer and real-worktree test-only patch after SHA checks. This supersedes earlier pending-root statements for these two test files only; memory/lease consumer acceptance remains open.

Additional test-only patch: `handoff/T21-real-worktree-identity-test.patch`, SHA-256 `75A48A6511D3BBADF2252655927D603FF0041EF2FF3D497C6D1F1D59BF9E094A`; root apply-check exit 0. Adds `tests/test_t21_real_namespace_identity.py` with real temporary Git repositories and a detached linked worktree, no Git-common mocks. Shared inherited namespace yields equal producer IDs, unrelated repository with the same alias differs, local namespace override differs, physical roots stay unchanged. All Git calls bounded at 10 seconds and hidden via existing process helper; only test-owned tmp fixtures change.

Candidate command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t21_real_namespace_identity.py` — **1 passed in 3.12s**, exit 0. `git diff --check` exit 0. This is separate from the earlier 103-test run, not a combined 104-pass receipt. Root test still belongs to T20.

T08 owns memory consumer boundary, T16 owns lease/fencing boundary. Both prepare scoped tests/proposals before production bridge changes. Automatic memory/lease sharing is still **not implemented** by this producer property alone. Memory tenant privacy, physical-worktree task/branch scopes and lease tenant-as-owner conflicts must remain distinct. T21 remains active; not done.

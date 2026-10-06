# T21 project_config resolver handoff to T11 — 2026-10-05

Status: source-only candidate packet. T21 checkout read; root and T11 checkout untouched. Patch contains exactly one path: `src/local_ai_hub/project_config.py`.

## Candidate identity

- Worktree: `C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub`
- Branch: `codex/t21-project-config`
- Base HEAD: `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`
- Inherited/other dirty state was preserved; no shared consumer files included.

## Exact source patch

- File: `handoff/T21-project-config-resolver-t11-20261005.patch`
- SHA-256: `56A7E21E936FD6E04525909F7F3104353DF95BE35EB1E3BAE63C4A19DA198A30`
- Bytes: `16,635`
- Diff stat: `src/local_ai_hub/project_config.py | 260 +++++++++++++++++++++++++++++-------` (`212 insertions`, `48 deletions`).
- Base file SHA-256: `03145095FAC22F7A69454069D0C41B5206AC2C78A0508CF6C924339D0FD26D5E`
- Candidate postimage SHA-256: `088B8AFDF05A331E51C74925884B2B7984DF8BD5E3AD227C82DBDBEEB19289A1`

Patch is the exact `git diff --binary HEAD -- src/local_ai_hub/project_config.py` bytes from this candidate. It was not applied to root or T11.

## Test receipt

Parent-reported T21 focused suite at the same candidate HEAD:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_project_config.py tests/test_project_config_worktrees.py tests/test_project_config_service_integration.py tests/test_t21_project_config_preprocess.py tests/test_project_path_hints.py tests/test_mcp_repo_path_hints.py tests/test_client_path_hints.py
```

Observed result reported by parent: `138 passed in 8.30s`. Not rerun here; no duplicate suite. This receipt is candidate test evidence, not T11/root acceptance.

## Ownership boundary

T21 supplies only the resolver module patch above. T11/root owner decides integration. No root/T11 files changed. `/api/context/pack` and T14 files untouched. No claim of production/runtime acceptance.

## Packet verification

`git apply --stat -- handoff/T21-project-config-resolver-t11-20261005.patch` reported exactly one changed path and `212 insertions, 48 deletions`; patch SHA matched the in-memory candidate diff fingerprint.
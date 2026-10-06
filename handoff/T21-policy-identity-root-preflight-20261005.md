# T21 project policy identity preflight — 2026-10-05

Status: verified candidate behavior; no root-current source patch emitted. T21 test artifacts already cover the requested resolver identity and cross-worktree policy. The reported missing method is T11-owned RAG code, not a missing T21 project-config API.

## Checkout and preimage pins

- T21 candidate: `C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub`, branch `codex/t21-project-config`, HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`.
- Shared root: `C:\Users\Adam\.local-ai-hub`, branch `master`, HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
- Both HEADs have identical `project_config.py` base blob SHA-256 `03145095FAC22F7A69454069D0C41B5206AC2C78A0508CF6C924339D0FD26D5E`.
- Root current `project_config.py` SHA-256 `00E80B1342E5E70A66FA8955D95553127E913F56EC693CF527B6AC96053BDBDE`; candidate postimage SHA-256 `088B8AFDF05A331E51C74925884B2B7984DF8BD5E3AD227C82DBDBEEB19289A1`.
- Candidate diff vs HEAD: 212 insertions/48 deletions; root diff vs HEAD: 209 insertions/44 deletions. Both files are dirty.

## Ownership and patch decision

T21 `ProjectContext.coordination_id` / project namespace resolver API is already present in both root-current and candidate. T21 regression tests already cover same Git-common identity, distinct namespace/repository separation, non-Git root isolation, real linked worktree inheritance, and path-hint namespace policy.

T11 reports the failing root test is `tests/test_rag_hybrid.py::test_rag_index_paths_step_retries_publish_lock_without_reembedding`: root RAGStore lacks `_sync_workspace_project_policy_identity`; candidate T11 RAG code implements it. That helper lives in T11-owned `src/local_ai_hub/rag.py`, reads T21 context fields `config_digest` and `settings.max_file_size_bytes`, and consumes T11 adapter policy helpers. T11 reports no missing T21 resolver API. T21 made no rag.py edit.

Root-current `project_config.py` and T21 candidate postimage differ in 13 hunks (read-only diff fingerprint SHA-256 `08B1DAD7F21FEF6DC8D13C70A6A636F85CC0A4037EA4015E6FCC0BE9B7AAB8C7`). Differences include `_connect(ensure_schema=...)` read-only schema behavior and path-policy normalization changes. Per-hunk ownership is not proven, so no root-current production patch is safe to emit. The candidate-only resolver patch from the earlier T11 handoff remains candidate-relative; its HEAD preimage is not the dirty root-current file.

No `/api/context/pack` or T14 file was changed. No root file was written. No patch was applied.

## T21 regression evidence

Candidate test files:

- `tests/test_t21_coordination_identity.py`, SHA-256 `81C784CD187FAB272FA98832B0BC29215B263ACE40A7098509C08257602B7A88`.
- `tests/test_t21_real_namespace_identity.py`, SHA-256 `EAE3684702C17CF621E079133B7EA62CC2A4DD5C5DE73229988867C4AF4D76BF`.

Exact command run once in the T21 candidate:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t21_coordination_identity.py tests/test_t21_real_namespace_identity.py::test_real_git_worktree_namespace_is_inherited_but_unrelated_repo_is_not
```

Observed: **6 passed in 1.33s**, exit 0. This run covers actual coordination identity, invalid-config isolation, linked worktree inheritance, and unrelated repository separation.

Parent-reported broader T21 focused receipt remains **138 passed in 8.30s**, not rerun here. T11's `test_rag_hybrid.py::test_rag_index_paths_step_retries_publish_lock_without_reembedding` root failure / candidate pass is owner-reported, not executed by T21.

## Next owner action

T11/root owner integrates or repairs `_sync_workspace_project_policy_identity` in T11-owned RAG scope. T21 can provide resolver API contract and passing identity tests; T21 does not change root or T11 production files.
# T11 root-current RAG correction packet — 2026-10-05

Status: candidate changes validated; immutable patch checked against current shared-root preimages and not applied. Local AI Hub tooling ignored as requested. Root workspace remains read-only for this work.

## Scope and identity

- Candidate: `C:\Users\Adam\.codex\worktrees\f678\.local-ai-hub`, HEAD `3c7da92aa6a267c2a18af0555d927f0e67d4c476`.
- Shared root: `C:\Users\Adam\.local-ai-hub`, HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
- Patch: `t11-root-current-owned-fixes-20261005.patch`, SHA-256 `2B4414C59987691CF5A41D7DED9E249A85C68C513431FC7F44A2B8A70EC66633`, 29,625 bytes.
- Paths: `src/local_ai_hub/rag.py` and `tests/test_rag_hybrid.py` only.
- Root preimages: `rag.py` SHA-256 `9328914E6D09EA6E88FB035FA7A8FD13779FEC564188B0016E1710B73E0F14CC`; test SHA-256 `038A15AA053CC75DEC69B8216D754508C75B9D1B721ACE5159D9963E9FD3737E`.
- Proposed postimages: `rag.py` SHA-256 `B162AC451953E0FCB3A9549EFA2A66CD500A8EEB0892FB931194E5EF5B269CC6`; test SHA-256 `1FD09F7AB94C1945984B96891803B49239B28E83B9BF700181C685C935ADE8DD`.

## Corrections

1. Recheck the current project-policy root and digest before and during persistence; compare-and-swap prevents an older concurrent scan from committing or deleting newer state.
2. Treat only `ENOENT` and `ENOTDIR` as confirmed missing paths. Permission and transient stat errors mark uncertainty, return retryable failure, and do not advance the digest or prune indexed rows.
3. Bind a workspace to one canonical root and include root identity in the policy digest key, preventing one root from pruning another root's rows.
4. Retain prior T11 fixes: embedding-space retry/persistence, published-path pending counts, and policy-aware prune behavior.

Added deterministic regressions cover stale concurrent snapshots, `EACCES`/`EIO`, confirmed missing files, and cross-root workspace reuse. No assertions were weakened. T21 `project_config.py` and its consumer tests are excluded; no project-config files are in this patch.

## Validation evidence

- Candidate new policy regressions: `6 passed`.
- Candidate focused prior plus policy regression selectors: `17 passed`.
- Candidate wider RAG/embedding suite: `185 passed, 1 skipped, 2 deselected in 56.22s`; skip requires `T11_REAL_OLLAMA=1`, and two benchmark selectors were excluded.
- Root-current `git apply --check --recount --whitespace=error`: PASS, patch not applied.
- Root-current `git apply --stat`: exactly the two paths above; 504 insertions, 8 deletions.
- Python syntax compile of both synthetic root postimages: PASS. Root tests were not run.
- Root `rag.py` and test preimage hashes rechecked unchanged after packet creation; root writes by this task: 0.

Patch and receipts are ready for owner review. T21 config remains separate and must use its owner packet; do not apply any config changes from this packet.

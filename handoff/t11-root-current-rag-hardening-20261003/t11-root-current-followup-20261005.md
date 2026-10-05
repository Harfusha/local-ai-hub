# T11 root-current follow-up — 2026-10-05

Status: owner-only follow-up packet. Root patch v1 remains applied by the root owner; this packet is checked against current root postimages and is not applied by this task. Root files were read-only here.

## Patch identity

- Root: `C:\Users\Adam\.local-ai-hub`, HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
- Candidate: `C:\Users\Adam\.codex\worktrees\f678\.local-ai-hub`, HEAD `3c7da92aa6a267c2a18af0555d927f0e67d4c476`.
- Patch: `t11-root-current-followup-20261005.patch`, SHA-256 `FF3F5B62BC16CE721503F0905743DED3574233AD0741981BDE955C0B5546530C`.
- Scope: `src/local_ai_hub/rag.py`, `tests/test_rag_hybrid.py`, `tests/test_rag_fragment_cache.py`, `tests/test_t11_rag_ingestion_contract.py` only.
- Root apply-check: PASS (`git apply --check --recount --whitespace=error`); not applied. Four synthetic postimages compile.

## Exact root hashes

| Path | Preimage SHA-256 | Proposed postimage SHA-256 |
|---|---|---|
| `src/local_ai_hub/rag.py` | `B162AC451953E0FCB3A9549EFA2A66CD500A8EEB0892FB931194E5EF5B269CC6` | `D7235A0FE32CD9549E1581C7530836F78392BC7331AE74F3592C37BFC9355342` |
| `tests/test_rag_hybrid.py` | `1FD09F7AB94C1945984B96891803B49239B28E83B9BF700181C685C935ADE8DD` | `833B366DE3C1141B69C946D365933CB86BCAC9A05D83C9F4FCEFD621460E7CA8` |
| `tests/test_rag_fragment_cache.py` | `F5641D678EDAD903E64BA13E2E360E04C297F2BB23FFEF987152498C9024EADF` | `71706EABACABD2AA9B8FE20DAA173069E63837E942DFFC6B055F0C85254B2590` |
| `tests/test_t11_rag_ingestion_contract.py` | `9710F1846DE6D35CF9D8045EC8D7DF3663488FC94C479AE41BAF1A20DF614294` | `1B6230D2AB67EF44776FB0F2330107FBB944F33869BBF685469DFDDCBF216321` |

## Reconciled failures and fix

- RAG path: reuse a stored embedding space when runtime identity is unresolved; return the identity; clear orphan FTS rows on fingerprint reset; normalize CRLF before chunking across all indexing entrypoints; route uncertain-only commits through the retry helper; bound vector batches by configured size and a memory budget; reuse the norm buffer for scores; report non-busy indexing exceptions as non-retryable.
- T11 regressions: import `Path`/`os` required by the added tests. Keep assertions intact.
- Ingestion contract tests: filter only `/api/rag/ingest_document` and `/api/rag/ingest_diagram` requests before asserting explicit payloads. Root MCP also emits `/api/telemetry/tool-accounting`; no T14 production file is changed.
- Current root `embeddings.py` SHA-256 is `B80C15DEBB62724BB20113E86324B8268C685A1076D5508A22BBF4246FEA07E0`; it changed during concurrent root work and is not part of this patch. Stable targeted root run afterward: `tests/test_embedding_cache.py` **17 passed / 0.24s**.
- Root `reranker.py` SHA-256 `EE8B660C9FA261EA34FB63587F8EAAF6119B83B544A4053D22669EF8D9C5C562` matches candidate; no missing T11 hunk found.
- `mcp_server.py` and `services.py` differ from candidate and include the telemetry request; both remain outside T11 patch scope.

## Validation receipts

- Candidate targeted follow-up selectors, including the full fragment-cache module, vector buffer/batch tests, policy-stat/publish-lock regressions, FTS atomicity, and explicit-ingest contracts: **36 passed / 12.36s**.
- Candidate broader RAG/embedding suite previously: **185 passed, 1 skipped, 2 deselected / 56.22s**; live Ollama skip requires `T11_REAL_OLLAMA=1`; benchmark selectors excluded.
- Root pre-patch diagnostics: fragment cache **6 failed, 22 passed / 23.78s**; vector batch/buffer **3 failed, 1 passed / 2.67s**; hybrid policy **3 failed / 1.21s**; ingestion targeted **4 failed / 6.50s**. Failures correspond to the root deltas listed above.
- A broad root run reported **17 failed, 147 passed, 1 skipped, 2 deselected / 66.20s** while `embeddings.py` changed concurrently; treat it as diagnostic, not a single-preimage acceptance receipt. The stable embedding-cache rerun passed 17/17.
- Root writes by this task: 0. No `project_config.py`, `mcp_server.py`, or `services.py` changes.

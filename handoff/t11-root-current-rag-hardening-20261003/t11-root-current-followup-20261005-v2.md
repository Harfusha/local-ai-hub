# T11 root-current follow-up v2 — 2026-10-05

Status: owner-only packet; root was not modified. This supersedes `t11-root-current-followup-20261005.patch` and its report, whose `rag.py` preimage is stale after concurrent root changes. The original owned-fixes packet remains as previously integrated.

## Scope and identity

- Root: `C:\Users\Adam\.local-ai-hub`, HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
- Patch: `t11-root-current-followup-20261005-v2.patch`.
- Patch SHA-256: `A12BFF22FFA48A29786C7A3C33065B70B55187068F1812E14151396FD15AC7B0`.
- Paths: `src/local_ai_hub/rag.py`; `tests/test_t11_rag_ingestion_contract.py`.
- Excluded: `project_config.py`, `mcp_server.py`, `services.py`, T14 paths, and T21 checkout.
- Root `git apply --check --recount --whitespace=error`: PASS; patch not applied.
- Synthetic postimages: Python AST parse PASS (2 files).
- Root tracked-dirty count observed before and after: 187; no root writes by this task.

## Hashes

| Path | Root preimage | Proposed postimage |
|---|---|---|
| `src/local_ai_hub/rag.py` | `4E22079FF0DE0CC9360411693E66FBEF12B9C310BEC1896378B107846617348B` | `E1F67AA741945BFF05704BBDA385D9DCF90F42C1CA2880A1FE3C9F2B1BB59CA1` |
| `tests/test_t11_rag_ingestion_contract.py` | `9710F1846DE6D35CF9D8045EC8D7DF3663488FC94C479AE41BAF1A20DF614294` | `1B6230D2AB67EF44776FB0F2330107FBB944F33869BBF685469DFDDCBF216321` |

## Delta

- Keep non-busy SQLite failures non-retryable in the public `index()` result.
- Prioritize explicitly dirty paths in bounded `index_step()` batches. Root already has the `dirty_paths` argument and includes same-stat dirty paths; v2 only adds priority.
- Filter MCP tool-accounting telemetry requests in the ingestion contract test, while asserting both exact RAG request payloads.

## Validation context

- Earlier root diagnostic after concurrent integration: fragment-cache, hybrid, vector and FTS selectors had 5 failures / 32 passes, including missing dirty-path priority and FTS retryability; explicit MCP payload selectors saw telemetry requests. This v2 packet was not applied to root, so those are pre-patch diagnostics, not post-patch test receipts.
- Earlier candidate follow-up selectors: 36 passed / 12.36s. Earlier candidate suite: 185 passed, 1 skipped, 2 deselected / 56.22s. These do not prove this root packet.
- Stable root embedding-cache rerun after concurrent source update: 17 passed / 0.24s. No embedding hunk needed.

## T11 checkout acceptance — 2026-10-05

Checkout: `C:\Users\Adam\.codex\worktrees\f678\.local-ai-hub`, HEAD `3c7da92aa6a267c2a18af0555d927f0e67d4c476`, with existing dirty T11 work preserved.

1. `python -m pytest -q --tb=short tests/test_rag_fragment_cache.py tests/test_rag_hybrid.py tests/test_rag_quality_contract.py tests/test_t11_rag_ingestion_contract.py tests/test_rag_read_bounds.py tests/test_t11_rag_seed_integrity.py tests/test_t11_project_policy_consumers.py tests/test_model_release_lifecycle.py` — **154 passed, 3 skipped in 36.46s**. Skips: two opt-in benchmarks and live Ollama verification.
2. `python -m pytest -q --tb=short tests/test_embedding_cache.py tests/test_embedding_batch_deduplication.py tests/test_rag_dedup.py tests/test_storage_service_reliability.py` — **38 passed in 4.33s**.

Total: **192 passed, 3 skipped**. Covered SQLite `database is locked` retry behavior, persisted resolved embedding-space recovery, same-stat dirty-path priority and pending completion, and test imports (`Path`, `os`). No expected assertion weakened. Live Ollama and benchmark acceptance remain unrun. These receipts apply to the dirty T11 checkout, not root.

Scope ledger: T11 RAG/embedding tracked changes are in the modified source/test set listed by `git status`; unrelated existing `src/local_ai_hub/project_config.py` and `tests/test_project_config.py` stay untouched. No T21 project configuration work, root writes, staging, or commit in this continuation.

## Live local-model receipt — 2026-10-05

- Bounded local Ollama check: `http://127.0.0.1:11434/api/tags` returned HTTP 200; `ollama list` showed `qwen3-embedding:0.6b` installed. Local AI Hub was not used.
- `T11_REAL_OLLAMA=1 python -m pytest -q --tb=short tests/test_t11_rag_ingestion_contract.py::test_t11_live_ollama_rag_ingest_and_reranker_truthfulness` — **1 passed in 23.89s**. Real embedding model used; real reranker not enabled (`T11_REAL_RERANKER` unset).
- Combined receipts: **193 passed**, two opt-in benchmarks skipped. This is source and local Ollama acceptance in the T11 checkout; no production deployment claim.

## Master-plan closeout audit — 2026-10-05

- T11 bounded retrieval/peak-memory benchmark: `RAG_BENCHMARK=1 python -m pytest -s -q --tb=short tests/test_rag_quality_contract.py::test_retrieval_latency_and_peak_memory_baseline` — **1 passed in 39.76s**. Current receipt: `handoff/t11-rag-benchmark-receipt-20261005.json`; 12 O(N) complexity probes, 100k p95 max **414.484 ms**, peak traced memory max **13.213 MiB**; suite asserts p95 <=750 ms and memory <=16 MiB.
- T11 synthetic ingest/seed benchmark: `T11_RAG_BENCHMARK=1 python -m pytest -s -q --tb=short tests/test_t11_rag_seed_integrity.py::test_t11_ingestion_batch_benchmark` — **1 passed in 12.71s**. Current receipt: `handoff/t11-rag-ingest-benchmark-receipt-20261005.json`. Synthetic embedder only; not model throughput.
- Own MCP-ingest verification, no root fixture copied: `python -m pytest -q --tb=short tests/test_t11_rag_ingestion_contract.py::test_mcp_rag_ingest_accepts_explicit_document_and_diagram_fields tests/test_t11_rag_ingestion_contract.py::test_mcp_rag_ingest_requires_explicit_input tests/test_t11_rag_ingestion_contract.py::test_mcp_rag_ingest_forwards_explicit_fields_only` — **4 passed in 2.16s**.
- Existing current-tree offline suites: 154 passed / 3 optional skips plus 38 passed; local Ollama embedding smoke (real qwen3-embedding, reranker disabled) 1 passed. The remaining skipped tests were the two benchmarks above and that live smoke; all three were subsequently run. The repeated broad suite still has two benchmark skips because those were run as separate opt-in selectors.
- CrossEncoder live command: `$env:T11_REAL_OLLAMA='1'; $env:T11_REAL_RERANKER='1'; python -m pytest -q --tb=short tests/test_t11_rag_ingestion_contract.py::test_t11_live_ollama_rag_ingest_and_reranker_truthfulness`. It reached `[100%]` after approximately 147 seconds, but final pytest summary and exit code were not captured; the exact process exited before a safe termination check. Mark live reranker acceptance **UNRESOLVED**, not passed. Do not infer from output dot. Existing 2026-10-01 live receipt is historical only.

## Ownership and limits

- This continuation added only these two benchmark receipts and updated this handoff report. No production/test source edits, root edits, staging, or commit.
- Existing dirty `f678` T11 source/tests remain inherited. `src/local_ai_hub/project_config.py` and `tests/test_project_config.py` remain out-of-scope and untouched. The root-current packet remains unapplied.
- Therefore offline T11 acceptance, current CPU benchmark gates, MCP ingest contracts, and local embedding smoke are verified in the dirty candidate. Live CrossEncoder end-to-end quality remains unresolved; do not claim full T11 completion.

## CrossEncoder run reconciliation — 2026-10-05

- Exact test process was `python.exe` PID `17692`, command contained `test_t11_live_ollama_rag_ingest_and_reranker_truthfulness`. A guarded process-identity check later returned `OWN_LIVE_TEST_ALREADY_EXITED`; no other PID was stopped.
- Current run's retained output is only the tool stream ending in `.` and `[100%]`; no final pytest summary, exit code, or saved stdout/stderr file/receipt was found in the T11 handoff artifacts. Therefore current live CrossEncoder result remains **UNRESOLVED**.
- Found `handoff/t11-transformer-reranker-live-receipt.json` (dated 2026-10-01, 1 passed in 23.47s). It is a prior candidate receipt and does not close the 2026-10-05 run.
- No test/model rerun, further wait, or process poll performed for this reconciliation. Offline suites, Ollama embedding smoke, and CPU benchmark receipts above remain unchanged.

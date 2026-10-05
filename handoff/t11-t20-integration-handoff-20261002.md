# T11 → T20 integration handoff — 2026-10-02

Status: **REVIEW / OPEN**. Candidate code is verified offline; root integration and 100k performance acceptance are not complete. No tests rerun and no root files changed for this handoff.

## Root-current overlay

- Root HEAD: `01df56605ccf484ebfe2808ac60d696c4e81dffc` (T20-owned, dirty).
- Patch: `handoff/t11-root-current-overlay-20261002.patch`
- Patch SHA-256: `910ff7dabf98202c2d7bc9b3c4fde1633377782c0493e869c1a164fa7009e145`
- Manifest SHA-256: `d11f45dfce99e2c66861bdd9b60663e19b85c17bacc24e95613b36be4bac15d6`
- Read-only `git -C C:\Users\Adam\.local-ai-hub apply --check C:\Users\Adam\.codex\worktrees\f678\.local-ai-hub\handoff\t11-root-current-overlay-20261002.patch`: **PASS**.
- Current root already contains T11 production behavior in `embeddings.py`, `rag.py`, and `reranker.py`. Their root pre/post SHA values are identical; see manifest. Root `_search_uncached` already has no search-time `BEGIN IMMEDIATE`. The patch therefore adds only the T11 warm-search regression test to `tests/test_rag_hybrid.py`. Root test has not been run; T20 owns that selector.
- T21 `project_config.py` and `/api/context/pack` are excluded.

## Candidate receipt and open blockers

- Offline suite: **176 passed, 3 skipped in 39.49s**. Exact command is in the manifest. Skips: 100k retrieval benchmark, live Ollama, ingestion benchmark.
- Fresh 100k RED remains `972.658 ms` p95 at batch 4096 vs 750 ms limit. No benchmark rerun; GREEN performance receipt absent.
- GPU reranker still lacks local `BAAI/bge-reranker-base` weights. No downloads or installs.

Next: integrate/check the test overlay in T20 root, run the root-owned selectors, and keep T11 open until performance acceptance has an approved benchmark slot and passing receipt.

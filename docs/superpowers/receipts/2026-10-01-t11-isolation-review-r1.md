# T11 isolation review r1 — hold old artifact pairs

Independent reviewer: Hubble. Read-only source/artifact review, no imports/tests/writes/Hub/models/Git mutations. Root rag SHA `23BEE629DA1B9F4BA555FE64D031701553118F4CC3B55D8421FDC8D3885626DE` unchanged; supplied artifact pins stable.

Reviewed candidate `C:\Users\Adam\.codex\worktrees\f678\.local-ai-hub\handoff`:

- Embedding-space production `5631CC11281F207EB70B244AEF7468EF5867257FE8736E0F1C9FE9623C41B636`.
- Embedding-space tests `4FBBE2D81DA5CC58C457A050370319747923016342714D5B440F3CE186DEE62E`.
- Read-uncertainty production `C5F02D68E371C38B853DDC1A4F329E82EDF916ED6E3BA916B6FF68F193615B0F`.

Result: **NOT release-ready**. Vector predicate preserves tenant/workspace/path, but reachable cache, FTS and ingestion reuse remain unsafe or inconsistent.

1. Critical: public `search` cache key at root rag.py:1751 omits effective tenant/scope. Identical workspace/revision can share results or coalesced computations across tenants before SQL isolation applies. Orchestrátor independently read this exact source. Include effective scoped identity; test public search cache/coalescing, not only `_search_uncached`.
2. Important: current runtime embedding-space/dimension missing from cache identity. Backend change can reuse stale cached results without executing new predicates.
3. Important: both FTS SQL branches rag.py:1774/1783 omit exact embedding-space. Hybrid fusion at 2010 reintroduces incompatible/empty-space rows. Require consistent resolved-space predicates and explicitly defined unresolved-space lexical behavior.
4. Important: same-workspace reuse rag.py:1274 accepts empty provenance; cross-workspace reuse 1307 accepts empty/NULL then relabels as current space at 1321 without recomputing embeddings. Orchestrátor confirmed source. Require exact provenance on all reuse paths; legacy rows need new embeddings, not relabeling.
5. Important: the two production patches do not sequentially compose in either order; overlapping search/empty-result hunks. Deliver one reconciled root-current delta preserving read uncertainty and embedding mismatch behavior.
6. Minor: mismatch diagnosis scans workspace without requested scope; stale rows elsewhere must not imply requested subtree mismatch.

Prior receipt reports 2 failed / 3 passed; added tests call `_search_uncached` and mixed-space fixtures omit FTS rows. No public cache/runtime identity/legacy reuse/composed consumer acceptance proven. Source review is not a runtime receipt.

T11 owns narrowly bounded fixes and genuine RED/GREEN public-path regressions in existing candidate. T20 owns integration and root validation. Both notified; hold old artifact pairs, preserve published hashes. No GPU/100k benchmark needed for these correctness regressions.

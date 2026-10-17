# Exact Fuzzy Candidate Index for Code Search

## Intent

Reduce fuzzy `CodeIndex.query` scoring work in large repositories without changing the search result contract. Current fuzzy lookup scores every indexed symbol, then computes exact totals and deterministic pages. A candidate cap would make totals or later pages incomplete, so this design uses an indexed superset of all possible matches.

## Contract

- Exact ASCII identifier hits retain their indexed lookup and score boost.
- Fuzzy results remain complete: exact `total_matches`, `observed_match_count`, deterministic score/path/line/name-path ordering, and offset pagination remain unchanged.
- The existing scorer remains authoritative. The trigram index may admit false positives but must never omit a row that could receive a positive score.
- For every search term of at least three Unicode code points, a candidate is included when all distinct trigrams of that term occur in any one searchable field (`name`, `name_path`, `container`, or `path`). Candidate rows are unioned across terms and fields, then the existing scorer removes false positives.
- If any term has fewer than three code points, use the current complete-scope scan. This preserves all short-substring matches.
- Normalize stored fields and query terms with Python `str.lower()` before trigram extraction. This keeps Unicode matching aligned with `_code_index_candidate_score`.
- Derived trigram rows update in the same SQLite transaction as symbol rows for single-file, batch, delete, prune, and unindexable-file paths.
- Existing derived databases without the trigram schema are archived and rebuilt through current code-index recovery. No migration or compatibility shim is added.
- Trigram query failure or unavailable index state falls back to the complete existing scan; it never returns a partial candidate set.

## Non-goals

- No result cap, approximate count, reordered tie-breaks, query-language changes, external search service, or model inference.
- No test, benchmark, or runtime claim until the full source bundle is closed.

## Acceptance evidence

Deferred unit cases compare indexed and full-scan result sets, scores, totals, and pages for repeated grams, Unicode lowercasing, multiple fields, short terms, exact-plus-fuzzy queries, file replacement, batch updates, deletion, pruning, and schema rebuild. A paired benchmark later measures scorer-call reduction and end-to-end query latency on pinned symbol sets; adoption requires unchanged results and lower measured work on large repositories without material small-repository regression.

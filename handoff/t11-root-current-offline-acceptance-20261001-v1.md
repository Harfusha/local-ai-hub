# T11 root-current offline acceptance

- Root: `C:\Users\Adam\.local-ai-hub` at `98a9a1a7611af574caf20a88620c4aa3eb2e918a`. Candidate: `C:\Users\Adam\.codex\worktrees\f678\.local-ai-hub` at `3c7da92aa6a267c2a18af0555d927f0e67d4c476`.
- Both runs used temporary overlays. Root unchanged. `/api/context/pack` untouched. No live model or 100k benchmark.

## Current root source + root tests

- Command: `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_t11_rag_ingestion_contract.py tests/test_rag_quality_contract.py tests/test_rag_hybrid.py tests/test_rag_read_bounds.py tests/test_t11_project_policy_consumers.py`
- Result: **69 passed, 4 failed, 2 skipped in 36.00s**.
- Failures:

  - test_vector_search_streams_rows_and_keeps_golden_relevance: expected chunk_no [2,3,1], got []
  - test_numpy_vector_parse_skips_integer_overflow: results empty
  - test_equal_scores_use_semantic_path_order_not_row_order: results empty
  - test_vector_cursor_closes_before_scoring_batch: closed_before_dot false

## Candidate source + root tests

- Command: `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_t11_rag_ingestion_contract.py tests/test_rag_quality_contract.py tests/test_rag_hybrid.py tests/test_rag_read_bounds.py tests/test_t11_project_policy_consumers.py`
- Result: **66 passed, 7 failed, 2 skipped in 30.49s**.
- Candidate source did not pass the current root test contract; no integration patch prepared.

## Candidate-owned offline suite

- Result: **71 passed, 2 skipped in 24.36s**. Live reranker and 100k benchmark skipped.

## Root preimage pins

- `src/local_ai_hub/rag.py` `4c0ed5c52ec4cd9d82b41f0d6d2188812d607d1ce58c4ffea956d045fbb9048a`
- `src/local_ai_hub/embeddings.py` `21a6282871005d1045b2e76a2cc65599deedb877477e007c1aa8fb31bfaccd08`
- `src/local_ai_hub/reranker.py` `12773e04a90db8f8a367e618d725a3ea995faf4b624244907b8a13f30ced2ec7`
- `src/local_ai_hub/project_config.py` `4238b6a6de1de00f55f4679ce0df7d431522ec1bafabfa272258c1662f13f713`
- `tests/test_t11_rag_ingestion_contract.py` `4876d98a26b9eb26701a841799ba088f3dac3021b842a2b55945f53641306914`
- `tests/test_rag_quality_contract.py` `4ba233cb1e69c8c42a782021f4d545a6cd1fd4c748104439fa479b473a10c51f`
- `tests/test_rag_hybrid.py` `5e8508f96b808a7369fa9e97617be359f7f23ea7a6213364eec71b99f5149160`
- `tests/test_rag_read_bounds.py` `9d9f3ee9daad5306570d9a7c2674da1a4cf3342541a1a2b43abb1f798ec0d002`
- `tests/test_t11_project_policy_consumers.py` `d79c4748e277b5eae20be56921765709a7180eb54cd7874041a483b16d3ff6a4`

## Existing patch checks

- `t11-root-current-bounded-ingestion-production.patch` SHA-256 `19688b4dcadbdd9919489d2997dee84405a98a6a895773da6e05ade0b89d4f26`: strict root apply-check failed; no patch applied.
- `t11-root-current-embedding-space-v1-production.patch` SHA-256 `5631cc11281f207eb70b244aef7468ef5867257fe8736e0f1c9fe9623c41b636`: strict root apply-check failed; no patch applied.
- `t11-root-current-rag-isolation-v3-production.patch` SHA-256 `afac10c2903ff46613bdcd9e7cc6fb831315e4fa145aa48b7356cf226e2eaa42`: strict root apply-check failed; no patch applied.
- `t11-root-current-read-uncertainty-v1-production.patch` SHA-256 `c5f02d68e371c38b853ddc1a4f329e82edf916ed6e3ba916b6ff68f193615b0f`: strict root apply-check failed; no patch applied.

T11 remains open. Reported live `Credential Rotation Plan` vs `Cafeteria Menu` failure is not reproduced by offline tests. No current-root patch created because root/candidate pins diverge and candidate source overlay remains red.

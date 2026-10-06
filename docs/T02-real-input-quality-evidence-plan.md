# T02 Real-Input Retrieval Quality Evidence Plan

## Status

Plan only. No real corpus, user query, or production data was inspected or measured in this candidate task. Synthetic benchmark golden operations do not count as real-input quality evidence.

## Paired evidence design

1. Select one permissioned, non-sensitive local corpus and pin its exact revision. Record corpus identifier, relative document IDs, per-file SHA-256, byte counts, format counts, parser/index versions, and corpus manifest hash. Do not place document contents or secrets in the receipt.
2. Prepare a fixed query set before measurement. For each query, record a stable query ID, expected relevant document IDs, and relevance labels. Keep query text private if it contains sensitive information; receipt may store a query hash.
3. Freeze retrieval settings for baseline and candidate: embedding space/model identity, chunking, filters, top-k, reranker, index schema, and any freshness cutoff. Reuse identical inputs and settings.
4. Execute same queries against baseline then candidate with recorded revisions and config fingerprints. Keep raw per-query retrieved IDs in a private evidence artifact; publish only hashes and aggregate metrics.
5. Report Recall@k, MRR, nDCG, empty-result/coverage rate, and per-query plus aggregate p50/p95 latency. Define k values and acceptance thresholds before the run; current T02 contract sets no real-input thresholds.
6. Preserve exact command, UTC timestamps, environment/hardware summary, corpus/query manifest hashes, baseline/candidate revisions, configuration hashes, per-query result artifact hashes, metric output, exit status, and failure/skip reasons.

## Boundaries and missing evidence

This plan does not authorize access to private repositories or corpora, a real-input run, model inference, GPU use, or deployment. It does not prescribe a numeric relevance threshold. T20 must approve dataset scope, query count, labels, metrics, thresholds, and resource window before execution.

Current packet has no real-input corpus manifest, query labels, retrieval outputs, or quality metrics. Those remain open receipts; synthetic matrix results cannot substitute.

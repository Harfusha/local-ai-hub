# T02 root-current acceptance handoff — 2026-10-01

## Root and candidate pins

- Root: `C:\Users\Adam\.local-ai-hub` HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`; read-only.
- Candidate: `{repo}` HEAD `{candidate_head}`.
- Root and candidate hashes are recorded in `acceptance-manifest.json`. Metrics below come from candidate revision `a7b0868ac964fd14e160001024e6e0ecaaf4e9db`, not current root.

## Original combined `2/25` RCA

- Retained receipt SHA-256: `f602295b4b953034f4dadace78af297e448fd4aa8da28343bcb7c091b4d07fe2`. It records target 25 attempts but only 3 attempt records, a command over two whole test files, and no selector manifest. Exact original 25-node replay cannot be reconstructed from retained input.
- Minimal deterministic reproduction exists for recorded queue-cancel failure: baseline `async_jobs.py` RED (`running` vs `cancelled`, 5.106s); candidate deadline fix GREEN (2.392s). See `evidence/queue-cancel-race/` for command/log hashes.
- This closes queue race RCA only. It does not reproduce full original 25-node set or establish SQLite warning owner. Historical ResourceWarning trace is truncated before allocation frames.

## Model-free baseline manifest

- Required matrix: 3 file sizes × 2 RAG sizes = 6. Measured: 2/6. Unmeasured: 4/6 (deferred 100k cases).
- Actual sampling per measured case: light 3; comparison 3; concurrency `[1,4]`. Contract target per case: 1000 light; 30 comparison; concurrency `[1,4,16,32]`.
- Full stage aggregates with cold/warm p50/p95/p99, throughput, and exact sample counts are embedded in `acceptance-manifest.json`; raw source records are copied under `evidence/model-free-records/` and SHA-pinned.
- Both case records passed, `baseline_readiness=per_case`, inference skipped. Synthetic quality score 100% applies only to 5 deterministic fixture checks; semantic retrieval quality not established. Peak RSS: 196,874,240 B at 100×10k; 225,116,160 B at 10k×10k. Peak VRAM unavailable, not zero.
- Not plan-grade, not paired, not current-root latency, not a performance acceptance claim.

## Root outcome

No root files changed. No tests or benchmarks ran in this continuation. No GPU/VRAM test ran. T02 remains open for missing original selector manifest/SQLite warning ownership, four matrix cases, sample targets, and paired acceptance.

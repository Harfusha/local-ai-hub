# Preprocess demand-priority benchmark — 2026-11-06

These measurements cover bounded file-card scheduling and deterministic `context_pack_paths`. No model inference ran. Synthetic fixtures and the sampled real repository are reported separately.

## Synthetic fixture

Command: `python tools/benchmark_preprocess_demand.py --files 512 --batch-size 32`

The fixture contains one query-matching hot file among 512. Demand ordering selected it in batch 1; FIFO selected it in batch 16. Both runs completed all 512 files across 16 batches.

| Measure | FIFO | Demand priority |
| --- | ---: | ---: |
| Batches to hot file | 16 | 1 |
| Files selected in first batch | 32 regular | 31 regular + hot file |
| Selection median | 0.716 ms | 1.292 ms |
| Selection p95 | 0.845 ms | 2.555 ms |
| Files completed / left | 512 / 0 | 512 / 0 |

Demand selection adds 0.576 ms median and 1.710 ms p95 on this synthetic run. The benchmark verifies queue order and starvation avoidance, not real preprocessing throughput.

## Sampled real repository

Command: `python tools/benchmark_preprocess_demand.py --files 512 --batch-size 32 --root "C:\Users\Adam\.local-ai-hub" --query "search endpoint hybrid RAG"`

The bounded sample covered 512 files and 8,190,153 bytes after examining 701 directory entries. The file cap was reached; the directory-entry cap was not. The query matched 214 sampled files. FIFO and demand ordering both produced useful context in batch 1 after 32 files; no preprocessing work was saved. Both completed all 512 sampled files in 16 batches.

| Measure | FIFO | Demand priority |
| --- | ---: | ---: |
| Useful context latency | 354.5 ms | 103.7 ms |
| Context packing time | 353.6 ms | 97.7 ms |
| Evidence items / context characters | 1 / 4,034 | 5 / 5,098 |
| Selection median / p95 | 0.830 / 1.109 ms | 1.516 / 6.004 ms |
| Files before useful context | 32 | 32 |

This is one deterministic sample, not a repeated causal comparison. Demand ordering took longer to select each batch, but this sample returned five evidence items instead of one and reached useful context sooner. It did not reduce total files or batches. No quality claim beyond the returned evidence count and context size is supported by this benchmark.

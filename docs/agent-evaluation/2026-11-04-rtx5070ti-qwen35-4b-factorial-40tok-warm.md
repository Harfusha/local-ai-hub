# RTX 5070 Ti warm hardware sample — qwen3.5:4b-nvfp4

**Status:** valid performance-only observation; not model-quality qualification or route promotion.

- Run: 20 consecutive `local_ai_task(action="hardware_benchmark")` calls, model `qwen3.5:4b-nvfp4`, identical factorial completion prompt, `max_tokens=40`, compact responses.
- Prompt: `def factorial(n: int) -> int:\n    """Return n factorial; reject negative n."""\n`
- Host: Codex through Local AI Hub 5.1.3; Ollama online. The benchmark reported NVIDIA GeForce RTX 5070 Ti, 16,303 MB total device VRAM, `policy_measurement_basis=dedicated_observed`, and dynamic context 32,768. Driver/backend, model digest, effective profile and installed-tag inventory were not returned.
- Root: `C:\Users\Adam\.local-ai-hub`; HEAD `b6f12daa2b8eac3cb23af8973d7365986db8a01f`; Hub git status `req_3cab701e92e0` reported 13 modified paths, none staged or untracked before this record. No repository tests or file mutations occurred during the benchmark.
- Cold/warm classification: all 20 are treated as warm repetitions; the 4B model was already resident before sample 1. A separate six-token diagnostic preceded this series. The 19-repeat block took 14.3 seconds; total elapsed time including sample 1 was not recorded.
- All 20 calls returned `success=true`, exactly 40 backend-counted tokens, and device-wide sampled peak VRAM. Statistics use median (mean of middle pair for 20 values) and nearest-rank p95.
- Representative full response `req_6498f20204a4` reported `streaming=false`. In that mode `HardwareBenchmarkRunner` sets `ttft_ms` to elapsed time for the full call, so this series' reported TTFT percentiles are full-call latency, not measured first-token latency. Per-request streaming flags were not retained for all 20 rows.

| # | Request ID | tok/s | TTFT ms | Queue ms | Peak VRAM bytes |
|---:|---|---:|---:|---:|---:|
| 1 | `req_6498f20204a4` | 86.40 | 462.94 | 9.78 | 9,300,869,120 |
| 2 | `req_1ee89d40c70e` | 80.54 | 496.62 | 5.34 | 9,299,820,544 |
| 3 | `req_2b4772e19b84` | 116.99 | 341.90 | 5.07 | 9,301,917,696 |
| 4 | `req_eb7bfd384ab2` | 133.83 | 298.90 | 5.13 | 9,301,917,696 |
| 5 | `req_a8d2afbc1b46` | 116.09 | 344.55 | 4.94 | 9,301,917,696 |
| 6 | `req_0eabe9f18870` | 98.76 | 405.02 | 5.30 | 9,300,869,120 |
| 7 | `req_9144172acce5` | 118.04 | 338.87 | 6.07 | 9,300,869,120 |
| 8 | `req_8b8727a04bb8` | 115.19 | 347.25 | 5.07 | 9,300,869,120 |
| 9 | `req_b005ffbf9db4` | 121.65 | 328.82 | 5.04 | 9,296,674,816 |
| 10 | `req_6f20e51833e7` | 115.54 | 346.20 | 5.00 | 9,296,674,816 |
| 11 | `req_d9579a2930ca` | 129.40 | 309.12 | 7.85 | 9,300,869,120 |
| 12 | `req_fb0b266ea44f` | 123.97 | 322.66 | 5.54 | 9,300,869,120 |
| 13 | `req_3dc2b76507d7` | 126.65 | 315.84 | 9.11 | 9,300,869,120 |
| 14 | `req_37bdb292d572` | 106.05 | 377.17 | 10.02 | 9,299,820,544 |
| 15 | `req_342b43389cb6` | 110.72 | 361.28 | 5.22 | 9,299,820,544 |
| 16 | `req_7cf5f872ef6c` | 119.62 | 334.39 | 5.51 | 9,299,820,544 |
| 17 | `req_689aa905f517` | 107.19 | 373.16 | 5.14 | 9,300,869,120 |
| 18 | `req_a4fcf62ee192` | 118.15 | 338.56 | 5.43 | 9,300,869,120 |
| 19 | `req_12050f485d0d` | 111.14 | 359.90 | 5.52 | 9,297,723,392 |
| 20 | `req_ba53c31c85f5` | 128.92 | 310.28 | 6.99 | 9,297,723,392 |

**Summary:** throughput min/median/p95/max = 80.54 / 116.54 / 129.40 / 133.83 tok/s; TTFT = 298.90 / 343.23 / 462.94 / 496.62 ms; queue wait min/median/p95/max = 4.94 / 5.39 / 9.78 / 10.02 ms. Device-wide sampled peak VRAM min/median/p95/max = 9,296,674,816 / 9,300,869,120 / 9,301,917,696 / 9,301,917,696 bytes. Reported final use ranged 8,866–8,871 MB; available VRAM 7,125–7,130 MB.

**Unqualified:** output correctness/quality, paired deterministic or model baseline, cold load, model digest, CUDA/backend/driver identity, 16k/32k/64k context stress, concurrency, background contention, low-memory behavior, fallback behavior, and promotion thresholds. The 40-token completion is too short to prove context capacity. Peak memory is sampled device-wide, not per-process accounting. Five earlier successful calls made with a minimal response profile returned only success/request IDs to the caller and are excluded from the metrics series: `req_ff1e0ba3c9d5`, `req_39ce140462c4`, `req_2233681d497e`, `req_0d794423fb74`, `req_4fc733990178`. The earlier six-token diagnostic (`req_0cdbd366a64a`) is also excluded.

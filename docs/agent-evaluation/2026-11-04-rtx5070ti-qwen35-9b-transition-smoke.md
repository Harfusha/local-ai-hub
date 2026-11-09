# RTX 5070 Ti 9B transition smoke — qwen3.5:9b-nvfp4

**Status:** one valid transition/load diagnostic; no warm-series, quality qualification or route promotion.

- Request: `req_9dcab4c3efc2`; `local_ai_task(action="hardware_benchmark")`; model `qwen3.5:9b-nvfp4`; factorial prompt; `max_tokens=40`.
- Hub/Ollama 5.1.3 were online. Model digest, backend, driver, effective profile, installed-tag inventory and confirmed effective context were not returned.
- Device: NVIDIA GeForce RTX 5070 Ti; 16,303 MB reported total. Initial: 9,135 MB used, 6,861 MB available, nominal pressure, context budget factor 1, dynamic context 32,768. Model load duration 2,004.09 ms.
- Result: 40 backend-counted tokens; TTFT 2,441.30 ms; generation duration 287.63 ms; 139.07 tok/s; queue 7.43 ms; device-wide sampled peak 14,512,291,840 bytes.
- The response reported `streaming=false`; the benchmark runner uses full-call elapsed time for `ttft_ms` in that mode. Treat 2,441.30 ms as full-call latency including queue/load, not true streaming first-token latency.
- Final sample: 13,840 MB used, 2,156 MB available, `pressure_level=high`, context factor 0.5 and dynamic context 16,384; `throttle_background=true`. The telemetry also reported speculative inference active with draft `qwen2.5-coder:3b` and target `qwen3.5:4b-nvfp4`, which does not match the measured 9B target and remains unexplained.
- A subsequent compact status `req_2742d97c3190` still showed the 9B active but returned VRAM pressure `unknown`. Treat the detailed benchmark sample as a high-pressure observation and the later status as unable to confirm recovery. No further 9B inference was submitted.
- Quality, output correctness, repeated warm throughput, cold capacity, concurrency, context stress, paired baseline and promotion are **NOT_RUN**. This is not evidence that the 9B route is safe at 32k or can sustain parallel work.
- No model was pulled; no profile or installed service was changed/restarted. No repo tests were run for this hardware-only call.

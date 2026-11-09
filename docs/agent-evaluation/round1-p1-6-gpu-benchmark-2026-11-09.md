# Round 1 P1-6 GPU benchmark — 2026-11-09

## Scope

Live Local AI Hub hardware benchmarks on the installed `qwen3.5:9b-nvfp4` only. No model was downloaded. Hub was online, Ollama online, GPU admission `available`, and reservation state `free`. GPU: NVIDIA GeForce RTX 5070 Ti, 16,303 MiB reported total. Installed model digest was verified as `646b3c2dbeba660702268ce7fd9033a8d6756ddbbdc9889b1dca6c1d6d2e581f`.

Each run requested the listed context, generated 128 backend-counted tokens from a fixed bounded prompt, and sampled `ollama ps`/VRAM after inference. All three returned `context_qualification_status=verified`, `context_qualified=true`, and loaded context equal to requested context.

| Requested / loaded context | Request ID | TTFT ms | Generation tok/s | Prefill tok/s | Peak device-wide VRAM bytes | Final available VRAM MiB |
|---|---|---:|---:|---:|---:|---:|
| 8,192 / 8,192 | `req_daa4e06b05dc` | 2,847.01 | 128.99 | 353.96 | 9,598,664,704 | 6,842 |
| 16,384 / 16,384 | `req_5c35fe5bbe81` | 2,876.60 | 128.47 | 380.01 | 9,719,250,944 | 6,727 |
| 32,768 / 32,768 | `req_8e1fec8ece56` | 3,163.90 | 127.94 | 293.19 | 9,924,771,840 | 6,531 |

Dynamic context budget reported 32,768 on each run. VRAM pressure stayed `nominal`; no OOM or recovery was reported. Throughput is a single sample at each context, not a repeated-run average.

A post-run `nvidia-smi` snapshot reported 9,475 MiB used / 6,521 MiB free and listed Windows desktop processes, ChatGPT, Edge WebView, Steam, and Ollama. This is device-wide evidence; Windows returned `[N/A]` for per-process VRAM. The benchmark peak is also device-wide and cannot attribute bytes to the model or prove the same desktop processes were active throughout each inference. Treat this as observed headroom under a live desktop session, not a dedicated concurrent-load stress test or OOM-proof guarantee.

`qwen3.5:4b-nvfp4` is absent from `ollama list`; no pull was authorized. Thus the requested 4B comparison remains unavailable. The 9B context, latency, throughput, and device-wide memory measurements are verified for these individual runs only.

## Regression evidence

`tests/test_t12_scheduler_scenarios.py`, `tests/unit/test_hardware_benchmark_prompt_metrics.py`, and `tests/unit/test_task_canonical_inputs.py`: 95 passed. The compact MCP benchmark projection now preserves `loaded_model_context_tokens`, `context_qualified`, and `context_qualification_status`; without that fix the context result could be lost at the API boundary.

## Long-prefill follow-up

Fresh runs on 2026-11-09 used unique, varied padding prompts and placed the response instruction at the end. Prompt sizes reached approximately 80–85% of the requested context; backend prompt counts below are authoritative. Each run requested eight generated tokens, so generation throughput is a short single sample rather than a sustained decode test. All six runs returned `success=true`, `context_qualified=true`, and the exact requested loaded context. Both models were already installed; no model pull occurred.

| Model | Requested / loaded | Backend prompt tokens | Request ID | TTFT ms | Prefill tok/s | Generation tok/s | Peak device-wide VRAM bytes | Final available VRAM MiB | Loaded model VRAM bytes |
|---|---:|---:|---|---:|---:|---:|---:|---:|---:|
| `qwen3.5:9b-nvfp4` | 8,192 / 8,192 | 6,523 | `req_e0c633840252` | 3,464.63 | 9,905.92 | 119.15 | 7,566,524,416 | 8,868 | 5,093,646,662 |
| `qwen3.5:9b-nvfp4` | 16,384 / 16,384 | 13,524 | `req_8850be71cdaa` | 4,183.73 | 10,098.14 | 106.53 | 7,801,405,440 | 8,780 | 5,185,921,350 |
| `qwen3.5:9b-nvfp4` | 32,768 / 32,768 | 27,521 | `req_d0651f0abd13` | 3,214.84 | 9,061.11 | 99.27 | 7,801,405,440 | 8,556 | 5,420,802,374 |
| `qwen2.5-coder:3b` | 8,192 / 8,192 | 6,541 | `req_f6803c1532c8` | 6,845.46 | 12,247.64 | 145.38 | 10,235,150,336 | 6,429 | 2,279,562,280 |
| `qwen2.5-coder:3b` | 16,384 / 16,384 | 13,976 | `req_628b0e7712bc` | 7,260.67 | 11,784.99 | 106.53 | 10,816,061,440 | 6,235 | 2,466,208,808 |
| `qwen2.5-coder:3b` | 32,768 / 32,768 | 27,906 | `req_86c361a314a1` | 2,926.75 | 10,001.00 | 75.33 | 10,816,061,440 | 5,681 | 3,075,452,435 |

3B digest: `f72c60cabf6237b07f6e632b2c48d533cef25eda2efbd34bed21c5e9c01e6225`; each run verified the installed digest. 9B digest remains the value above. A separate exploratory 3B run with a repetitive `while` padding prompt returned `model output repetition loop detected` (`req_c34d7c085aef`); it is excluded from the measurements. A later admission reported `gpu_outcome_unknown`; reservation status was `free` with no file, and the user-authorized release endpoint cleared stale scheduler state before the varied-prompt 3B runs. No inference was repeated after an unknown outcome.

These data verify long prefill and the configured context size for the installed 3B and 9B models under the observed desktop load. They do not prove sustained throughput, paired model quality, concurrency safety, per-process attribution, or zero-OOM guarantees. `qwen3.5:4b-nvfp4` remains absent and was not downloaded.

The user-authorized release endpoint cleared the final unknown reservation (`req_b9858d2b6eaa`); a subsequent `gpu_reservation_status` (`req_8b3ca450a7fa`) confirmed `reservation_present=false`, `state=free`, and `manual_intervention_required=false`. A separate 128-token 9B decode request was rejected before inference with `gpu_outcome_unknown` (`req_bb5283c5e351`); it was not retried. No identical inference request was replayed. The longer-decode throughput sample is therefore unavailable, and the eight-token generation rates above are only short samples.

Post-follow-up verification: benchmark/projection/scheduler files, 95 passed; VRAM-balancer plus scheduler-admission files, 36 passed; `python -m pyflakes src tools` and `python -m compileall -q src tools tests` passed. Full `python -m pytest -q --tb=short -p no:cacheprovider` completed with 15,275 passed, 129 skipped, 60 subtests passed and 11 failures. The two P1-2 fingerprint assertions are fixed and now pass in the focused suite; the other nine failures remain pending repair/classification.

## Longer decode follow-up

A new, independent 9B request ran after Hub readiness reported GPU admission available and the reservation was free. It generated 128 backend-counted tokens at 128.99 tok/s with verified installed digest and an 8,192-token loaded context. This does not replay the earlier request rejected before inference.

| Model | Request ID | Prompt tokens | Generated tokens | TTFT ms | Generation ms | Generation tok/s | Peak device-wide VRAM bytes | Final available VRAM MiB | Loaded model VRAM bytes |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `qwen3.5:9b-nvfp4` | `req_bc951f9fe00f` | 41 | 128 | 3,155.76 | 992.32 | 128.99 | 7,092,568,064 | 9,232 | 5,093,646,662 |

The request returned `success=true`, `context_qualified=true`, `context_qualification_status=verified`, `tokens_generated=128`, and `token_count_estimated=false`. VRAM pressure was `nominal`. This is one decode sample; it does not establish sustained throughput or concurrency safety. The full-suite result recorded above remains 11 failures pending classification.

## Simultaneous-request sample

Two distinct bounded 9B hardware benchmark requests were started concurrently at 8,192 context with 32-token caps. Both returned generated text and verified loaded context. They reported prompt counts 37 and 36, generation durations 247.82 ms and 248.64 ms, queue waits 36.90 ms and 7.73 ms, and the same device-wide peak sample of 7,140,802,560 bytes (9,186 MiB available). Request IDs: `req_b0318e2e5e6c`, `req_9b4340d03eee`. Reservation status after both calls was `free`, with no manual intervention required. This is one short same-model concurrency sample; it does not prove cross-model admission safety or zero-OOM behavior.

A separate cross-model pair then ran concurrently: `qwen3.5:9b-nvfp4` and `qwen2.5-coder:3b`, each requesting an 8,192-token context and at most 32 generated tokens. Both reported `success=true`, verified installed digests, and exact loaded contexts. The 9B request generated 32 tokens; the 3B request stopped after 4. Both reported nominal pressure. Device-wide sampled peak was 6,607,077,376 bytes; available VRAM reported 9,695 MiB and 7,311 MiB in the respective results. Request IDs: `req_206fca9f127b`, `req_9f61d05f846d`. A post-run reservation check returned `free` and `manual_intervention_required=false`. This is a single short cross-model sample under the observed host state, not a statistical or zero-OOM guarantee.

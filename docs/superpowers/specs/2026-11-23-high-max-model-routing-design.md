# High and Max Model Routing Design

## Intent

Make `high` and `max` model roles scale coherently with VRAM, keep preprocessing lightweight, and pin selected model weights to a predictable quantization.

## Goals

- Preserve `high`: 3B background/preprocessing, 7B fast code, 14B heavy code, Qwen3.5 9B reasoning and general.
- Set `max` baseline (24–31 GiB GPU VRAM): 3B preprocessing, 7B background/fast code, 14B heavy code and reasoning, Qwen3.5 9B general.
- Select 32B heavy code only when a single detected GPU has at least 32 GiB VRAM.
- Use Q4_K_M model weights and Q4 KV cache for the updated profiles. Do not automatically select FP4 based only on GPU capability; promote an exact CUDA model variant only after its quality evaluation passes.
- Preserve existing local changes and do not download models.

## Non-goals

- Rebalance CPU, integrated, low, balanced, or medium model tiers.
- Change runtime concurrency, context limits, installer provisioning, or model availability.
- Claim that configured tags are installed or qualified for unrestricted use.

## Approach

Keep the 14B model as `max` heavy/reasoning baseline and choose 32B heavy code only at the higher VRAM threshold. Pin Q4_K_M for those role targets, use Q4 KV cache, and remove automatic NVFP4 substitution: hardware support alone is insufficient, and current repository evidence does not qualify the exact NVFP4 route. Update the routing matrix and quantization notes to match.

## Acceptance

- `profile_overrides("max", ...)` keeps the 14B heavy target below 32 GiB and selects 32B at or above 32 GiB; missing VRAM remains on the 14B target.
- `high`/`max` do not switch Qwen3.5 roles to NVFP4 solely because `has_fp4` is true.
- `max` uses Q4 KV cache; preprocessing remains 3B.
- Shipped model-routing documentation and VRAM estimate maps match the implementation.
- No test suite is run for this change; review source and diff only.

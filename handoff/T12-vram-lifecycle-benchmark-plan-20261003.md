# T12 VRAM lifecycle before/after plan

Status: prepared, not executed. No model pull, inference, test, or benchmark was run for this plan.

## Scope and pins

- Candidate worktree: `C:\Users\Adam\.codex\worktrees\4816\.local-ai-hub`
- Candidate HEAD at plan start: `933c0129079fcc0c894a71fe842cbbb5e6ad7285`
- Root checkout at plan start: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`; keep it untouched.
- Changed scope: `src/local_ai_hub/vram_balancer.py` and `tests/test_vram_balancer.py` only, plus this handoff plan.
- `commands.py`, `services.py`, and `/api/context/pack` are outside scope.
- Capture final SHA-256 for both source and test file immediately before any accepted run. T12 had no T02 baseline artifact; do not claim optimization or improvement against T02.

## Gate and host

Run only after T20 grants an explicit serial GO and an owner-bound slot. Current evidence says this is the only physical host: RTX 4060, balanced profile. Do not claim integrated/high/max hardware acceptance from this machine. Check Hub status once before a run; do not pull models. Model-specific work may use only an already installed, explicitly selected model. If status reports critical VRAM pressure or inventory is unavailable, skip live inference and record the blocker.

## Deterministic contract command

After GO, execute once through `local_ai_command` from the candidate root:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_vram_balancer.py tests/test_model_routing.py tests/test_router.py tests/test_config_hardware.py tests/test_tiered_ollama_runtime.py tests/test_t12_llama_model_inventory.py
```

This command checks bounded telemetry coalescing/fallback, routing profiles and overrides, and inventory/runtime contracts. It is not a physical GPU or model-quality benchmark.

## Paired lifecycle measurement

Once a baseline snapshot and candidate snapshot are frozen, use the same host, Python/runtime versions, configuration, test process options, and idle-state precondition for both. Run baseline then candidate in AB/BA order, 3 blocks × 30 pairs per case. Cases:

1. Cached `status(force=False)` latency.
2. Forced telemetry `status(force=True)` latency and probe count.
3. One blocked telemetry sampler with one concurrent waiter; capture waiter elapsed time, fallback fields, and total probe count. Release the sampler in `finally` so the harness cannot strand a thread.
4. If an installed model is available and Hub status is safe: one fixed balanced-profile request per paired trial; record route/model tag, queue delay, end-to-end latency, generated tokens, fallback/cancel outcome, and peak VRAM. No pulls and no quality claim without a fixed evaluation set.

For each case preserve all raw per-pair observations and report p50/p95 for elapsed time, paired deltas, probe counts, failures, and stale/unavailable fallback counts. Report context-budget and throttling state with latency; the fail-closed fallback is a safety outcome, not a successful telemetry sample. Do not combine synthetic/mock timing with physical GPU measurements.

## Current blocker

T20 serial GO is not available in this turn. T20 state host was unreachable on the prior check. Therefore the command above, all benchmark workloads, and all before/after measurements remain unexecuted. No performance result is claimed.

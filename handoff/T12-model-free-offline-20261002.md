# T12 deterministic routing and offline scheduler receipt — 2026-10-02

Owner: T12 worktree. Root integration remains with T20.

## Result

Deterministic routing/config acceptance is source-level PASS. The offline harness ran against current worktree source and exercised configured profile targets plus production `AffinityScheduler` admission paths with synthetic callbacks.

Command: `PYTHONDONTWRITEBYTECODE=1; PYTHONPATH=src; python -B tools/t12_model_free_harness.py`

Exit: 0. Wall time: 4662.718 ms. Full machine-readable report: `T12-model-free-offline-20261002.json` (SHA-256 `DC9B0BB07F377106D40CC7B44544A0F601E567C3A77711E1CAE1928A66127DA9`).

The harness reports `measurement_mode=synthetic_model_free`, `live_inference=false`, `quality=not_measured`, and `vram_bytes=null`.

Configured route targets exercised:

- `balanced`: `{'fast_code': 'qwen2.5-coder:3b', 'heavy_code': 'qwen2.5-coder:7b'}`; queue-limit rejection `rejected`; one preparation per model; 2 switches.
- `high`: `{'fast_code': 'qwen2.5-coder:3b', 'heavy_code': 'qwen2.5-coder:7b'}`; queue-limit rejection `rejected`; one preparation per model; 2 switches.
- `integrated`: `{'fast_code': 'qwen2.5-coder:1.5b', 'heavy_code': 'qwen2.5-coder:3b'}`; queue-limit rejection `rejected`; one preparation per model; 2 switches.
- `max`: `{'fast_code': 'qwen2.5-coder:3b', 'heavy_code': 'qwen3.5:9b'}`; queue-limit rejection `rejected`; one preparation per model; 2 switches.

Cross-tenant virtual-time fairness: tenant A 1000 ms; tenant B 2000 ms. Queue rejection did not invoke executor. These are harness-path observations, not live throughput or latency evidence.

## Deterministic test evidence

No test suite was rerun in this step. Reuse existing worktree receipts:

- Routing/prompt selectors: 66 passed, 20 subtests. Exact command is recorded in `.handoff/t12-resume-receipt-20260930.json` under `routing_instruction_contract` and its validation evidence.
- Broader T12/config suite: 347 passed, 10 subtests. Its command includes `tests/test_model_routing.py`, `tests/test_config_hardware.py`, `tests/test_model_policy_sampling_floor.py`, and `tests/test_completion_model_routing.py`; exact command is recorded in the `validation` field of that JSON.
- Profile role mappings were statically compared with hardware source and prompt policy; receipt records pass under `t12_profile_policy_review`.

Current source SHA-256:

- `src/local_ai_hub/hardware.py`: `91621DEC38E68E611ED6F89D71508600D9C59A6F5AAC087678B4DDDC17069A8E`
- `src/local_ai_hub/router.py`: `AC089C43BD6A3CBEE26F3A742D80C92E7252D5A803491842EA7CB5D9C2E74B49`
- `src/local_ai_hub/scheduler.py`: `6F45F079F45997823EC81A854685B6CB42B6A83ADB2567270C00716847868B09`
- `tools/t12_model_free_harness.py`: `51091A7778D2C24555BF4258E27E203A8A746B3246284BF171D16EE7A3FBD9D8`

## Limits

Only configured routing and synthetic scheduler paths pass here. No live inference, model quality, CUDA/VRAM, native hardware profile, or T02 baseline evidence. T02 artifact is absent; comparison skipped and no optimization claim made. User confirmed RTX 4060 is only available physical host. Full T12 remains blocked on live acceptance.

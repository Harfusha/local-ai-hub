# T12 offline runtime routing acceptance — 2026-10-02

## Accepted offline checks

- Sampling floor and routing hardness: existing focused receipt **66 passed, 20 subtests**. It includes `test_model_policy_sampling_floor.py` and `test_model_routing.py`; not rerun.
- Runtime sampling/repetition and hardware profile defaults: existing broad receipt **347 passed, 10 subtests**. It includes `test_model_policy_repetition.py` and `test_config_hardware.py`; not rerun.
- Static `PROFILE_OVERRIDES` AST check passed for integrated, balanced, high, and max. Every recorded model role and `max_parallel` value matches current `hardware.py`.

## Unique consumer selector

Command: `PYTHONDONTWRITEBYTECODE=1; python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t12_project_model_consumer.py`

Result: **2 failed, 4 passed, 5 skipped in 0.58s**.

Root cause: `src/local_ai_hub/project_config.py` is absent. `services._resolve_local_task_project` catches the failed import and returns no project settings. The two unskipped tests then miss the configured project model and prompt prefix; five tests explicitly skip on the missing module. No fallback or fake behavior was added.

Source/test hashes and exact failure names are recorded in `.handoff/t12-resume-receipt-20260930.json` under `offline_model_routing_follow_up`.

## External limits

No live CUDA/VRAM or quality evidence. Only balanced RTX 4060 host is available. T02 baseline artifact is absent; comparison skipped and no optimization claim made. Full T12 remains blocked.

## Additional offline harness receipt — 2026-10-02

Parent-authorized bounded native harness command:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; $env:PYTHONPATH='src'; python -B tools/t12_model_free_harness.py
```

Exit **0**, duration **4.727 s**, candidate HEAD `933c0129079fcc0c894a71fe842cbbb5e6ad7285`. Durable output: `handoff/T12-model-free-offline-20261002-rerun.json`, SHA-256 `5FBAEFA87C664944B0B3F4F175B90794BC485273888E259F3BE31109CFFA123F`. Harness SHA-256 `51091A7778D2C24555BF4258E27E203A8A746B3246284BF171D16EE7A3FBD9D8`.

This run is `synthetic_model_free`: each profile exercised three accepted scheduler requests and one queue-limit rejection before executor invocation. Two configured models were prepared once per profile. Measured accepted-request queue waits were 1.216–1.617 ms, 25.412–25.567 ms, and 1088.928–1102.085 ms across the three requests; synthetic inference service was 5.141–25.529 ms. These are harness timings, not model inference. `live_inference=false`, `quality=not_measured`, `vram_bytes=null`; no optimization or physical-profile claim.

T20 selector S (`test_prompt_only_project_settings_preserve_host_model_profile`) was attempted once through the authorized broker but returned `Transport closed` without a receipt. The one permitted process check also returned `Transport closed`; outcome remains UNKNOWN. No retry/native pytest fallback. Selector and post-run source/test pins remain unverified.

## Scheduler deadline regression queued — 2026-10-02

Static review found that `AffinityScheduler.submit` calls its synchronous foreground GPU preempt hook before entering the caller-deadline wait. A slow managed-server stop can therefore hold the caller past its deadline before timeout handling begins.

Test-first regression added in `tests/test_t12_scheduler_scenarios.py`: `test_t12_preempt_hook_obeys_caller_deadline_before_dispatch`. It holds the preempt hook past a 50 ms caller deadline, expects `SchedulerTimeoutError(state="pending")`, and verifies foreground execution did not start before preemption. No production scheduler edit was made; TDD requires the selector's red result before implementation.

Exact selector, pending explicit T20 serial GO:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t12_scheduler_scenarios.py::test_t12_preempt_hook_obeys_caller_deadline_before_dispatch
```

At handoff, T20 reports this selector is waiting for its serial slot; no GO or test result exists. Candidate HEAD `933c0129079fcc0c894a71fe842cbbb5e6ad7285`; current scheduler SHA-256 `7E012E058D8AE213C50866D2E937F147C5C6871EECF8AD55FA1D273805ACC91D`; scenario test SHA-256 `57D8381E603A5D0BA322B4808E080ACDD7A9C81B806751357263FF328623AF85`. Scoped `git diff --check -- tests/test_t12_scheduler_scenarios.py` exited 0 with Git's LF-to-CRLF warning. No test or live service/model run.

## T20 serial GO #16 receipt — 2026-10-02

Pre-run HEAD and all six source/test/evidence pins matched; selector was present and matching runner count was zero. The sole authorized command was `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t12_scheduler_scenarios.py::test_t12_preempt_hook_obeys_caller_deadline_before_dispatch`, dispatched once through `local_ai_command`. Tool returned `Transport closed` with no receipt or execution metadata. Outcome is **UNKNOWN**: no test count, pass/fail, or duration can be claimed. No retry, poll, native fallback, or post-run runner scan. T20 was notified; slot released. Regression remains unverified; do not treat as red or green.

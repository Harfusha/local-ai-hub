# T12 acceptance continuation — 2026-10-04

Candidate: `C:\Users\Adam\.codex\worktrees\4816\.local-ai-hub`  
Candidate HEAD: `933c0129079fcc0c894a71fe842cbbb5e6ad7285`  
Scope: T12 only. Root checkout and other owners' paths were not changed.

## Candidate receipts

- Current routing/availability/completion/model-quality selectors:
  `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_router.py tests/test_local_model_availability.py tests/test_completion_model_routing.py tests/test_model_quality.py`
  — **56 passed**, exit 0, 0.82 s pytest / 1.273 s wrapper. Guarded sources and tests retained hashes; HEAD unchanged. Tests are synthetic or mocked.
- Current generated-policy/routing selectors:
  `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_model_routing.py tests/test_config_hardware.py tests/test_prompt_contracts.py tests/test_model_policy_sampling_floor.py tests/test_setup.py::test_instruction_policy_blocks_match_generated_policy_sources`
  — **24 passed**, exit 0, 1.94 s pytest / 2.536 s wrapper; `git diff --check` passed. HEAD unchanged.
- Historical focused lifecycle/quality suite: **61 passed**. Historical broad matrix: **303 passed, 5 skipped, 7 failed, 1 teardown error**. Exact historical command and logs remain in the original task history; these are not fresh receipts for this candidate continuation.
- Historical synthetic model-free harness: `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH=src`, `python -B tools/t12_model_free_harness.py` — exit 0, 4.727 s. It exercised synthetic `integrated`, `balanced`, `high`, and `max` profile maps; it measured no live inference, quality, or VRAM.
- Historical VRAM timeout/cache fallback regression: **2 passed** with CPU mocks. No hardware VRAM measurement.

## Selector history and status

- `tests/test_t12_scheduler_scenarios.py` was included in the historical broad matrix; do not rerun that suite as a whole.
- `test_t12_preempt_hook_obeys_caller_deadline_before_dispatch` has a broker `Transport closed` result with no receipt: **UNKNOWN**, not pass/fail. Do not retry.
- `test_prompt_only_project_settings_preserve_host_model_profile` also ended without a receipt: **UNKNOWN**. Do not retry.
- No remaining scheduler/routing selector was confirmed both unique and unrun. This continuation launched no pytest selector.

## Runtime gates still open

- Only physical host available: RTX 4060, balanced profile. No integrated/high/max host evidence.
- No live inference, quality, latency, load-thrashing, cancellation, overload, or VRAM acceptance receipt. Current bounded status had Ollama online, queue/inflight zero, `active_model=null`, VRAM pressure `moderate`.
- Installed-model inventory request `ollama list` was rejected by `local_ai_command` (`allowed=false`, `command not in safe broker allowlist`); its stdout is not treated as an accepted validation receipt. No model was pulled or invoked.
- T20 has no fresh benchmark GO/slot. T02 baseline artifact is absent; comparison and optimization claims remain skipped.

## Exact owner packets

- Generated policy sync patch: `T12-generated-policy-sync-20261004.patch`, SHA-256 `5F2E0207E8332F1C2976E7872E1FBDB53A6F52AA1F5A244474998B14B8CC5BBF`.
- Candidate generator-only root packet (preimage check passed; not applied): `T12-root-current-generator-policy-20261004.patch`, SHA-256 `22CEAC047EBC3957949E7822CEB3F46A9DACBECD8BAFD819B474A127D159A74C`.
- VRAM timeout/cache candidate packet: `T12-root-current-vram-timeout-20261003.patch`, SHA-256 `254200B68677DB9ED44166720A335338BC8DF80A691D8B47740AB02643587542`.
- The three packets are separate handoffs with their recorded preimages; none was applied to the root checkout in this continuation.

## Outcome

Offline candidate checks pass as listed. Full T12 acceptance remains **incomplete** until valid benchmark ownership/slot and required physical-profile runtime evidence exist. No optimization claim is made.

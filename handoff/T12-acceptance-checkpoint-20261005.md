# T12 acceptance checkpoint — 2026-10-05

## Ownership and candidate identity

- Registered worktree artifact: `01a0fb73-824b-7252-86d0-9add7d3f74d5`.
- Candidate path: `C:\Users\Adam\.codex\worktrees\4816\.local-ai-hub`.
- Git root: `C:/Users/Adam/.codex/worktrees/4816/.local-ai-hub`.
- HEAD before this checkpoint: `933c0129079fcc0c894a71fe842cbbb5e6ad7285` (detached).
- Adaptive repository context revision: `4cd5fb7be43f8e3cd85325045a047a48cdd8786640d41f03ce90d5cd216c2a9a` (workspace evidence identity; not Git HEAD).
- Worktree was already dirty with mixed T12 and inherited/other-owner changes, including a large untracked `.handoff/T12-model-free-root-overlay-20261001` tree. Preserved all. No `/api/context/pack`, shared-root, or unrelated source path changed in this continuation.
- T12 task goal already exists and was `blocked` at resume. No new goal/task was created and no completion/status transition was made. Current candidate `task_list` did not return a T12 Agent OS task contract; this append-only checkpoint records acceptance state without replacing the existing goal.

## Candidate validation receipts

Freshly reused from 2026-10-04; no tests ran in this continuation:

- `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_router.py tests/test_local_model_availability.py tests/test_completion_model_routing.py tests/test_model_quality.py` — **56 passed**, exit 0; pytest 0.82 s, wrapper 1.273 s; guarded hashes stable and HEAD unchanged. Synthetic/mocked only.
- `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_model_routing.py tests/test_config_hardware.py tests/test_prompt_contracts.py tests/test_model_policy_sampling_floor.py tests/test_setup.py::test_instruction_policy_blocks_match_generated_policy_sources` — **24 passed**, exit 0; pytest 1.94 s, wrapper 2.536 s; `git diff --check` passed.
- Historical VRAM timeout/cache fallback regression: **2 passed** with CPU mocks; no live VRAM measurement.
- Historical focused lifecycle/quality suite: **61 passed**. Historical broad matrix: **303 passed, 5 skipped, 7 failed, 1 teardown error**. Do not treat these historical results as a clean full pass.
- Historical `tools/t12_model_free_harness.py`: exit 0, 4.727 s; synthetic integrated/balanced/high/max profile maps only. No live inference, quality, latency, or VRAM proof.

## Selector and live acceptance status

- `tests/test_t12_scheduler_scenarios.py` was included in the historical broad matrix; suite not repeated.
- `test_t12_preempt_hook_obeys_caller_deadline_before_dispatch` — **UNKNOWN** after broker `Transport closed`, no receipt. Never retry.
- `test_prompt_only_project_settings_preserve_host_model_profile` — **UNKNOWN**, no receipt. Never retry.
- No remaining scheduler/routing selector was confirmed both unique and unrun. No pytest ran during this continuation.
- One physical host only: RTX 4060, balanced. Integrated/high/max physical-profile evidence unavailable. No live model invocation, quality/latency run, overload/cancel run, model pull, or benchmark performed.
- T02 baseline artifact absent: paired comparison skipped; no optimization claim.
- T12 live benchmark ownership/slot is not available. Adaptive context records T02 as current slot owner and T12 root selectors waiting for T02 release plus T20 queue clearance.
- Shared-root validation remains paused until T20 reconciles the disputed dirty fingerprint/path count (379 vs 452). No root tests or writes were made.

## Owner packets and exact pins

- `handoff/T12-generated-policy-sync-20261004.patch` SHA-256: `5F2E0207E8332F1C2976E7872E1FBDB53A6F52AA1F5A244474998B14B8CC5BBF`.
  - Candidate postimage SHA-256: `src/local_ai_hub/generator.py` `5AA14AC1D6FC9462ADA6CC2E495B519E18D1E535E37D2AC3245888376B4747FF`; `AGENTS.md` `3FD4C90FA3DD10CCA0E4C20423E1B25521C554C32953EEAD628B0CE166D2EA78`; `docs/INSTALL_PROMPT.md` `0B14752FDC0C4118DEA636B23F35005CA1D6F57DBD5950C1C7613353F650A7F9`; `docs/UPDATE_PROMPT.md` `574F8673C18799CBC5566DD22CEC73EC00A66B571052A5DFC4D11B0866FDEE8A`.
- `handoff/T12-root-current-generator-policy-20261004.patch` SHA-256: `22CEAC047EBC3957949E7822CEB3F46A9DACBECD8BAFD819B474A127D159A74C`; root generator preimage `2147622D0713579F7BE9EEE9890C646D50F932F26687D26BB951A51E560CDFCB`; candidate generator postimage `5AA14AC1D6FC9462ADA6CC2E495B519E18D1E535E37D2AC3245888376B4747FF`. Packet was not applied to root.
- `handoff/T12-root-current-vram-timeout-20261003.patch` SHA-256: `254200B68677DB9ED44166720A335338BC8DF80A691D8B47740AB02643587542`; recorded root preimages: `src/local_ai_hub/vram_balancer.py` `F5A5A7E0F5129F4144B875B4FD54D7C9E92685A7B66E94E54DAF5FA337D5E00A`, `tests/test_vram_balancer.py` `3C14CA43DA632903E85A394967A79145542C27B4AB53A43CFC7DC3A00CA5DB05`. These dated pins are not current shared-root validation.

## Resume decision

Candidate offline routing/policy checks pass. Full T12 acceptance remains **incomplete** pending T02/T20 slot release, reconciled shared-root ownership, and physical profile/runtime receipts. Existing goal retained; no status changed.

## Tiered admission capability regression receipt — 2026-10-05

- Indexed review of candidate `tests/test_tiered_ollama_runtime.py` found an existing regression selector, `test_post_unload_admission_capability_delegates_to_selected_runtime` (line 247), matching the previously recorded wrapper-admission gap. Candidate source already implements the delegation in `TieredOllamaRuntime.supports_post_unload_admission` (line 229); no lasting source/test edit was needed.
- Exact targeted run after the source had a temporary duplicate method (the later existing class method remained effective):
  `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_tiered_ollama_runtime.py::test_post_unload_admission_capability_delegates_to_selected_runtime`
  — **1 passed in 0.10 s**, command exit 0; `git diff --check` exit 0. The temporary duplicate was removed after review. No retry was run; the selector's observed pass tested the already-present effective delegation method.
- Final candidate source SHA-256 returned to its pre-edit value `C21644B24CB996FD682A1D7EEE11C5B3FD2763597891AFA0F427D3208E04F5FB`; test file SHA-256 `E50E87D7F3268D7AC01AD9C8F7A9A4E9F1142115F130A786EB6FDC1298854686`; HEAD remained `933c0129079fcc0c894a71fe842cbbb5e6ad7285`; HEAD blob for `tiered_ollama.py` is `a958825231d12840d23b04590898e77b7838d30a`. The pre-existing T12 dirty diff remains intact.

## Release-first focused receipts — 2026-10-05

After the earlier checkpoint, two non-live focused validations ran through the Local AI Hub command broker at repository revision `985dd14f5d4855ca5a385e61d49d9f6a889f9752b44662bb4b3c87d6d43b6d50`:

- `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_vram_balancer.py` — **9 passed in 0.25s**, exit 0.
- `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t12_runtime_scenarios.py -k vram` — **4 passed, 18 deselected in 0.12s**, exit 0.

No live inference, stress, full suite, install, Hub start, or source edit was performed in this continuation. These unit receipts do not close multi-profile/live T12 acceptance.
- Hub `local_ai_repo(action="review_diff", paths=[...])` rejected `paths` with terminal 400; one bounded candidate-only native diff slice confirmed the duplicate and existing method. No root review/test/write occurred.

## Fast-release priority and owner handoff — 2026-10-05

- Re-confirmed registered artifact `01a0fb73-824b-7252-86d0-9add7d3f74d5` at `C:\Users\Adam\.codex\worktrees\4816\.local-ai-hub`; explicit `attach_worktree` completed for that same Git root. Candidate HEAD remained `933c0129079fcc0c894a71fe842cbbb5e6ad7285`.
- Current bounded `repo_state` before this append: 42 changed paths, fingerprint `065e0ef6953b220617755d8de88f1ba328a422801cd93eed70be7a91a6958f1d`. It includes mixed T12 and inherited/other-owner files; no path was cleaned or reset.
- User's fast-release order and explicit deferrals are recorded in `handoff/T12-fast-release-plan-20261005.md`, SHA-256 `87DAF458617924B08A20AECC24B36EFA84228347C84E30632FEA8125D44C170C`. No T12 acceptance criterion was waived; only baseline-dependent optimization claims and polish outside acceptance were deferred.
- Candidate owner packet index is `handoff/T12-owner-packet-index-20261005.md`, SHA-256 `F48F4A023FBFB95D3FA6D379DA487DE605385BEB6B4154176106512901E1FD81`. It lists existing patch hashes, historical root preimages, current candidate file hashes, and exact focused receipts.
- T20 responded that it cannot reconcile the disputed root dirty count/fingerprint because its registered worktree is unavailable. It explicitly said not to transfer the T12 packet. Root integration/validation stays paused; T20 also reports T03 C2 and T08 swarm release blockers. No root tests or edits occurred here.
- T02's registered candidate is unavailable and its baseline artifact remains absent. Only balanced RTX 4060 physical evidence is available. Integrated/high/max live acceptance, live VRAM/quality/latency and full overload/cancel/fallback receipts remain open.

Current outcome: candidate and owner packets are ready for T20's reconciled root preimages, but T12 end-to-end release acceptance remains **blocked** by unavailable T20/T02 checkouts and missing required hardware/profile evidence. Existing goal remains incomplete.

Bounded host status snapshot after the coordination update: Hub `4.0.0`, Ollama online, active model `qwen2.5-coder:7b`, queued `0`, inflight `0`, VRAM pressure `critical`, context budget factor `0.25`. No inference or benchmark started.

## Final routing and live benchmark follow-up — 2026-10-05

Bounded candidate profile/routing contract command:

- `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_model_routing.py tests/test_config_hardware.py tests/test_t12_benchmark_contract.py` — **32 passed in 2.36s**, exit 0.

Latest bounded `local_ai_status(action="brief")`: Hub 4.0.0 online; active model `qwen2.5-coder:7b`; queue 0; inflight 0; VRAM pressure `high`; context budget factor 0.5. This reports the active model only, not a complete installed-model inventory.

One `local_ai_task(action="hardware_benchmark", root=<candidate>)` attempt failed before returning benchmark data: `AttributeError: '_InterruptibleSocketReader' object has no attribute 'peek'` (model reported by tool: `qwen2.5-coder:3b`). No repeat was made. No cold/warm/model-switch latency or live VRAM receipt was obtained. Do not infer measurements from contract tests or active-model status. Live balanced profiling is blocked by the tool transport error and high VRAM pressure; only the balanced RTX 4060 host is available. Integrated/high/max remain unavailable; T02 baseline absent, so no comparison or optimization claim.

The semantic solve call also returned circuit-open for `qwen2.5-coder:7b` and `qwen2.5-coder:3b`. No source files changed in this follow-up.

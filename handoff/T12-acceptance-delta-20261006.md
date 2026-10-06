# T12 acceptance delta — 2026-10-06

## Identity and ownership

- Assigned candidate: `C:\Users\Adam\.codex\worktrees\4816\.local-ai-hub`
- Candidate HEAD/base: `933c0129079fcc0c894a71fe842cbbb5e6ad7285`
- Master comparison: `b947d76fdfb7ed592b72e55587d5c83cfa352c35`
- Candidate evidence fingerprint after the focused receipts: `a5168f8e91c71a3a6bb1fa5008720862242a90838916987d7fa89c5f500b1cf1`
- This acceptance delta is add-only. No source, shared `services.py`, root, or T14 path changed.
- Existing source/config/docs/test dirty state remains mixed/inherited. No unrelated owner changes are attributed or merged here.

## Receipted candidate contract results

1. Model routing/config/prompt/policy parity: **24 passed in 1.73s**, exit 0. Exact command, source/test blob pins, and scope are in `T12-routing-policy-blob-receipt-20261006.md` (SHA-256 `7E3F6DACD81A2A403016480DEC6CE3F1A92041405E62ED2844B330D8015BB3C6`).
2. Router, local availability, completion routing, quality/fallback contracts: **56 passed in 0.88s**, exit 0. Same receipt pins exact relevant test blobs.
3. Focused batch contract selector: **2 passed, 33 deselected in 0.19s**, exit 0. Exact command and source/test blob pins are in `T12-routing-batching-receipt-20261006.md` (SHA-256 `A9D4C7082045A27EF2CEA1AF1C6F07F2527166231061C30D53260CF5B0B8B0C1`).
4. VRAM fallback unit/scenario receipts: `tests/test_vram_balancer.py` **9 passed**; `tests/test_t12_runtime_scenarios.py -k vram` **4 passed, 18 deselected**. Prior checkpoint contains exact VRAM source/test postimages and command evidence.
5. Scoped `git diff --check b947d76f`: exit 0 on recorded model-routing/policy paths.

These receipts prove candidate contract behavior for the pinned blobs. They do not prove live inference, physical VRAM reclamation, or live overload/cancel/fallback quality.

## Release acceptance still open

- **Live latency and VRAM: NOT VERIFIED.** Latest bounded status had `active_model: null`, queue/inflight 0, VRAM pressure `nominal`. No installed-model inventory or live inference receipt was available. A prior bounded hardware benchmark failed with `AttributeError: '_InterruptibleSocketReader' object has no attribute 'peek'`; it was not repeated. No cold/warm/model-switch metric is claimed.
- **Profiles:** only balanced RTX 4060 host is available. Integrated/high/max live receipts are absent.
- **Baseline:** T02 artifact is absent; comparison and optimization claims remain skipped.
- **Integration:** root has separate dirty owners; VRAM root-current postimages were already present, and applying the dated packet against clean root index failed. Do not reapply or overlay the mixed candidate diff.
- **Final release gate:** T20 runs after root ownership reconciliation and the missing physical/baseline dependencies. T12 remains **INCOMPLETE / NO-GO** until required live receipts or an explicitly authorized scope change exists.

## No unsupported claims

No optional model is assumed installed. No model was pulled or installed. Candidate test passes are not live performance evidence. No acceptance gate is waived by this delta.

## Post-integration acceptance update — 2026-10-06

### Owner packet and current source

- T12 owner worktree: `C:\Users\Adam\.codex\worktrees\4816\.local-ai-hub`, branch `codex/sync-4816-20261006`.
- T12 commits: `a08d6f1d98fdc94a22521b6b1b1b92dee3690d97` (scheduler implementation), then `282a5624f3e5980e588045787507a72691813080` (scheduler fixture).
- Master integration commits: `1402bc934ae2a50e3b23ffd96300cc630bfcc58b`, then `135677aff274a281e88874290117b2c269d25d37`.
- Master/worktree blobs match for `src/local_ai_hub/scheduler.py` (`99ce19967ee112f231c7b79f565dde14f7e9b462`) and `tests/test_local_model_availability.py` (`f1b264cecf8ceca8d9adce72ecc4331b1c1d287b`). T12 owner commits are not ancestors of the master integration commits.
- Owner paths: `src/local_ai_hub/scheduler.py`; `tests/test_local_model_availability.py`. No `services.py`, T14 `/api/context/pack`, or T20 benchmark-surface edits.

### Offline acceptance receipts

1. `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t12_scheduler_scenarios.py::test_t12_preempt_hook_obeys_caller_deadline_before_dispatch` — **1 passed**, exit 0; execution `26457f8a5f5247e2a6888dd86a052e9a`.
2. `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_vram_balancer.py tests/test_t12_runtime_scenarios.py tests/test_tiered_ollama_runtime.py tests/test_t12_scheduler_scenarios.py` — **73 passed**, exit 0; execution `daeab1be855649259383835272c9fadb`.
3. `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_local_model_availability.py::test_scheduler_pending_timeout_releases_queue_slot tests/test_local_model_availability.py::test_scheduler_timeout_signals_running_job_and_keeps_capacity_until_exit tests/test_local_model_availability.py::test_scheduler_external_cancel_removes_pending_job_promptly` — **3 passed**, exit 0; execution `cbd067f34b234ef38b90d1f6eeefd1c0`.
4. `python -B -m pytest -q -p no:cacheprovider --tb=no tests/test_model_routing.py tests/test_config_hardware.py tests/test_prompt_contracts.py tests/test_model_policy_sampling_floor.py tests/test_local_model_availability.py tests/test_completion_model_routing.py tests/test_model_quality.py tests/test_router.py` — **82 passed, 1 failed**, exit 1; execution `dd533599312e4df3ad41de5eae178202`. Remaining failure: `tests/test_config_hardware.py::test_health_probe_timeout_rejects_absurd_values`; config timeout validation owner unresolved, outside scheduler patch.
5. Scoped `git diff --check` passed before each T12 commit.

### T02 baseline and live evidence

- T02 owner response: no receipt path or SHA; artifact registry empty; assigned checkout lacks Git metadata. T02 marks its 24-cell baseline **BLOCKED**.
- Required T02 comparison receipt: immutable baseline commit/tree and config/profile; approved model IDs; deterministic real-input workload and harness/version/hash; all 24 paired baseline/candidate cells with raw trial counts, latency and quality metrics, peak/after VRAM, environment/GPU/runtime identity, exact command/exit, and raw artifact hashes. Mark unavailable cells blocked. Until present, make no optimization claim.
- Bounded runtime status: `ollama_online=true`, `active_model=null`, queue/inflight `0`, VRAM pressure `nominal`; status overall `success=false`.
- Inventory command `ollama list` returned installed entries including `qwen2.5-coder:7b` ID `dae161e27b0e`, `qwen2.5-coder:3b` ID `f72c60cabf62`, and `qwen3.5:9b` ID `56671c2ab938`. Broker marked the command `allowed=false` (`command not in safe broker allowlist`) despite returning stdout; treat inventory as provisional.
- One bounded `local_ai_task(action="hardware_benchmark", model="qwen2.5-coder:7b", prompt="Return exactly: 4", max_tokens=16)` failed with `AttributeError: '_InterruptibleSocketReader' object has no attribute 'peek'`; request `req_2dd5c898b088`. No latency/VRAM measurements were produced; no retry or alternate transport used.
- Only balanced RTX 4060 host is available. Integrated/high/max profiles and paired real-input quality remain unmeasured.

**T12 status: ACTIVE / NO-GO.** Offline scheduler, routing and VRAM tests are receipted; baseline, live inference/latency/VRAM, complete profile matrix, and config timeout failure remain open. T20 owns final release acceptance.

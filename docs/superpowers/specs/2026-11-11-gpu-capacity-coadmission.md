# GPU capacity co-admission

## Goal

Admit Laya residency from measured capacity while preserving every existing GPU reservation and loaded model. Reservation presence or another resident model alone is not a rejection reason.

## Contract

- A valid reservation, with or without `owner_vram_budget_bytes`, does not by itself block Laya admission. The budget is metadata for its owner, not a physical allocation; admission uses fresh measured free VRAM and conservative request size.
- Every new reservation requires positive `owner_vram_budget_bytes`. Known Hub producers supply this owner metadata, but admission does not treat it as measured VRAM use.
- `AffinityScheduler.acquire_gpu_capacity_lease(owner, requested_bytes)` samples current total and available VRAM. It admits only when telemetry is current, available bytes cover the conservative request peak, and all active capacity leases plus the new request fit total VRAM.
- Acquisition and reservation generation binding are atomic under the reservation store lock. Malformed reservation or lease metadata returns `capacity_unknown`; measured shortage returns `insufficient_capacity`.
- Capacity leases aggregate across owners. Laya's lease is installation-wide, persistent through warm residency, and released only after confirmed Router unload. Scheduler request leases last through inference. No expiry or restart recovery may silently free a possibly live lease.
- Dispatch remains per-request. It defers only a request whose current measured capacity or residual shared budget is unknown/insufficient. Laya acquisition never unloads or preempts another resident model; a resident model alone is not a rejection reason.
- Shared-capacity model preparation passes `unload_others=False`; idle unload, prewarm, and background GPU lending stay disabled while any shared residency lease exists.
- External reservation remains in place while Laya shares capacity. Reservation release/expiry cannot clear a generation pinned by a capacity lease.

## Public API

```python
reserve_external_gpu(owner: str, *, owner_vram_budget_bytes: int) -> str | None
acquire_gpu_capacity_lease(owner: str, requested_bytes: int) -> dict[str, object]
release_gpu_capacity_lease(lease_id: str, owner: str, generation: str) -> bool
```

New reservations require a positive owner budget. Existing valid budgetless records can co-admit from measured free VRAM. Lease result includes `lease_id`, `generation`, and the pinned external reservation generation when one exists.

## Validation

Focused tempfile tests cover exclusive legacy reservations, generation binding, aggregate capacity admission/rejection, release fencing, real scheduler dispatch/admission, and model switching that preserves a resident Laya model. Do not run live inference, restart the Hub, or inspect/clear the operator's current reservation as part of these tests.

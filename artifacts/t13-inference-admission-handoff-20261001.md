# T13 handoff: AsyncJobManager inference admission

T08 owns the root-current `AsyncJobManager` API and transition drain in `artifacts/t08-async-inference-admission-root-current.patch`. T13 owns `app.py` dispatch wiring.

API contract:

- `active_inference_operations` reports active admitted operations under the transition condition.
- `inference_operation(admission_check=None)` yields `True` only after atomic admission and counter increment. It yields `False` when the supplied current-mode check denies work.
- Keep the actual inference/GPU call inside the yielded context. Context exit decrements the count for normal return, exceptions, and cancellation.
- `operational_mode_change_guard(timeout_seconds=None)` stops new admission, waits for admitted work to drain, then yields to mode persistence. Timeout raises `TimeoutError` and releases the admission block.
- Durable queued jobs remain queued when admission is denied. Existing blocked-mode response and job completion paths remain T13/app-owned.

T13 should call the API at the final dispatch boundary, pass a current operational-mode admission check, route `False` through the existing blocked-mode response path, and keep executor/GPU work inside the context. Do not track queue submission or status reads as inference.

Evidence in T08 candidate: `tests/test_async_inference_admission.py` 4 passed; `tests/test_async_job_reliability_contract.py` passed in the 86-test focused suite. Root remains unchanged; integration patch passes `git apply --check` against the current root checkout.

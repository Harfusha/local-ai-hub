# T13 operational mode final candidate handoff — 2026-10-01

Candidate worktree: `C:\Users\Adam\.codex\worktrees\t13-operational-mode\.local-ai-hub`
Candidate HEAD: `6050c41ce5510a6de3eaeb674a180560ea404f24`
Root: `C:\Users\Adam\.local-ai-hub`, HEAD observed `98a9a1a7611af574caf20a88620c4aa3eb2e918a`; T20 owns integration. T13 made no root writes.

## Root-current patch artifacts

- Four-source overlay: `handoff/T13-rootcurrent-fresh-overlay.patch`, SHA-256 `95D33076B5BC61A61D5A59C54B5FF21DDA7C271EABAA6544B9DEA499FF38895A`.
- Source preimage/postimage pins and initial apply receipts: `handoff/T13-rootcurrent-source-pins-2026-10-01.md`.
- T20's four older failing selectors compatibility delta: `handoff/T13-root-mode-test-contract-current.patch`, SHA-256 `DCD0E5D51AED1A08D5A02C71FADF3DABFFA130F7118486E8C7050044D28F5165`; detail in matching `.md`.
- At final check, root `test_operational_mode.py` and `test_async_operational_mode.py` SHA-256 matched test-patch postimages (`558A4800...A8392A`, `9B88C1F7...B8567A`). Root `git apply --check` now reports those hunks already present; do not reapply. Root HTTP/app hashes have since changed under T20 integration; T20 should reconcile owned hunks against its current checkout.

## Candidate changes / scope

- Mode gate: active permits all; gaming permits deterministic reads and speculative lint while expensive agent work returns bounded retryable rejection; maintenance/degraded fail closed.
- MCP operator status remains available; agent workload rejection happens before transport/accounting path.
- HTTP safe existing-job controls only allowed active/gaming; operator/admin mode routes retain authorization. Gaming release is reserved under transition guard, drain is checked, external unload/CUDA cleanup runs outside the guard, reservation blocks active resume until cleanup/drain finishes.
- Async batch child nonblank `root` or `cwd` overrides parent workspace; parent root/cwd inherited only when child gives neither.
- Candidate test cleanup uses real APIs/receipts: Ollama partial fixture includes verified remaining-model data; `EmbeddingModel`/`Reranker` tests call `release_accelerator`; CUDA receipts assert `state`; missing `SimpleNamespace` import fixed. No T12 production files changed.

## Validation

- Focused mode/MCP/HTTP/preprocess/context suites: **141 passed in 12.20s**.
- Full `test_async_jobs.py`: **64 passed in 9.55s**.
- Broader T13 suite once returned **277 passed, 1 failed** at `test_mode_change_receipt_reports_running_inference_until_cancel_finishes` (`started.wait(1)` timeout). Same selector passed alone (**1/1, 0.30s**); full async-job suite then passed (**64/64**). Failure is timing-sensitive; no code change made for it.
- Four changed Python source modules passed `py_compile`.
- `git diff --check` passed; Git emitted only existing LF/CRLF normalization warnings.
- Earlier exact-root-copy legacy selectors: before compatibility patch 4 failed; after patch 4 passed in 2.64s. The patch changes test contract/fixtures only; no production expectation weakened.

## Current proof boundary

Candidate source and targeted suites are green. One broad-suite timing timeout is recorded above. T20's root integration owns final reconciliation and integrated checkout tests; root release acceptance remains separate.

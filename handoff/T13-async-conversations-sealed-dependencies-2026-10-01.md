# T13 async/conversations sealed dependency manifest — 2026-10-01

Status: candidate evidence only; integration and acceptance remain open.

## Owned candidate

- T13 checkout: `C:\Users\Adam\.codex\worktrees\t13-operational-mode\.local-ai-hub`
- HEAD: `6050c41ce5510a6de3eaeb674a180560ea404f24` (detached)
- Retained ref: `refs/heads/codex/t13-lifecycle-core` at `c3f372b0a728298104ff8a7735dd36f7ad0b6bf0`
- Consumer patch: `handoff/T13-rootcurrent-consumer-v2.patch`
- Consumer patch SHA-256: `2DFD20E54161C20F57C447A2433BAAA2570DD3F31DCBEDB1EFDD1FA403237948`
- T13 candidate `src/local_ai_hub/app.py` SHA-256 after batch inheritance fix: `4EB942A56658ECFB21FDE29C7A723912BC42C048082B15B242E3BDD86520759C`
- T13 candidate `tests/test_t13_async_project_context.py` SHA-256: `7AA31775B0FE3CEA0D3DB34D7DDF42BD43DCB18D96FAA06A9136134B11DEE3BC`
- Joined scratch harness SHA-256: `A1274A270DAA7A2AD305188B0977551FFE7D705DC8923D440BD6744C2027A71F`
- Root preimages: `app.py` `4050325BCC0F319941A0A183C2DA7CA529A33820236062A39E86E817DCB7705E`; `http_server.py` `6BA4B79AD0A7D06C11151E07E7261AFD9CAD515C1EF8FBA5A0DB0A34CEAA40CA`
- Root postimages: `app.py` `F7360F3A7B266030FF0A79E5C1EA46780D5F3E28E96D2AD89254070656C53A60`; `http_server.py` `4B635B978EF556A69863507D9B7672604068997BE32C55CEFA1E1C1CCCC9C8BE`
- Patch check receipt: `git apply --check handoff/T13-rootcurrent-consumer-v2.patch` passed against the pinned root preimages; `git apply --stat` reported 2 files, 66 insertions, 11 deletions. Root files were not written or tested.

## Producer dependency (T08)

- Checkout: `C:\Users\Adam\.codex\worktrees\t08-agent-os\.local-ai-hub`
- HEAD: `2b33602adef0d030fea66cdcc04ca742c60b2e32`
- Canonical producer patch: `artifacts/t08-async-admission-root-current-17E5CEABBEA17711749104894A7E5E24708E2D260A4298CDDD7895BAEC69A41E.patch`
- Patch SHA-256: `17E5CEABBEA17711749104894A7E5E24708E2D260A4298CDDD7895BAEC69A41E`
- Root `async_jobs.py` preimage SHA-256: `A524078F716D4915F6ABFFB27347C4625FDBB9C34A1373F5F8442D7102AEF935`
- T08 candidate `src/local_ai_hub/async_jobs.py` SHA-256: `3BC9AA358C224D8A011F35B5C0D35693D804906D38586FFD28D4E24C4F3E4154`

## Generation-boundary dependency (T12 staged overlay)

- Checkout: `C:\Users\Adam\.codex\worktrees\4816\.local-ai-hub`
- HEAD: `933c0129079fcc0c894a71fe842cbbb5e6ad7285`
- Staged service: `handoff/.t12-r7-generation-boundary/overlay/src/local_ai_hub/services.py`, SHA-256 `E76A0B15C56B7E7461EAE5749AC62BA9B52F985C6AC55849B81E1E2F7A49DF89`
- Boundary test: `handoff/.t12-r7-generation-boundary/overlay/tests/test_t12_generation_boundary.py`
- Receipt: `python -B -m pytest -q -p no:cacheprovider --tb=short handoff/.t12-r7-generation-boundary/overlay/tests/test_t12_generation_boundary.py` — **1 passed in 0.26s** (run from T12 checkout).
- This source remains staged; T12 production `services.py` is not claimed to contain the boundary.

## T13 candidate receipts

- `tests/test_async_jobs.py` — 64 passed in 17.49s.
- `tests/test_conversations.py` — 24 passed in 0.40s.
- `tests/test_speculative_draft_and_split.py::test_speculative_draft_service` — 1 passed in 0.49s.
- `tests/test_t13_async_project_context.py` — 9 passed in 1.06s.
- T08 joined outer-consumer overlay — 1 passed in 1.20s; this replaced `_generate` with a controlled barrier, so it proves consumer drain behavior but does **not** prove the T12 nested generation admission.
- Candidate-source joined generation overlay: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t13_async_project_context.py handoff/.t13-t08-t12-joined/test_joined_generation_admission.py` — **10 passed in 2.58s**. The joined test uses the T13 candidate app/HTTP/mode modules, T08 candidate `async_jobs.py`, and T12 staged `services.py`. It pauses actual `_generate` after its active-mode snapshot, switches to gaming through the HTTP handler, confirms no runtime request, terminal cancellation, and cleared release ownership. It does not execute the root-current consumer patch postimage directly.
- T08 full joined overlay receipt — 38 passed in 16.83s; external receipt from the T08 owner, not rerun here.
- No GPU/model-quality proof. One older fake-CUDA suite had 8 passed and 1 failed due to a stale `status` expectation versus current `state`.

## Ownership and blockers

- T13 may edit its candidate and files beneath its `handoff`; T08 owns its producer; T12 owns production `services.py`; T20 owns root integration.
- No root files were modified. T13 consumer patch and T08 producer patch are separate artifacts.
- Batch inheritance bug found and fixed: parent root/cwd now inherit only when child root and cwd both fail to resolve. Regression covers explicit child root, explicit child cwd, and no child workspace hint.
- Root-current consumer patch postimage is still not executed by the joined harness; only its separate apply-check receipt exists.
- T13 candidate remains open until T12 production integration, root-current postimage validation, T19 full-suite acceptance, and T20 root integration are complete.

## Maintenance gate correction — 2026-10-01

Human-confirmed contract relayed by the T19 docs owner: maintenance mode covers database migration and rejects agent MCP/API work, including cheap reads. Gaming alone permits explicitly classified low-cost reads and safe job controls. Health, mode administration, and dashboard remain operator channels.

- `operational_mode_gate_error(..., requires_heavy_work=False)` now allows cheap reads only in active or gaming; maintenance and degraded state fail closed.
- MCP instrumentation gates every agent tool before body execution, ledger/accounting writes, or transport; `local_ai_status` remains the operator health exception. Existing tool-specific gates still decide gaming inference policy.
- HTTP POST requests gate before trace creation, body reads, and route dispatch. Mode/admin-mode, control, telemetry-report, and dashboard operator paths remain exempt. This covers direct async-job controls, evaluation reports, and other agent POST APIs.
- RED receipts: maintenance `local_ai_task` safe actions reached HTTP transport; six direct API safe-action/read cases returned HTTP 200 and reached manager/service stubs; generic MCP repo search and HTTP repo profile also reached backend before the shared fences.
- Focused receipt: **18 passed in 2.93s** across helper, MCP controls, generic MCP action, direct HTTP controls, operator mode read, and maintenance mode control. Maintenance tests assert zero backend, trace, manager, service, context-ledger, and accounting calls; gaming cases assert safe controls still reach handlers.
- Full modified-file receipt: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_operational_mode.py tests/test_operational_mode_http.py tests/test_mcp_agent_routing.py` — **119 passed, 6 failed in 6.47s**. The six failures are known T12-owned release tests: partial Ollama receipt expected `partial` but got `unverified`; missing `SimpleNamespace` import; stale CUDA `status` key expectation; and missing `release()` methods in embedding/reranker test doubles. These were present in earlier candidate receipts and were not changed here.
- Candidate source hashes: `operational_mode.py` `F243EA73BBF204DA9401B234AE1C8F0C92750991E85D5BB8A5C88BC83D00BB74`; `http_server.py` `60D06C590FCF0A6550365D388EDC9FB06C54F78B8319A4A20FBBF4E2767F2E06`; `mcp_server.py` `6F93D152E62D094C3AADE320B6AB01E78D2F386BAE3DAED20B4F8DA9489A6B00`; `HTTP_API.md` `C1943E3ED4D0B2D0614EDAE823C6E8DCFF04020FE12879A7FA720C0157352880`. `git diff --check` passed.
- Release lock regression test hash: `tests/test_operational_mode_http.py` `6D1BD9D2B973F77E6FD249191703B559F98F4E7DEEE7A9CB973B4111A45B3BC5`.
- Root integration stays T20-owned and untouched. T19 owner reported root `operational_mode.py` SHA-256 `D2B510D1ED2A7C7819E0FC063376BB6256C57D6BFFDDE63D872E27D0E758BFD1`; T13 did not verify or edit that source. Root-current docs patch mode-policy hunks remain on HOLD until T20 integrates and validates the corrected helper.

## T19/T20 status refresh

- T19's latest prompt update now states the all-agent maintenance block and marks the prior safe-job exception as pending. Its 2 failures / 17 passes prove docs behavior only; they do not clear root acceptance.
- T13's root-current consumer patch is stale after the child-workspace fix. It still contains `task_payload.setdefault(key, value)`, which lets a parent `root` override an explicit child `cwd`. Patch SHA remains `2DFD20E54161C20F57C447A2433BAAA2570DD3F31DCBEDB1EFDD1FA403237948`; do not apply this artifact as the final T20 integration. Regenerate against T20's current root after incorporating the candidate fix.
- Candidate HTTP gaming release performs model/accelerator cleanup after `operational_mode_change_guard()` exits. Root's reported network-cleanup-under-lock finding remains a T20 integration check; T13 made no root change or live-root claim.
- New candidate regression: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_operational_mode_http.py::test_gaming_cleanup_runs_outside_mode_guard_and_keeps_release_reserved` — **1 passed in 0.41s**. Blocking Ollama cleanup observes the mode guard released; concurrent resume obtains the guard but gets 423 while resource-release reservation remains active; reservation clears after cleanup.
- Candidate receipts above exercise the decorated public MCP functions and HTTP handlers with isolated fakes. They are not a live root MCP/API receipt. T19 pending caveat must stay until T20 integrates the source and attaches fresh root public-surface tests.
- A complete fresh root-current patch cannot be checked from T13-owned evidence: exact root `app.py` preimage is present, but matching `http_server.py` and `mcp_server.py` source copies are absent. Existing consumer-v2 still has the stale child-root `setdefault`; T20 must regenerate and strict-check the whole delta against its current source. No root files were edited.

# T12 operational-mode rejection contract — R10 handoff

This is a new bounded correctness delta over the already-integrated R9 boundary. R9 artifacts remain unchanged. T20 owns root application; re-pin root files at application time.

## Patch

- Patch: `handoff/T12-O2-generation-contract-rootcurrent-r10.patch`
- SHA-256: `162B44C250DFE16F1D73949CF7B2BC368E1F839B4E1AFDCCF1A3FE6B7C1ABFD7`
- Changes only `LocalAIServices._generate` and `tests/test_t12_generation_boundary.py` (68 insertions/18 deletions in services; 88 inserted test lines).
- Read-only `git apply --check --whitespace=error` against `C:\Users\Adam\.local-ai-hub`: PASS; T12 did not edit root.

## Source pins

- Root R9 `services.py` preimage SHA-256: `3369FC0A27ED96682F172A3378B68B5129A928F32113A9F85D1D9D743BC4164C`
- R10 joined `services.py` postimage SHA-256: `416ED8341303463416D4ADBDDE7BC81AEAA3B7D8160294611E84F7354B873434`
- Root R9 barrier test preimage SHA-256: `4A6CC339DB17200DC6DE4749715C68C15AB118D3BB318051C01547A02C82447D`
- R10 joined barrier/contract test postimage SHA-256: `2844F950FE54E0E2824B32F6608F5DCBE2A166DE019B8D60B086980A367187AE`
- Current root manager `async_jobs.py` pin: `77F33CA01FF72B22C2D4E3E080A28767259A02713AD6F7CFE84DA1BE5E2AD5B8`
- T08 candidate manager used for lifecycle/overlay tests: `65166587C7E256C63C7C3717B32DC9A7A2C658487F97EC1C794DC79E73F0C6A8`
- Central gate helper stayed T13-owned; `operational_mode.py` pin at run: `D2B510D1ED2A7C7819E0FC063376BB6256C57D6BFFDDE63D872E27D0E758BFD1`.

## Behavior and focused receipts

`_generate` now returns the exact `operational_mode_gate_error` response for both the pre-start pause and the race where gaming mode commits between the earlier snapshot and nested manager admission. It preserves the response through the model-attempt and cache wrappers, with no fallback attempt, runtime payload, or model-request trace. Mode-load failure passes `None` to the same helper and fails closed using its maintenance response.

- TDD baseline before fix: both ordering tests failed on the mismatched error and response fields.
- T12 barrier + pre-paused contract + mode-load-failure tests: **3 passed**.
- T08 lifecycle + T08/T13/T12 joined consumer overlay with the current candidate manager and matching T13 dependencies: **4 passed**.
- The earlier T13 async project-context suite remains **9 passed**; R10 does not change T13-owned files.
- No GPU/live-model run. Only RTX 4060 host is available; no cross-profile live evidence or optimization claim.

## Integration boundary

R10 is based on the R9 source postimage above. T20 should apply only this delta, preserve concurrent root context, record fresh pre/post hashes, and run owned acceptance. The owned root remains untouched here.
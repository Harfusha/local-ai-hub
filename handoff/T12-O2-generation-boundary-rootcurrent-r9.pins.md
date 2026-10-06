# T12 model-start admission boundary — R9 handoff

Patch and source pins are immutable. T20 owns root application and must re-pin the fresh root preimage immediately before applying.

## Patch

- Patch: `handoff/T12-O2-generation-boundary-rootcurrent-r9.patch`
- SHA-256: `08679F78EE2800D7594AD879086D45D380EBEBC09F8086AC83BA790AEA9A680B`
- Files: `src/local_ai_hub/services.py` (45 insertions, 12 deletions) and new `tests/test_t12_generation_boundary.py` (157 lines).
- Read-only `git apply --check --whitespace=error` against `C:\Users\Adam\.local-ai-hub`: PASS; root was not modified by T12.

## Root-current source identity at check

- `services.py` preimage SHA-256: `170A483C71E81376637A99FCB8385AA4E737E5866BA87954E1C418EBFCE674AA`
- `services.py` joined postimage SHA-256: `3369FC0A27ED96682F172A3378B68B5129A928F32113A9F85D1D9D743BC4164C`
- Barrier test SHA-256: `09A60C2B9CDE4A1E3209A51B4B25EE089941C36878C1F2F98302EE896B19C7DE`
- Root manager `async_jobs.py`: `324181DCDA22F76BF4787455A4EDB05D7BF2A91C76A50F6D2EE081B52FCEA54B`
- Root consumer context: `app.py` `F7360F3A7B266030FF0A79E5C1EA46780D5F3E28E96D2AD89254070656C53A60`; `http_server.py` `4B635B978EF556A69863507D9B7672604068997BE32C55CEFA1E1C1CCCC9C8BE`; `operational_mode.py` `D2B510D1ED2A7C7819E0FC063376BB6256C57D6BFFDDE63D872E27D0E758BFD1`.

## Joined inputs

- Approved R6 strict-timeout patch SHA-256: `BF483E47DA2585363A79CA62D60379EB13CC2528B53D9483D4BBFA5E7AF9114B`.
- T13 consumer-v2 patch SHA-256: `2DFD20E54161C20F57C447A2433BAAA2570DD3F31DCBEDB1EFDD1FA403237948`.
- T08 candidate `async_jobs.py` SHA-256: `65166587C7E256C63C7C3717B32DC9A7A2C658487F97EC1C794DC79E73F0C6A8`.
- Joined scratch service preimage was copied byte-for-byte from the root pin above. No source outside the owned `LocalAIServices._generate` start boundary was included in this patch.

## Focused receipts

- Barrier regression on root-current joined sources: **1 passed**. A real `AsyncJobManager` outer admission is active; the worker pauses after observing active mode; the test commits gaming mode under the manager transition guard; the nested start admission rejects; no runtime payload and no model-request trace are emitted.
- Barrier regression with T08 candidate API SHA `65166587…`: **1 passed**.
- T08 lifecycle tests with explicit T08 candidate source: **2 passed**.
- T08 T13 T12 consumer overlay using T13 candidate app/HTTP, matching root `vision_contracts`, T08 candidate manager, and T12 postimage: **1 passed**.
- T13 async project-context candidate tests: **9 passed**.
- No GPU/live model run performed. Only RTX 4060 host is available; no other profile live evidence or optimization claim.

## Integration boundary

T20 applies the patch to its owned root, preserves concurrent T14 context, records a fresh `services.py` preimage/postimage SHA, and runs its owned acceptance. The patch is based on the root source SHA above; recheck applicability against the then-current source before applying.
## Failed harness variant kept separate

A harness run using canonical root app/HTTP (without its admin audit fixture wiring in the harness) failed before the model-start assertion with `admin audit unavailable`; it is not a passing T13/T12 receipt. The T13 candidate app/HTTP compatibility overlay above passed. An attempt to reuse candidate-specific T08 private-helper fixtures against root `async_jobs.py` also failed because that private helper is not part of the root API; the lifecycle tests passed when explicitly loading the pinned T08 candidate source.
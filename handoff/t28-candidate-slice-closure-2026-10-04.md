# T28 candidate vision slice closure - 2026-10-04

## Candidate and ownership

- Worktree: `C:\Users\Adam\.codex\worktrees\t17-multimodal-resume\.local-ai-hub`
- HEAD: `2b33602adef0d030fea66cdcc04ca742c60b2e32` (detached).
- This continuation made no product-source or test edits. Existing T28 changes were already present in inherited T17 dirty state; selector below verifies them at current hashes.
- T28 disjoint slice: `LocalAIServices.vision()` successful response assembly, `vision_inputs.py`, `vision_response.py`, and T28 parity test in `test_vision_service.py`.
- Inherited/shared dirty changes remain on other listed T17 paths. No root file was written here. Audio WER remains separate T17 gate.

## Immutable patch and source receipts

- Candidate-only result assembly patch: `handoff/t28-vision-result-assembly-extraction.patch`
- Patch SHA-256: `1B7608D5D1347C1FDF8338400F2FFD1F88E4AC2AA4D4DF69366D0131D8078679`
- Patch preimages recorded at application: `services.py` `A3C9C6DBAE5ACFAAC1D543F02783EDA4FBBC89F7991D9870F849972F7224F0C0`; `tests/test_vision_service.py` `25E7055A1BA98EA1446C1F06C3C073A3E46766453B11305CDFD3CBDB049DFEE8`.
- Immediate postimages after that patch: `services.py` `505990A19AF517103A7AEA24EE52289098B3967FC7EE9CC81059A90F983A1568`; `tests/test_vision_service.py` `CE70055A26DACDE600A76C508EDF4C84C8C4E19833D8CF8797B99C5FF4225BCC`.
- Current candidate aggregate postimages include later inherited T17 edits: `services.py` `8CEC8C8F041195622642C2F52962F97176CAB251BB8A57D7F9B7909CC5A9B83C`; `vision_inputs.py` `FAA436CB9F4F0720409E27F45E7908A2BC1AB28EF90D20603A49098959EE1D40`; `vision_response.py` `14C091CBC572011827F985CD92534687AFAFCECC23DC3F516E97CF8AEA7D09BA`; `tests/test_vision_service.py` `7314D975AFDC2F355EC7423F54E088D9D039F3AFC0AF7080C5878CF26A8C14A2`.
- HEAD blobs: `services.py` `6529532559b3dab2a11fbeae913af45d59e9b2d7`; `test_vision_service.py` `ea57e0d42acf0e9af31f0f17f0cd1fc96bcee802`; both new helper modules are untracked relative to HEAD.
- Shared successful-review contract retains `review.observation_sources`; focused test is `test_vision_success_payload_assembles_review_without_runtime`.
- `/api/context/pack`, `transcribe()`, route handlers, and root checkout are outside patch scope.

## Candidate selector

Exact command, run once on the current pinned candidate hashes:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_vision_service.py tests/test_vision_contracts.py tests/test_frontend_review.py
```

Result: exit `0`, `149 passed in 6.84s`.

`git diff --check`: exit `0`. No live model, browser, network, benchmark, or root test was run for this T28 closure. Live vision quality remains `NOT VERIFIED`.
# T28 vision success-payload extraction receipt

Date: 2026-10-04. Applied in the assigned T17 candidate worktree only.

## Scope and baseline

- Candidate HEAD: `2b33602adef0d030fea66cdcc04ca742c60b2e32`.
- `services.py` was already dirty and mixed-owner. User's latest scope explicitly authorizes `LocalAIServices.vision()` only. `transcribe()`, `/api/context/pack`, route bodies, root checkout, and other owners' hunks were not edited.
- Before applying, `git apply --check handoff/t28-vision-result-assembly-extraction.patch` returned exit 0 against the exact current dirty candidate preimage.
- Dirty preimage SHA-256 before patch: `services.py` `A3C9C6DBAE5ACFAAC1D543F02783EDA4FBBC89F7991D9870F849972F7224F0C0`; `test_vision_service.py` `25E7055A1BA98EA1446C1F06C3C073A3E46766453B11305CDFD3CBDB049DFEE8`.
- Exact-scope lease `lease_cb1c8a3119b74929a705` claimed successfully (request `req_40f7af3f909f`) for these two paths and T28 `vision()` payload extraction. Lease arrived after this patch had already been applied under the preceding explicit method-only authorization; no further source edits since lease.

## Applied change

- `src/local_ai_hub/services.py`: extracted `_vision_success_payload()` and replaced the inline success dictionary assembly with a call. Existing key names and values preserved; no auth, timeout, cancellation, fallback, or route flow changed.
- `tests/test_vision_service.py`: added `test_vision_success_payload_assembles_review_without_runtime`, checking success, response, and retention of `review.observation_sources`.
- T28 patch artifact SHA-256: `1B7608D5D1347C1FDF8338400F2FFD1F88E4AC2AA4D4DF69366D0131D8078679`.

## Contract checklist

- Success payload retains keys and values: `success`, `model`, `response`, `review`, `prompt`, `image_artifact_id`, `bundle_artifact_id`, `raw_output_artifact_id`.
- `review` continues to serialize the parsed result, including `observation_sources`; focused test covers this seam.
- Only successful payload assembly was extracted. Auth, timeout, cancellation, capability classification, invalid-output handling, retries/fallbacks, and route behavior were not changed.
- `transcribe()`, `/api/context/pack`, and all other service methods remain outside T28 scope.

## Post-patch working-tree hashes

- `services.py`: `505990A19AF517103A7AEA24EE52289098B3967FC7EE9CC81059A90F983A1568`.
- `test_vision_service.py`: `CE70055A26DACDE600A76C508EDF4C84C8C4E19833D8CF8797B99C5FF4225BCC`.
- Patch: `1B7608D5D1347C1FDF8338400F2FFD1F88E4AC2AA4D4DF69366D0131D8078679`.
## Verification

- `git diff --check -- src/local_ai_hub/services.py tests/test_vision_service.py`: exit 0.
- Focused test command, NOT RUN (T20 GO absent): `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_vision_service.py::test_vision_success_payload_assembles_review_without_runtime`.
- No shared-root tests, benchmarks, or builds run.




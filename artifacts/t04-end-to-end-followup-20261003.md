# T04 end-to-end follow-up — 2026-10-03

## Root-current GET singleflight fix

- Root checkout remained unchanged. HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
- Root preimage SHA-256: `src/local_ai_hub/client.py` `CBE4B84CBB987CB2B2157FEA2224C2B647C5C91573587B67C7FEDB7AD8E9DD8F`; `tests/test_client_transport.py` `FC638D8F041B76D1A9504C6A6E349626043690199ACB999D4610250254336A6B`.
- Patch: `artifacts/t04-singleflight-request-id-root-current.patch`; SHA-256 `AC75F9627D2439A412968F616389988C3062E218F5BC36EB430BEE4CD6286362`.
- Decision: support caller `request_id` in `_singleflight`; GET already passes it and coalesced timeout response reads it from the exception. Coalesced callers also receive their own ID in copied result.
- `git apply --check --whitespace=error` against root: exit 0. Patch not applied to root.
- Candidate RED: `tests/test_client_transport.py::test_get_passes_request_id_through_singleflight` failed with exact `TypeError: HubClient._singleflight() got an unexpected keyword argument 'request_id'`.
- Candidate GREEN: `python -B -m pytest -q --tb=short tests/test_client_transport.py::test_get_passes_request_id_through_singleflight` — 1 passed, exit 0.

## Candidate changes and receipts

- Candidate HEAD: `3658d5056354849ddf17883ed04f807f16cc44c1`.
- `src/local_ai_hub/client.py` current SHA-256: `D4B42B5369973140D573FE0BAEE4276E62BACD87C07F88C1C7DD151494E66EC0` (contains inherited T04 work plus current lock recovery, managed-mode gate, retry policy, and singleflight changes; do not treat whole file as newly authored here).
- `tests/test_client_transport.py` SHA-256: `BCE65436B206027C0221082EC3B0C78DA50E8E68B32DD351C2B800979F32D68F`.
- Focused mock lifecycle/mode/lock/request-ID selectors — 15 passed in 3.43s, exit 0. Includes 30-thread mock service-start coordination; not multi-process runtime evidence.
- Earlier focused run of startup/mode/MCP/path-hint files — 27 passed, 9 failed. After test fixture corrections, remaining observed failures: actual child not recorded in two MCP stdio tests, actual Hub child `/api/search` did not become ready, and path-hint HTTP search still returned `secret/blocked.py` despite fixture exclusion. These remain unverified/blocking; no source change made to T03-owned HTTP/MCP adapter paths.
- Earlier cross-process selector starts two Python workers but mocks service start. It proves lock coordination, not a real daemon. Current receipts provide no valid real multi-process/RSS measurement.
- The Windows test state dirs contained only managed/operational metadata and no `hub.pid`; process inventory matched no child using those test configs. No test process remained to clean up.
- Broader pre-follow-up suite result was 137 passed, 12 failed, 1 skipped before final candidate edits. Do not claim full suite pass.
- Root patch and T04 worktree are separate. No root edit, commit, or HUB call.

# T04 singleflight request ID runtime compatibility

## Finding

The exact `unexpected keyword argument 'request_id'` is a caller/method version mismatch.

- T04 baseline: HEAD `3658d5056354849ddf17883ed04f807f16cc44c1`; `client.py` blob `3efbfc395bf512f3cc7b9d713ee3d1a665288eb5`. Its `_singleflight(self, key, timeout, execute)` has no `request_id` keyword.
- T04 working source: `src/local_ai_hub/client.py`, SHA-256 `D4B42B5369973140D573FE0BAEE4276E62BACD87C07F88C1C7DD151494E66EC0`. Its keyword-only signature accepts `request_id: str | None = None` and `cancel_event`; the GET caller passes both.
- Root source: `C:\Users\Adam\.local-ai-hub\src\local_ai_hub\client.py`, SHA-256 `7D0EF3BE7A95152318FAE1B7E7B8376BFAAE065EEAD4C5CC4F2A37C1DF06DEA2`. Its signature accepts both keywords; current callers at lines 826 and 900 use `cancel_event` and `request_id`, respectively.
- T26 source: `client.py`, SHA-256 `393791DFC87F64247DB675B1E76C86DF6B4C666B937B70CAD2A55FC7BE44502C`; its signature accepts `request_id`.
- T04 `pyproject.toml` maps the package to `src` (lines 44, 47), but this does not identify the module loaded by the live MCP process.

So the T04 baseline is incompatible with its newer caller; the T04 working tree already contains the minimal signature compatibility change. The live runtime's import path/version remains unproven. Do not claim stale installation as fact without `local_ai_hub.client.__file__` and loaded signature from that process.

## Candidate delta and preimages

Changed source: `src/local_ai_hub/client.py`.

Preimage: T04 HEAD blob `3efbfc395bf512f3cc7b9d713ee3d1a665288eb5`.

Current candidate SHA-256: `D4B42B5369973140D573FE0BAEE4276E62BACD87C07F88C1C7DD151494E66EC0`.

The relevant working-tree delta adds keyword-only `request_id` and `cancel_event` to `_singleflight`; the existing complete source diff remains the patch. No root or MCP server files were changed.

## Coalesced ID follow-up

The candidate waiter path currently overwrites the response's `request_id` with the waiter's ID. The regression `tests/test_client_transport.py::test_coalesced_get_returns_server_visible_owner_request_id` expects the response ID to remain the owner ID actually sent in `X-LocalAI-Request-ID`. Its source predicts a failure, but it has not been run. Keep this separate from the signature mismatch fix; preserve cleanup ordering and retry/result shape when repairing it.

## Validation gate

No tests run: T20 has not granted a slot. After explicit T20 GO, run from this worktree:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_client_transport.py::test_get_passes_request_id_through_singleflight tests/test_client_transport.py::test_coalesced_get_returns_server_visible_owner_request_id
```

The T04 test-file baseline blob is `87d78946c7dec5c7a262ffea1a7f0b73bd03aac8`; current test SHA-256 is `808F1661D41B14A3A7E5F63C228CF64A270C142155B3BFDCC09B516C571949D3`.

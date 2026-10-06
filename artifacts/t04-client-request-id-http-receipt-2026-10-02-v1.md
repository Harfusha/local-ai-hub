# T04 API client request-ID loopback receipt

Date: 2026-10-02 (Europe/Prague)
Worktree: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`
HEAD: `3658d5056354849ddf17883ed04f807f16cc44c1`
Branch: `codex/t04-integration-2b33602`

## Change

Added `tests/test_t04_client_request_id_http.py`. A real loopback HTTP server returns retryable `503 in_progress`, then success. The `HubClient` test verifies the same caller-supplied `X-LocalAI-Request-ID` and request body reach both attempts, and the decoded result keeps that ID.

## Exact commands and results

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t04_client_request_id_http.py
```

Result: **1 passed in 2.38s**, exit 0.

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_client_transport.py tests/test_t04_client_retry_acceptance.py tests/test_t04_malformed_json_contract.py tests/test_t04_request_id_preflight.py tests/test_t04_client_auth_transport.py tests/test_t04_client_request_id_http.py
```

Result: **39 passed in 4.66s**, exit 0.

The first isolated run exposed a fixture-only config error (`max_request_timeout_seconds` minimum is 5); the fixture was corrected, then the isolated and combined commands above passed.

## Ownership

Base and inherited state rechecked: `3658d5056354849ddf17883ed04f807f16cc44c1`, branch `codex/t04-integration-2b33602`. `client.py` SHA-256 remained `DCDF8BB8FF150B5FCD4EDD3A25B53991DD6B87CDB9DDDEC0714A7F11B2FAE5B1`; `mcp_server.py` remained `A6449D390F27ED56C89139AC56518AD0D57AB9285FFD7FAD05E7D000D6729F50`; `test_client_transport.py` remained `777CC424B651130DC96FE4D2EAC21FE6E4C152E1C19C46F18EAE380587F588F3`. Existing dirty hunks were preserved. Only the new T04 test and this receipt were added for this request. No root or `/api/context/pack` edits.

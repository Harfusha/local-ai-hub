# T04 public HTTP handoff receipt — 2026-10-01 v2

Supersedes receipt v1 with fresh retry/request-id evidence. Patch remains v2; no client source is included.

## Target and patch

- Candidate HEAD: `3658d5056354849ddf17883ed04f807f16cc44c1`.
- Test file SHA-256: `89CABF4A047CBFF388612B550BED7D1689B1A9937EE0A8C910C59680C7A282CD`.
- Add-file patch: `handoff/t04-public-http-stream-conversation-auth-cancel-deadline-2026-10-01-v2.patch`.
- Patch SHA-256: `9BB4416E074EED6A5424E3F21B3E2C851FFFEF354E1749FC52A06276B92203D5`.
- v1 patch is superseded. Apply v2 only; it adds `tests/test_t04_public_http_stream_acceptance.py`.
- Current-root `git apply --check` passed. Root test destination remains absent. No root files changed by T04.

## Exact current-root pins

Root HEAD remained `98a9a1a7611af574caf20a88620c4aa3eb2e918a` during focused E2Es. The following hashes matched before and after public route tests, and matched after the retry/request-id selectors:

- `src/local_ai_hub/http_server.py`: `4B635B978EF556A69863507D9B7672604068997BE32C55CEFA1E1C1CCCC9C8BE`
- `src/local_ai_hub/client.py`: `5518706E0E81623E3FF0184274BD17F18C9BF7F43D9BC4DD37FD754586B0D056`
- `src/local_ai_hub/mcp_server.py`: `8EC5C493964419233A349A78ECCA6487A78078B6125A7A328980877B3AA132FB`

All root tests below imported `C:\Users\Adam\.local-ai-hub\src\local_ai_hub` explicitly through `PYTHONPATH`; root remained read-only.

## Fresh acceptance results

1. Candidate test, ResourceWarning elevated to error:
   `python -X tracemalloc=6 -B -m pytest -q -p no:cacheprovider -W error::ResourceWarning --tb=short tests/test_t04_public_http_stream_acceptance.py::test_public_http_conversation_auth_stream_cancel_and_deadline`
   - `1 passed in 11.08s`.

2. Current-root path-hint public MCP/HTTP chain plus public conversation/auth/cancel/deadline test:
   - `2 passed in 13.58s`.
   - Conversation start/continue uses actual HTTP Handler and HubClient; generation is stubbed. Missing token gets 401 before generation. Authenticated SSE replays persisted AgentState event. Cancel stops blocked read. Deadline returns `retry_timeout` and `outcome_unknown`.

3. Current-root daemon-off MCP status plus MCP-owned autostart/payload fixture:
   - `2 passed in 11.60s`.

4. Candidate real child cold-start, HTTP search result, PID lock, and owned-child cleanup:
   - `1 passed in 10.21s`.

5. Current-root retry/request-id selectors (stable safe GET request ID, no replay of unsafe POST, malformed request ID rejected before body/journal/dispatch):
   - `3 passed in 2.69s`.

No live Hub, GPU, or T02 benchmark used. Autostart child ran only in bounded temporary candidate fixture with external model backends disabled.

## Status

Handoff artifact is ready for T20. T04 remains partial pending T20 patch integration/receipt and T21 adapter/runtime proof. Do not interpret this focused evidence as full goal completion.

# T04 assigned-worktree API client and conversation transport acceptance v2

Date: 2026-10-01
Candidate worktree: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`
Candidate HEAD: `3658d5056354849ddf17883ed04f807f16cc44c1`

This receipt supersedes the stale blocker wording in v1. T04 acceptance uses only assigned-worktree paths. No T13 files or `/api/context/pack` were read or changed by this verification.

## Exact candidate results

1. Command: `python -B -m pytest -q --tb=short tests/test_client_transport.py -k 'not coord_pubsub_poll_uses_after_seq_in_json_body'`
   Result: **27 passed, 1 deselected in 3.78s**. Covers pooled HTTP reuse, idle disconnect/reconnect, request coalescing, safe/unsafe retry, request-ID validation, transport/connect/write failure classifications, malformed-response outcomes, timeout, SSE partial disconnect/cancel/deadline, stale pooled connection, and worker-thread cleanup.

2. Command: `python -B -m pytest -q --tb=short tests/test_conversations.py tests/test_mcp_agent_routing.py::test_local_ai_task_forwards_continue_with_opaque_conversation_id tests/test_t04_client_auth_transport.py tests/test_t04_public_http_stream_acceptance.py`
   Result: **13 passed in 13.96s**. Covers conversation lifecycle and opaque continuation, auth boundary, public HTTP conversation start/continue, SSE replay/auth, cancellation, and deadline response contract.

3. Command: `python -B -m pytest -q --tb=short tests/test_client_transport.py::test_coord_pubsub_poll_uses_after_seq_in_json_body`
   Result: **1 passed in 1.54s**. This was run separately. It proves exact integer `after_seq` JSON payload for default and explicit cursors.

4. Check: `git diff --check -- src/local_ai_hub/client.py src/local_ai_hub/http_server.py tests/test_client_transport.py`
   Result: passed. Git prints existing CRLF advisory for `tests/test_client_transport.py` only.

## Candidate source pins

- `src/local_ai_hub/client.py`: `DCDF8BB8FF150B5FCD4EDD3A25B53991DD6B87CDB9DDDEC0714A7F11B2FAE5B1`
- `tests/test_client_transport.py`: `777CC424B651130DC96FE4D2EAC21FE6E4C152E1C19C46F18EAE380587F588F3`
- `src/local_ai_hub/http_server.py`: `840933FF8801832D4DDC4746853011AB1486338EA42BBA186E137393574156D7`
- `src/local_ai_hub/conversations.py`: `46DBCC009505CC15C91D76B6BAECD9B7B6B0BE956CF0317402CE7500CBCC4E09`
- `tests/test_conversations.py`: `DA4822506DE70C66AA1204D6A44F1CECAEA766EBAD90DA012A67E933866973D7`
- `tests/test_mcp_agent_routing.py`: `6150D24029076D29343E9CEF648E61C2FE4C025A9F800C221CB1868618423F54`
- `tests/test_t04_client_auth_transport.py`: `56B2A4D1348EBF4B1F89F02A6493FA660BC058B9FD2A5585D2F91F662A4EBCE7`
- `tests/test_t04_public_http_stream_acceptance.py`: `9E6A8FE9FD52B8DDBC721663FC2E85CB19BA20009B44B7BD977B7D4FA135B510`

No new source or test edits were needed: all selected contracts pass at these pins. T04 made no root edits and did not integrate foreign patches. Root integration remains T20-owned.

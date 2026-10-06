# T04 end-to-end acceptance closeout v2

Date: 2026-10-01 (Europe/Prague)
T04 candidate worktree: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`
T04 candidate HEAD: `3658d5056354849ddf17883ed04f807f16cc44c1`
Integrated root: `C:\Users\Adam\.local-ai-hub`
Current root HEAD: `01df56605ccf484ebfe2808ac60d696c4e81dffc`

## Acceptance result

Full T04 API/client/conversation acceptance passes. Current root T20 integration remains intact. No production source edits were made by this verification. `/api/context/pack` was not accessed or changed. T13 files were not accessed. Tests use temporary fixtures; actual Hub child test uses isolated config/state and CPU-only setup. No live user Hub, secrets, models, or GPU used.

## Current root integrated verification

Exact command:

`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_client_transport.py tests/test_conversations.py tests/test_mcp_agent_routing.py tests/test_t04_current_root_acceptance.py tests/test_t04_client_auth_transport.py tests/test_t04_client_retry_acceptance.py tests/test_t04_malformed_json_contract.py tests/test_t04_root_request_id_preflight.py tests/test_t04_root_path_hint_chain.py tests/test_t04_public_http_stream_acceptance.py tests/test_t04_mcp_status_actual_hub_child.py tests/test_t04_real_child_startup_acceptance.py tests/test_agent_task_query.py tests/test_client_path_hints.py tests/test_artifact_tenant_isolation.py`

Result: **120 passed in 63.70s**, exit 0.

This root-current batch covers retry/request IDs, timeout/disconnect/malformed response outcomes, client path-hint serialization, conversation continuation, auth, SSE replay/cancel/deadline, HTTP API compatibility, task query/owner search/truncation, artifact tenant isolation, daemon-off MCP status, real Hub entrypoint cold start, readiness, and owned process shutdown.

Relevant root SHA-256 at verification:

- `src/local_ai_hub/client.py`: `5518706E0E81623E3FF0184274BD17F18C9BF7F43D9BC4DD37FD754586B0D056`
- `src/local_ai_hub/http_server.py`: `BDB4ECF50C149FCB144F3745EC9AB58FCE029F900A6ED83A41C5FAF1D2C9BECB`
- `src/local_ai_hub/mcp_server.py`: `5FF372AF25D78EDBB09B7F6D3AB6ECF5F8C9C593247F38A7B01C2CFF8E7929CE`
- `src/local_ai_hub/conversations.py`: `57D22C57DDE990FE1E0C8F91B115457C89981722DF6A26EFF2125FF66B578670`
- `src/local_ai_hub/agent_tasks.py`: `79487FCE9F8A477A9DE888A6C7FEF77C3526F9B63151EF69FF0CE2019502BA45`
- `tests/test_agent_task_query.py`: `0F5CE4A1805C18919DFF1360729E510786C8E99B725FB690A69C278E2D53A86B`
- `tests/test_t04_public_http_stream_acceptance.py`: `1A7EC182E1D79F408301C2E99EBB80356F559C349BE4C5381FB85D50174A4FB2`
- `tests/test_t04_mcp_status_actual_hub_child.py`: `AA5913E80A5CAA6FDDFEA1E397DC050F2F1180D4AFF482F5AD3A49529F37420E`

The two previously failing query selectors both passed in the 120-test batch. T09 owner receipt reports its isolated query suite **8/8**. No T09 files were edited by T04.

## Assigned candidate receipts

- Nine-file T04 assigned suite: **132 passed in 26.57s**, log SHA-256 `7CC3BE41A4D4E4CD8471DDEE0287A3BD8FF5F3318D80E56D2A10277B70E03403`.
- Public API/conversation/query/inventory selectors: **39 passed in 43.83s**.
- Client-to-loopback path-hint suite: **7 passed in 2.31s**.
- Client transport (excluding the separately passing pubsub case): **27 passed, 1 deselected in 3.78s**.
- Conversation/auth/public HTTP stream group: **13 passed in 13.96s**.
- Pubsub cursor exact body: candidate **1 passed in 1.54s**; current root **1 passed in 1.57s**.
- Actual first registered MCP status started real `local_ai_hub.__main__`; child source/argv, ready status, hidden Windows launch and owned cleanup were proven in the test receipts.

Candidate source pins remain at assigned HEAD `3658d5056354849ddf17883ed04f807f16cc44c1`: `client.py` `DCDF8BB8FF150B5FCD4EDD3A25B53991DD6B87CDB9DDDEC0714A7F11B2FAE5B1`; `http_server.py` `840933FF8801832D4DDC4746853011AB1486338EA42BBA186E137393574156D7`; `mcp_server.py` `A6449D390F27ED56C89139AC56518AD0D57AB9285FFD7FAD05E7D000D6729F50`; `conversations.py` `46DBCC009505CC15C91D76B6BAECD9B7B6B0BE956CF0317402CE7500CBCC4E09`.

## Dirty-state and ownership

Before validation, T04 candidate worktree contained mapped mixed-owner dirty source/tests and untracked acceptance artifacts. T04 preserved them. The existing ownership map identifies T04 edits separately from inherited T07/T10/T13/T21 hunks. Current root also contains T20 integration changes and owner work; T04 wrote nothing to root. Relevant `git diff --check` passed; only existing CRLF advisory was emitted.

T04 acceptance is complete. T20 still owns overall release integration/acceptance outside T04 scope.

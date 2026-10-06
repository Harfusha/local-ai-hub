# T04 API client acceptance closeout v1

Date: 2026-10-01
T04 worktree: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`
T04 HEAD: `3658d5056354849ddf17883ed04f807f16cc44c1`
Current root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`

## Final query blocker verification

T09 owner receipt reports owner search and bounded truncation fix, isolated overlay query suite **8/8 passed**, and `git apply --check` passed. Root was unchanged during that T09 validation.

T04 then verified only the two previously failing selectors against current root:

`python -B -m pytest -q --tb=short tests/test_agent_task_query.py::test_task_query_reports_bounded_scan_truncation tests/test_agent_task_query.py::test_http_task_query_searches_contract_checkpoint_and_owner_before_limit`

Result: **2 passed in 10.76s**. The capped scan reports truncation; owner search returns matching task.

Root pins at verification:

- `src/local_ai_hub/agent_tasks.py`: `79487FCE9F8A477A9DE888A6C7FEF77C3526F9B63151EF69FF0CE2019502BA45`
- `src/local_ai_hub/http_server.py`: `520A77B5F2B8E0B4C4C9FC68A8B7E7718DD3A170C37E197AF1623F4C0853C38D`
- `src/local_ai_hub/client.py`: `5518706E0E81623E3FF0184274BD17F18C9BF7F43D9BC4DD37FD754586B0D056`
- `src/local_ai_hub/mcp_server.py`: `5FF372AF25D78EDBB09B7F6D3AB6ECF5F8C9C593247F38A7B01C2CFF8E7929CE`
- `tests/test_agent_task_query.py`: `0F5CE4A1805C18919DFF1360729E510786C8E99B725FB690A69C278E2D53A86B`

T09 owner checkout pin differs from integrated root pin: T09 checkout HEAD `968443549f2a68d17df26689cd49874d1ce400de`, T09 `agent_tasks.py` SHA `31BB08EF5837C5406F5A5D227FC2E96D9BC82970DD5645C5E1248EB349FBFFAB`. This receipt combines the owner's isolated 8/8 result with direct current-root proof for both formerly failing selectors; it does not assert the complete T09 source file is byte-identical to root.

## T04 API/client/conversation evidence

- Root-current transport selectors (timeouts, retry, disconnect, response contracts), excluding separately checked pubsub selector: **26 passed, 1 deselected in 4.53s**.
- Root-current conversation/auth/public HTTP stream group: **15 passed in 10.91s**.
- Root-current `test_coord_pubsub_poll_uses_after_seq_in_json_body`: **1 passed in 1.57s**; candidate equivalent **1 passed in 1.54s**. Both test files import `json`; candidate/root implementation branch hashes match. No code patch required.
- Earlier integrated root-current T04 run: **50 passed**, covering client transport, auth, request-ID, path hints, public conversation/auth/cancel/deadline, MCP status/real Hub child, and routes.
- Actual first registered MCP status cold-started the real `local_ai_hub.__main__` child under isolated temp config/state, proved readiness and owned shutdown; source evidence in `artifacts/t04-mcp-status-actual-hub-child-2026-10-01-v1.md`.
- T21 owner supplied current-root accepted-hint E2E and route-chain/policy/consumer receipts; T04's root path-hint MCP/HTTP chain also passed within integrated root evidence.

No `/api/context/pack` edits. No live user Hub, production config, secrets, GPU, model, or benchmark used. No root files were edited by T04 verification. No T04 client code patch required; current root already passes transport contracts.

## Status

T04 API/client/conversation acceptance is complete at the tested source pins. Remaining maintenance-gate issue reported earlier belongs to T13 and is outside T04. T20 owns overall release integration/acceptance beyond this T04 closeout.

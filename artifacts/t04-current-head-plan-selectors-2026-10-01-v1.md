# T04 current-head plan selector refresh receipt v1

Date: 2026-10-01
Candidate: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`
Candidate HEAD: `3658d5056354849ddf17883ed04f807f16cc44c1`

Fresh native pytest selectors against current candidate source:

- API/conversation/public description selectors: 17 passed in 6.96s. Includes `tests/test_conversations.py`, opaque conversation forwarding, resolve import GET/POST default, unsupported completions, task query forwarding, public descriptions, and semantic diff route.
- Current operation/artifact/review equivalents: 6 passed in 4.88s. Includes parameterized `include_code`, public artifact list metadata/no-ID contract, v2 and legacy tenant isolation, and foreground review result.
- Query filtering/validation: 3 passed in 8.44s. Includes GET filtering/checkpoint-before-limit, POST non-string rejection, and MCP query forwarding.

Total: 26 passed across three bounded groups. No broader suite rerun.

Two selectors recorded in the old plan no longer resolve in this candidate: `test_unsupported_chat_completions_rejects_before_payload_validation` is now `test_unsupported_chat_completions_rejects_valid_payload`; `tests/test_operation_contracts.py` is absent. The tests above use current equivalents found in `test_t04_public_api_contracts.py` and `test_mcp_agent_routing.py`. The stale selector attempts collected no tests; no test failure occurred.

Actual Hub entrypoint/MCP status cold-start proof is in `artifacts/t04-mcp-status-actual-hub-child-2026-10-01-v1.md` with add-file patch `handoff/t04-mcp-status-actual-hub-child-2026-10-01-v1.patch`. Separate T21 adapter/runtime evidence remains outstanding.

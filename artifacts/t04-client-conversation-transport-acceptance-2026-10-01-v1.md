# T04 client and conversation transport acceptance receipt v1

Date: 2026-10-01
Candidate worktree: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`
Candidate HEAD: `3658d5056354849ddf17883ed04f807f16cc44c1`
Current root: `C:\Users\Adam\.local-ai-hub`
Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`

## Results

No product or test patch was required. The reported `test_coord_pubsub_poll_uses_after_seq_in_json_body` failure did not reproduce: candidate and root both passed it. Both test files contain `import json`; both client implementations have identical `pubsub_poll` branch SHA-256 `5704D5532407D1C26E7BC30D7ACBC76059585D3E8BA2D8BD4C044B97BE0D1F0E`. The test verifies integer `after_seq` and exact JSON bodies for default cursor 0 and explicit cursor 17.

Remaining candidate transport selectors, excluding the separately passing pubsub selector: `python -B -m pytest -q --tb=short tests/test_client_transport.py -k 'not coord_pubsub_poll_uses_after_seq_in_json_body'` — **27 passed, 1 deselected in 3.78s**. Covers HTTP connection reuse, idle disconnect reconnect, safe and unsafe retry, request-ID validation, connect/write failure outcome classification, malformed response contract, coalescing timeout, SSE timeout/cancel/partial disconnect, stale pooled connection behavior, and threaded close.

Candidate conversation/auth/public-stream group: `python -B -m pytest -q --tb=short tests/test_conversations.py tests/test_mcp_agent_routing.py::test_local_ai_task_forwards_continue_with_opaque_conversation_id tests/test_t04_client_auth_transport.py tests/test_t04_public_http_stream_acceptance.py` — **13 passed in 13.96s**.

Current-root conversation/auth/public-stream group, same selectors: **15 passed in 10.91s**.

Current-root transport selectors excluding separately passing pubsub selector: **26 passed, 1 deselected in 4.53s**. Collection differs by one candidate-only query-serialization selector.

Previously run pubsub selector: candidate **1 passed in 1.54s**; root **1 passed in 1.57s**.

`git diff --check` passed for relevant candidate and root paths; Git emitted only the existing CRLF advisory for `tests/test_client_transport.py`.

## Source pins

| File | Candidate SHA-256 | Root SHA-256 |
|---|---|---|
| `src/local_ai_hub/client.py` | `DCDF8BB8FF150B5FCD4EDD3A25B53991DD6B87CDB9DDDEC0714A7F11B2FAE5B1` | `5518706E0E81623E3FF0184274BD17F18C9BF7F43D9BC4DD37FD754586B0D056` |
| `tests/test_client_transport.py` | `777CC424B651130DC96FE4D2EAC21FE6E4C152E1C19C46F18EAE380587F588F3` | `03000F1016075FC4B4025F9185CFFB471043663028F04496B0CD4F42D5EA06A0` |
| `src/local_ai_hub/http_server.py` | `840933FF8801832D4DDC4746853011AB1486338EA42BBA186E137393574156D7` | `6F0B986255DD231F40761538227A66F0A9B97F7659064952593FB83B48130DB3` |
| `src/local_ai_hub/conversations.py` | `46DBCC009505CC15C91D76B6BAECD9B7B6B0BE956CF0317402CE7500CBCC4E09` | `57D22C57DDE990FE1E0C8F91B115457C89981722DF6A26EFF2125FF66B578670` |
| `tests/test_conversations.py` | `DA4822506DE70C66AA1204D6A44F1CECAEA766EBAD90DA012A67E933866973D7` | `1C309E8DF75C3CF9E4D3B58DF514CA26450B5136B04B49A1C66C6B27FF58EE75` |
| `tests/test_mcp_agent_routing.py` | `6150D24029076D29343E9CEF648E61C2FE4C025A9F800C221CB1868618423F54` | `D3E0AB9139872A722EC24A8B7C6D7D8571262D5C676E800047CDF1A135A8AF96` |
| `tests/test_t04_client_auth_transport.py` | `56B2A4D1348EBF4B1F89F02A6493FA660BC058B9FD2A5585D2F91F662A4EBCE7` | `23543817A7CAB8B966DAAE8DA4B09B1DBC2B2F66FDF8E081B1CA6ACBBB1963C5` |
| `tests/test_t04_public_http_stream_acceptance.py` | `9E6A8FE9FD52B8DDBC721663FC2E85CB19BA20009B44B7BD977B7D4FA135B510` | `1A7EC182E1D79F408301C2E99EBB80356F559C349BE4C5381FB85D50174A4FB2` |

No root files changed during verification. No patch emitted because root already passes this contract.

## Remaining blockers

This receipt covers client/conversation transport only. Existing T09-owned `agent_tasks.py` query failures remain separately reported: `test_task_query_reports_bounded_scan_truncation` and `test_http_task_query_searches_contract_checkpoint_and_owner_before_limit`. Do not mark all T04 acceptance complete until owner fix and integrated acceptance pass.
